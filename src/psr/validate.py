from psr.models import Cue
from psr.text import display_width


def validate(cues: list[Cue], audio_duration: float) -> list[str]:
    """驗證字幕清單是否符合設計文件 §8 的所有規則，回傳違規訊息清單
    （空清單代表通過）。"""
    violations: list[str] = []
    violations.extend(_check_text_non_empty(cues))
    violations.extend(_check_intervals_valid(cues))
    violations.extend(_check_monotonic(cues))
    violations.extend(_check_bounds(cues, audio_duration))
    violations.extend(_check_line_width(cues))
    violations.extend(_check_duration(cues))
    violations.extend(_check_reading_speed(cues))
    violations.extend(_check_english_tokens_intact(cues))
    violations.extend(_check_contiguous_indices(cues))
    return violations


def _check_text_non_empty(cues: list[Cue]) -> list[str]:
    """空白字幕會佔著螢幕時間卻什麼都不顯示，而且其他規則全部抓不到它：
    時長合法、不重疊、行寬 0、閱讀速度 0/duration = 0 遠低於上限。
    這是縱深防禦——refine._split_one 已經保證不產生空文字，但那是唯一的
    產生途徑這件事，不該靠讀程式碼去確認。"""
    return [
        f"cue {c.index}: 字幕文字為空（{c.start}–{c.end}）"
        for c in cues
        if not c.text.strip()
    ]


def _check_intervals_valid(cues: list[Cue]) -> list[str]:
    return [
        f"cue {c.index}: start ({c.start}) 必須小於 end ({c.end})"
        for c in cues
        if not (c.start < c.end)
    ]


def _check_monotonic(cues: list[Cue]) -> list[str]:
    violations = []
    for a, b in zip(cues, cues[1:]):
        if not (a.end <= b.start):
            violations.append(
                f"cue {a.index} 的 end ({a.end}) 晚於 cue {b.index} 的 start ({b.start})"
            )
    return violations


def _check_bounds(cues: list[Cue], audio_duration: float) -> list[str]:
    violations = []
    if cues and not (cues[0].start >= 0):
        violations.append(f"cue {cues[0].index}: start ({cues[0].start}) 不可小於 0")
    if cues and not (cues[-1].end <= audio_duration):
        violations.append(
            f"cue {cues[-1].index}: end ({cues[-1].end}) 超過音訊長度 ({audio_duration})"
        )
    return violations


def _check_line_width(cues: list[Cue], max_width: float = 20.0) -> list[str]:
    violations = []
    for c in cues:
        width = display_width(c.text)
        if width > max_width:
            violations.append(f"cue {c.index}: 行寬 {width} 超過上限 {max_width}")
    return violations


def _check_duration(cues: list[Cue], min_s: float = 0.5, max_s: float = 7.0) -> list[str]:
    violations = []
    for c in cues:
        duration = c.end - c.start
        if not (min_s <= duration <= max_s):
            violations.append(
                f"cue {c.index}: 時長 {duration} 秒不在允許範圍 [{min_s}, {max_s}]"
            )
    return violations


def _check_reading_speed(cues: list[Cue], max_speed: float = 9.0) -> list[str]:
    violations = []
    for c in cues:
        duration = c.end - c.start
        if duration <= 0:
            continue
        speed = display_width(c.text) / duration
        if speed > max_speed:
            violations.append(
                f"cue {c.index}: 閱讀速度 {speed:.2f} 全形字/秒 超過上限 {max_speed}"
            )
    return violations


def _check_english_tokens_intact(cues: list[Cue]) -> list[str]:
    """檢查英文 token（連續英文字母數字）沒有被斷行硬生生切一半：
    如果一行的結尾是英文字母/數字，而下一行的開頭也是英文字母/數字，
    代表同一個英文單字被拆到兩行去了。"""
    violations = []
    for a, b in zip(cues, cues[1:]):
        if (
            a.text and b.text
            and a.text[-1].isascii() and a.text[-1].isalnum()
            and b.text[0].isascii() and b.text[0].isalnum()
        ):
            violations.append(
                f"cue {a.index} 與 cue {b.index}: 英文 token 疑似被斷行切開"
                f"（'...{a.text[-4:]}' | '{b.text[:4]}...'）"
            )
    return violations


def _check_contiguous_indices(cues: list[Cue]) -> list[str]:
    violations = []
    for expected, c in enumerate(cues, start=1):
        if c.index != expected:
            violations.append(f"cue 序號應為 {expected}，實際為 {c.index}")
    return violations
