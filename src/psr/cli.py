"""端到端編排。

執行順序刻意讓 **Drive 的狀態本身就是 checkpoint**：產物依
mp3 → words.json → raw.srt → manifest → zh-Hant.srt 的順序上傳，
最終 SRT 最後才寫。中途死掉時 Drive 有前面的產物、沒有最終檔，下次重跑
自動從斷點續，不需要任何外部狀態儲存。
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

from googleapiclient.discovery import build

from psr import drive, glossary as glossary_mod, manifest as manifest_mod, polish as polish_mod
from psr.align import align
from psr.asr import colab as colab_asr
from psr.asr.colab import ColabUnavailable
from psr.issue import parse_issue
from psr.models import Cue, Word
from psr.refine import enforce_duration, merge_short_cues, strip_leading_punctuation, wrap_lines
from psr.segment import raw_segment
from psr.srt import render
from psr.validate import validate
from psr.youtube import drive_paths, slugify

TOKEN_PATH = pathlib.Path.home() / ".config/polish-screen-record/token.json"
ASR_STAGE_VERSION = "1"
POLISH_STAGE_VERSION = "1"


def _youtube_title(video_id: str) -> str:
    out = subprocess.run(
        ["yt-dlp", "--skip-download", "--print", "%(title)s",
         f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _resolve_target(service, source):
    """決定產物的資料夾與檔名前綴。

    Drive 來源沿用影片所在的資料夾與檔名；YouTube 來源則在 videos/<slug>/
    底下開一個新資料夾，slug 保留中文只去符號——那個資料夾會出現在使用者
    自己的 Drive 裡，看得懂比 ASCII 安全重要。
    """
    if source.kind == "drive":
        info = drive.preflight(service, source.id)
        stem = info.name.rsplit(".", 1)[0]
        return info.parents[0], stem, info.md5_checksum, info
    slug = slugify(_youtube_title(source.id))
    root = drive.ensure_folder(service, "videos", None)
    folder = drive.ensure_folder(service, slug, root)
    return folder, slug, "", None


def _build_cues(words, windows, audio_duration):
    """把每個窗口的潤稿行貼回時間軸；沒潤到的窗口退回決定性斷句。"""
    cues, degraded = [], 0
    for window_words, lines in zip(windows, words):
        got = align(window_words, lines) if lines else None
        if got is None:
            degraded += 1
            got = raw_segment(window_words)
        cues.extend(got)

    cues = [Cue(i + 1, c.start, c.end, c.text) for i, c in enumerate(cues)]
    cues = merge_short_cues(cues)
    cues = strip_leading_punctuation(cues)
    flat = [w for ws in windows for w in ws]
    cues = enforce_duration(cues, flat, audio_duration=audio_duration)
    cues = wrap_lines(cues)
    return [Cue(i + 1, c.start, c.end, c.text) for i, c in enumerate(cues)], degraded


def _transcribe(source, creds, gloss, work_dir):
    """Colab 為主、Groq 為備。

    只有 ColabUnavailable（配不到 GPU、VM 被斷、超時）才 fallback。程式邏輯
    錯誤直接往上拋——被 fallback 掩蓋成「反正 Groq 跑得出來」的話，Colab
    這條路壞掉了永遠不會有人發現。
    """
    prompt = gloss.whisper_prompt()
    try:
        token = drive.mint_readonly_access_token(creds)
        words, meta = colab_asr.transcribe(
            source.kind, source.id, token, prompt, work_dir)
        return words, meta, "colab"
    except ColabUnavailable as exc:
        print(f"[fallback] Colab 不可用：{exc}", file=sys.stderr)

    from psr.asr import groq as groq_asr
    video = pathlib.Path(work_dir) / "source.mp4"
    if source.kind == "drive":
        service = build("drive", "v3", credentials=creds)
        drive.download(service, source.id, str(video))
    else:
        subprocess.run(["yt-dlp", "-f", "bv*+ba/b", "--merge-output-format", "mp4",
                        "-o", str(video),
                        f"https://www.youtube.com/watch?v={source.id}"], check=True)
    audio = pathlib.Path(work_dir) / "audio.mp3"
    groq_asr.extract_audio(video, audio)
    words = groq_asr.transcribe(audio, prompt, work_dir)
    return words, {"audio_duration": groq_asr.probe_duration(audio)}, "groq"


def run(report_path: str) -> int:
    body = os.environ.get("ISSUE_BODY", "")
    dry_run = os.environ.get("DRY_RUN", "").lower() == "true"
    started = time.time()

    source = parse_issue(body)
    creds = drive.load_credentials(TOKEN_PATH.read_text(encoding="utf-8"))
    service = build("drive", "v3", credentials=creds)
    folder_id, stem, source_md5, _ = _resolve_target(service, source)
    names = drive_paths(stem)
    gloss = glossary_mod.load("glossary.yml")

    man = manifest_mod.Manifest(source=f"{source.kind}:{source.id}", source_md5=source_md5)
    man.stage_keys["asr"] = manifest_mod.stage_key(
        "asr", ASR_STAGE_VERSION, [source_md5 or source.id],
        {"engine": "faster-whisper-large-v3", "prompt": gloss.whisper_prompt()})

    with tempfile.TemporaryDirectory() as work:
        words_raw, meta, engine = _transcribe(source, creds, gloss, work)
        words = [Word(w["text"], w["start"], w["end"]) for w in words_raw]
        audio_duration = float(meta.get("audio_duration") or (words[-1].end if words else 0.0))
        man.engine = engine
        man.gpu_model = meta.get("gpu", "")
        man.timings.update(meta.get("seconds", {}))

        man.stage_keys["polish"] = manifest_mod.stage_key(
            "polish", POLISH_STAGE_VERSION,
            [man.stage_keys["asr"], gloss.content_hash()],
            {"model": "deepseek-v4-flash"})

        windows = polish_mod.make_windows(words)
        lines_per_window, result = polish_mod.polish_words(words, gloss)
        cues, degraded = _build_cues(lines_per_window, windows, audio_duration)

        man.degraded_window_count = degraded
        man.cost = round(result.prompt_tokens / 1e6 * 0.14
                         + result.completion_tokens / 1e6 * 0.28, 4)
        man.timings["total"] = round(time.time() - started, 1)

        violations = validate(cues, audio_duration)
        srt_text = render(cues)

        links = {}
        if not dry_run:
            work_dir = pathlib.Path(work)
            # 順序即 checkpoint：最終 SRT 最後上傳。
            for local_name, remote_name, payload in (
                ("words.json", names["words"], json.dumps(words_raw, ensure_ascii=False)),
                ("raw.srt", names["raw_srt"], render(raw_segment(words))),
                ("manifest.json", names["manifest"], man.to_json()),
                ("final.srt", names["srt"], srt_text),
            ):
                p = work_dir / local_name
                p.write_text(payload, encoding="utf-8")
                meta_up = drive.find_or_create(
                    service, remote_name, folder_id, str(p), "text/plain")
                links[remote_name] = meta_up.web_view_link

    lines = [
        f"### {'（dry-run，未寫入 Drive）' if dry_run else '完成'}",
        "",
        f"- 來源：`{source.kind}:{source.id}`",
        f"- 轉錄引擎：**{engine}**"
        + (f"（{man.gpu_model}）" if man.gpu_model else ""),
        f"- 音訊長度：{audio_duration / 60:.1f} 分鐘，{len(words):,} 個 word",
        f"- 字幕：{len(cues):,} 條，降級窗口 {degraded}/{len(windows)}",
        f"- 潤稿成本：約 ${man.cost:.4f}",
        f"- 總耗時：{man.timings['total']:.0f} 秒",
        f"- 驗證：{'✅ 零違規' if not violations else f'⚠️ {len(violations)} 個違規'}",
    ]
    if links:
        lines += ["", "產物："] + [f"- [{n}]({u})" for n, u in links.items() if u]
    if dry_run:
        preview = "\n".join(srt_text.split("\n\n")[:6])
        lines += ["", "前 6 條預覽：", "", "```", preview, "```"]
    pathlib.Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="psr")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_cmd = sub.add_parser("run", help="從 ISSUE_BODY 執行完整 pipeline")
    run_cmd.add_argument("--report", default="report.md")
    args = parser.parse_args(argv)
    if args.cmd == "run":
        return run(args.report)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
