"""Colab CLI 編排——主轉錄路徑。

實測（2026-08-16）：`colab run --gpu T4` 從配置到釋放全程 19.8 秒，
87 分鐘音訊在 T4 上轉錄 397 秒（13.2 倍實時）。
"""

import json
import pathlib
import shutil
import subprocess
import tempfile

REMOTE_JOB = pathlib.Path(__file__).with_name("remote_job.py")


class ColabUnavailable(RuntimeError):
    """基礎設施層失敗——配不到 GPU、VM 被斷、超過硬超時。

    只有這一類才該觸發 Groq fallback。程式邏輯錯誤（ffmpeg 死、檔案找不到）
    必須直接失敗，否則會被 fallback 掩蓋成「反正 Groq 跑得出來」，
    而 Colab 這條路壞掉了你永遠不會知道。
    """


def _colab(*args, timeout=None):
    # --auth adc 必須顯式指定：CLI 的預設是 oauth2（會開瀏覽器），
    # 在 CI 裡只有 ADC 能無頭運作。
    cmd = ["colab", "--auth", "adc", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def transcribe(source_kind, source_id, access_token, whisper_prompt,
               out_dir, session="psr", hard_timeout_s=3600):
    """在 Colab T4 上轉錄，回傳 (words, meta)。

    VM 只收到唯讀 access token，產物由這裡拉回來，上傳一律在 runner 端做。
    """
    out_dir = pathlib.Path(out_dir)
    if shutil.which("colab") is None:
        raise ColabUnavailable("找不到 colab CLI")

    r = _colab("new", "-s", session, "--gpu", "T4", timeout=600)
    if r.returncode != 0:
        raise ColabUnavailable(f"無法配置 T4：{(r.stderr or r.stdout)[:300]}")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            job = pathlib.Path(tmp) / "job.json"
            job.write_text(json.dumps({
                "source_kind": source_kind,
                "source_id": source_id,
                "access_token": access_token,
                "whisper_prompt": whisper_prompt,
            }), encoding="utf-8")
            up = _colab("upload", "-s", session, str(job), "/content/job.json", timeout=300)
            if up.returncode != 0:
                raise ColabUnavailable(f"上傳工作設定失敗：{up.stderr[:200]}")

            # --timeout 預設只有 30 秒，轉錄一定要顯式加大。
            run = _colab("exec", "-s", session, "--timeout", str(hard_timeout_s),
                         "-f", str(REMOTE_JOB), timeout=hard_timeout_s + 300)
            if "REMOTE_JOB_OK" not in (run.stdout or ""):
                raise ColabUnavailable(f"遠端工作未完成：{(run.stderr or run.stdout)[-400:]}")

            for remote, local in (("/content/words.json", out_dir / "words.json"),
                                  ("/content/meta.json", out_dir / "meta.json")):
                d = _colab("download", "-s", session, remote, str(local), timeout=600)
                if d.returncode != 0:
                    raise ColabUnavailable(f"取回 {remote} 失敗：{d.stderr[:200]}")

        words = json.loads((out_dir / "words.json").read_text(encoding="utf-8"))
        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        return words, meta
    except subprocess.TimeoutExpired as exc:
        raise ColabUnavailable(f"超過硬超時 {hard_timeout_s}s") from exc
    finally:
        _colab("stop", "-s", session, timeout=300)
