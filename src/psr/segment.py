import re
import unicodedata

from psr.models import Word, Cue
from psr.text import display_width

# 兩個東亞寬字元之間的空白。Whisper 的中文 word token 會帶前導空格
# （實測 ' 來'），直接串接會讓字幕出現「導演 來個特寫」這種夾雜空格的結果。
# 中文字幕不用空格分隔，斷句靠標點與換行。但英文術語兩側的空格必須保留
# （「安裝 Python 環境」），所以只能刪除「兩側都是寬字元」的那些空白。
_CJK_SPACE = re.compile(r"(?<=\S)\s+(?=\S)")


def _is_wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def clean_text(text: str) -> str:
    """整理串接 word 後的字幕文字：收斂連續空白、刪除中日韓字元之間的空白、
    去除頭尾空白。"""
    text = _CJK_SPACE.sub(lambda m: " ", text).strip()
    out: list[str] = []
    for i, ch in enumerate(text):
        if ch == " " and 0 < i < len(text) - 1 and _is_wide(text[i - 1]) and _is_wide(text[i + 1]):
            continue
        out.append(ch)
    return "".join(out)


def raw_segment(words: list[Word], max_width: float = 20.0, max_gap: float = 0.6) -> list[Cue]:
    """在沒有潤稿（或潤稿降級）時，用固定規則把 word 直接切成字幕。
    純規則、決定性、不呼叫 LLM：累積寬度會超過 max_width，或跟下一個字
    之間的間隔超過 max_gap 秒，就在此處斷句。"""
    if not words:
        return []

    cues: list[Cue] = []
    current_words: list[Word] = [words[0]]
    current_text = words[0].text

    for word in words[1:]:
        gap = word.start - current_words[-1].end
        candidate_text = current_text + word.text
        candidate_width = display_width(candidate_text)

        if candidate_width > max_width or gap > max_gap:
            cues.append(_flush(cues, current_words, current_text))
            current_words = [word]
            current_text = word.text
        else:
            current_words.append(word)
            current_text = candidate_text

    cues.append(_flush(cues, current_words, current_text))
    return cues


def _flush(cues: list[Cue], words_in_cue: list[Word], text: str) -> Cue:
    return Cue(
        index=len(cues) + 1,
        start=words_in_cue[0].start,
        end=words_in_cue[-1].end,
        text=clean_text(text),
    )
