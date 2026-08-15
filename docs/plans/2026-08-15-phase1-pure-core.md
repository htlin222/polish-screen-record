# Phase 1：純函式核心 實作計畫

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 實作 SRT 渲染/解析、文字正規化、對齊演算法與驗證器——全部為純函式，零網路、零憑證，並以 golden / property-based / metamorphic / 對抗性測試完整覆蓋。

**Architecture:** 對齊演算法把 LLM 潤稿後的文字貼回 ASR 的 word 時間軸：兩側各壓成字元流並保留「字元位置 → 來源」反查表，用 `difflib` 在正規化後的文字上找出共同區塊，再把潤稿行的斷點吸附回原始 word 邊界換算成時間。LLM 從不輸出時間碼，時間永遠只從 word 的 `start`/`end` 推導。所有函式（`align.py`、`validate.py`、`srt.py`、`text.py`、`segment.py`、`refine.py`）皆為純函式：輸入資料結構、輸出資料結構，不碰網路、不碰檔案系統，因此可以完全離線、確定性地測試。

**Tech Stack:** Python 3.11, uv, pytest, hypothesis, zhconv

---

## 背景說明（給不熟悉本專案的實作者）

- **SRT** 是最常見的字幕檔格式：一連串「序號 / 時間區間 / 文字」區塊，用空行分隔。
- **ASR**（Automatic Speech Recognition，自動語音辨識，這裡指 Whisper）輸出 **word-level timestamps**：每個詞都有自己的絕對開始/結束時間（單位：秒）。
- **潤稿（polish）** 是把 ASR 的逐字稿丟給 LLM 修飾成通順的字幕文字（修正錯字、加標點、重新斷行）。LLM 只看得到文字，看不到任何時間碼——這是設計上刻意的限制，理由見下方「對齊演算法」段落。
- 本 Phase 要解決的核心問題是：**LLM 潤稿後的文字，要怎麼準確地貼回原始的時間軸？** 答案是字串比對（`difflib`）：把「原始逐字稿」和「潤稿後文字」都正規化成方便比對的形式，找出兩者的共同片段，再把潤稿的斷行點對應回原始文字的位置，最後查表換算成時間。

本計畫共 15 個任務，每個任務都是嚴格的 TDD 循環（紅 → 綠 → commit），步驟顆粒度控制在 2–5 分鐘可完成的大小。所有指令、程式碼皆已在本機驗證可執行（`uv run pytest` 72 個測試全數通過），可以直接照抄。

---

## Task 1: 專案骨架 + 資料模型

**Files:**
- Create: `pyproject.toml`
- Create: `src/psr/__init__.py`
- Create: `src/psr/models.py`
- Create: `tests/__init__.py`
- Test: `tests/test_models.py`

### Step 1: 寫失敗的測試

先把專案骨架（`pyproject.toml`、空的 `__init__.py`）和測試檔一起建立起來——沒有骨架，連「import 失敗」這個失敗都跑不出來。

建立 `pyproject.toml`：

```toml
[project]
name = "psr"
version = "0.1.0"
description = "polish-screen-record: pure-function core for SRT rendering, alignment, and validation"
requires-python = ">=3.11"
dependencies = [
    "zhconv>=1.4.3",
]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "hypothesis>=6.100.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/psr"]
```

建立空檔案 `src/psr/__init__.py`（內容留空）與 `tests/__init__.py`（內容留空）。

建立 `tests/test_models.py`：

```python
import pytest
from dataclasses import FrozenInstanceError

from psr.models import Word, Cue


def test_word_construction():
    w = Word(text="你好", start=0.0, end=0.5)
    assert w.text == "你好"
    assert w.start == 0.0
    assert w.end == 0.5


def test_word_is_frozen():
    w = Word(text="你好", start=0.0, end=0.5)
    with pytest.raises(FrozenInstanceError):
        w.text = "再見"


def test_cue_construction():
    c = Cue(index=1, start=0.0, end=1.5, text="你好世界")
    assert c.index == 1
    assert c.text == "你好世界"


def test_cue_is_frozen():
    c = Cue(index=1, start=0.0, end=1.5, text="你好世界")
    with pytest.raises(FrozenInstanceError):
        c.index = 2
```

### Step 2: 執行測試確認失敗

```bash
uv sync
uv run pytest tests/test_models.py -v
```

預期失敗（`psr.models` 還不存在）：

```
ERROR collecting tests/test_models.py
ImportError while importing test module '.../tests/test_models.py'.
tests/test_models.py:4: in <module>
    from psr.models import Word, Cue
E   ModuleNotFoundError: No module named 'psr.models'
```

### Step 3: 寫最小實作

建立 `src/psr/models.py`：

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Word:
    """ASR 輸出的單一詞，帶絕對時間（秒）。"""
    text: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class Cue:
    """一條字幕。index 從 1 起算。"""
    index: int
    start: float
    end: float
    text: str
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_models.py -v
```

預期：

```
tests/test_models.py::test_word_construction PASSED
tests/test_models.py::test_word_is_frozen PASSED
tests/test_models.py::test_cue_construction PASSED
tests/test_models.py::test_cue_is_frozen PASSED

============================== 4 passed ==============================
```

### Step 5: commit

```bash
git add pyproject.toml src/psr/__init__.py src/psr/models.py tests/__init__.py tests/test_models.py
git commit -m "feat(models): add Word and Cue frozen dataclasses"
```

---

## Task 2: SRT 時間碼格式化

**Files:**
- Create: `src/psr/srt.py`
- Test: `tests/test_srt.py`

### Step 1: 寫失敗的測試

建立 `tests/test_srt.py`：

```python
import pytest

from psr.srt import format_timestamp


def test_format_timestamp_zero():
    assert format_timestamp(0.0) == "00:00:00,000"


def test_format_timestamp_with_hours_minutes_seconds():
    assert format_timestamp(3661.5) == "01:01:01,500"


def test_format_timestamp_millisecond_rounding():
    # 1.0005 秒在 IEEE 754 double 中實際儲存為略小於 1.0005 的值，
    # round(seconds * 1000) 對剛好落在 .5 的浮點數採「banker's rounding」
    # （四捨五入到最近的偶數），1000 是偶數，所以捨去而非進位。
    # 這不是 bug，是刻意選擇 round() 而非手動 +0.5 取整的結果——
    # 手動 +0.5 在浮點數上反而更容易因為誤差被放大而不穩定，
    # round() 對整數毫秒運算則是穩定、可重現的。
    assert format_timestamp(1.0005) == "00:00:01,000"


def test_format_timestamp_negative_raises():
    with pytest.raises(ValueError):
        format_timestamp(-1.0)
```

### Step 2: 執行測試確認失敗

```bash
uv run pytest tests/test_srt.py -v
```

預期失敗（`psr.srt` 還不存在）：

```
E   ModuleNotFoundError: No module named 'psr.srt'
```

### Step 3: 寫最小實作

建立 `src/psr/srt.py`：

```python
def format_timestamp(seconds: float) -> str:
    """把秒數轉成 SRT 時間碼格式 HH:MM:SS,mmm。"""
    if seconds < 0:
        raise ValueError(f"seconds must be non-negative, got {seconds}")
    total_ms = round(seconds * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, ms = divmod(remainder_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_srt.py -v
```

預期：`4 passed`

### Step 5: commit

```bash
git add src/psr/srt.py tests/test_srt.py
git commit -m "feat(srt): add format_timestamp for SRT timecodes"
```

---

## Task 3: SRT 渲染

**Files:**
- Modify: `src/psr/srt.py`
- Modify: `tests/test_srt.py`

### Step 1: 寫失敗的測試

在 `tests/test_srt.py` 加入：

```python
from psr.models import Cue
from psr.srt import render


def test_render_two_cues_exact_string():
    cue1 = Cue(index=1, start=0.0, end=1.5, text="你好")
    cue2 = Cue(index=2, start=1.5, end=3.0, text="世界")
    expected = (
        "1\n00:00:00,000 --> 00:00:01,500\n你好\n"
        "\n"
        "2\n00:00:01,500 --> 00:00:03,000\n世界\n"
    )
    assert render([cue1, cue2]) == expected


def test_render_empty_list():
    assert render([]) == ""
```

### Step 2: 執行測試確認失敗

```bash
uv run pytest tests/test_srt.py -v
```

預期失敗：

```
E   ImportError: cannot import name 'render' from 'psr.srt'
```

### Step 3: 寫最小實作

在 `src/psr/srt.py` 加入（`format_timestamp` 保留不動）：

```python
from psr.models import Cue


def render(cues: list[Cue]) -> str:
    """把 Cue 清單渲染成 SRT 檔案內容。每個區塊之間用一個空行分隔，
    檔案結尾恰好一個換行符（沒有多餘的結尾空白行）。"""
    if not cues:
        return ""
    blocks = [
        f"{cue.index}\n{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}\n{cue.text}"
        for cue in cues
    ]
    return "\n\n".join(blocks) + "\n"
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_srt.py -v
```

預期：`6 passed`

### Step 5: commit

```bash
git add src/psr/srt.py tests/test_srt.py
git commit -m "feat(srt): add render() to produce SRT text from cues"
```

---

## Task 4: SRT 解析 + round-trip property

**Files:**
- Modify: `src/psr/srt.py`
- Modify: `tests/test_srt.py`
- Create: `tests/test_srt_properties.py`

### Step 1: 寫失敗的測試

在 `tests/test_srt.py` 加入：

```python
from psr.srt import parse


def test_parse_two_cues():
    text = (
        "1\n00:00:00,000 --> 00:00:01,500\n你好\n"
        "\n"
        "2\n00:00:01,500 --> 00:00:03,000\n世界\n"
    )
    cues = parse(text)
    assert cues == [
        Cue(index=1, start=0.0, end=1.5, text="你好"),
        Cue(index=2, start=1.5, end=3.0, text="世界"),
    ]
```

建立 `tests/test_srt_properties.py`。這是本任務的重點：`parse(render(cues)) == cues` 這個 round-trip 性質，是之後所有 golden fixture（Task 15）能被信任的基礎——如果渲染和解析互相不是對方的逆運算，golden fixture 比對的就不是「同一份資料的兩種表示法」，而是兩個各自可能有 bug 的獨立實作，測試會失去意義。

```python
from hypothesis import given, settings, strategies as st

from psr.models import Cue
from psr.srt import parse, render


@st.composite
def cue_lists(draw):
    """產生毫秒精度的合法 Cue 清單：時間單調遞增、不重疊、文字不含換行。

    刻意用「整數毫秒 / 1000」建構秒數，而不是直接產生任意 float——
    這樣 format_timestamp 內部的 round(seconds * 1000) 才能精確復原成同一個
    整數毫秒，round-trip 才有機會做到位元級相等，而不是「差不多相等」。
    """
    n = draw(st.integers(min_value=1, max_value=5))
    cues = []
    prev_end_ms = 0
    for i in range(n):
        start_ms = prev_end_ms + draw(st.integers(min_value=0, max_value=5000))
        duration_ms = draw(st.integers(min_value=100, max_value=7000))
        end_ms = start_ms + duration_ms
        text = draw(
            st.text(
                alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
                min_size=1,
                max_size=20,
            ).filter(lambda s: "\n" not in s and s.strip() != "")
        )
        cues.append(Cue(index=i + 1, start=start_ms / 1000, end=end_ms / 1000, text=text))
        prev_end_ms = end_ms
    return cues


@given(cue_lists())
@settings(max_examples=200)
def test_parse_render_round_trip(cues):
    assert parse(render(cues)) == cues
```

### Step 2: 執行測試確認失敗

```bash
uv run pytest tests/test_srt.py tests/test_srt_properties.py -v
```

預期失敗：

```
E   ImportError: cannot import name 'parse' from 'psr.srt'
```

### Step 3: 寫最小實作

在 `src/psr/srt.py` 加入：

```python
def _parse_timestamp(ts: str) -> float:
    """把 "HH:MM:SS,mmm" 轉回秒數。先算出總毫秒數（整數運算），
    最後只除一次 1000——如果分開算 h*3600 + m*60 + s + ms/1000，
    浮點加法的結合順序不同會產生極小的誤差（例如 2.369 vs
    2.3689999999999998），足以讓 round-trip 測試在位元級比對時失敗。
    這跟 format_timestamp 用整數毫秒運算是同一個原則的兩面。
    """
    hms, _, ms = ts.partition(",")
    h, m, s = hms.split(":")
    total_ms = int(h) * 3_600_000 + int(m) * 60_000 + int(s) * 1000 + int(ms)
    return total_ms / 1000


def parse(text: str) -> list[Cue]:
    """把 SRT 檔案內容解析回 Cue 清單，是 render() 的逆運算。"""
    blocks = text.strip("\n").split("\n\n")
    cues = []
    for block in blocks:
        if not block.strip():
            continue
        lines = block.split("\n")
        index = int(lines[0].strip())
        start_str, _, end_str = lines[1].partition(" --> ")
        start = _parse_timestamp(start_str.strip())
        end = _parse_timestamp(end_str.strip())
        cue_text = "\n".join(lines[2:])
        cues.append(Cue(index=index, start=start, end=end, text=cue_text))
    return cues
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_srt.py tests/test_srt_properties.py -v
```

預期：`test_srt.py` 7 passed，`test_srt_properties.py` 1 passed（內部跑滿 200 個 hypothesis 案例）。

### Step 5: commit

```bash
git add src/psr/srt.py tests/test_srt.py tests/test_srt_properties.py
git commit -m "feat(srt): add parse() with round-trip property test"
```

---

## Task 5: 正規化與索引映射（最關鍵的基礎設施）

**Files:**
- Create: `src/psr/text.py`
- Create: `tests/test_text.py`

### Step 1: 寫失敗的測試

建立 `tests/test_text.py`：

```python
from hypothesis import given, settings, strategies as st

from psr.text import normalize


def test_normalize_fullwidth_digits():
    normalized, orig_index = normalize("１２３")
    assert normalized == "123"
    assert orig_index == [0, 1, 2]


def test_normalize_traditional_simplified_fold_to_same_string():
    # 資料（繁體）與 资料（簡體）是同一個詞的繁簡字形差異，
    # 正規化後應該疊成同一個字串，這樣潤稿把繁簡混用也不會被誤判成內容不同。
    assert normalize("資料")[0] == normalize("资料")[0] == "资料"


def test_normalize_strips_punctuation():
    normalized, orig_index = normalize("你好，世界！")
    assert normalized == "你好世界"


def test_normalize_casefolds_latin():
    assert normalize("Python")[0] == normalize("python")[0] == "python"


@given(st.text(min_size=0, max_size=50))
@settings(max_examples=300)
def test_normalize_index_map_is_valid(s):
    normalized, orig_index = normalize(s)
    assert len(normalized) == len(orig_index)
    for idx in orig_index:
        assert 0 <= idx < len(s)
    for i in range(len(orig_index) - 1):
        assert orig_index[i] <= orig_index[i + 1]
```

### Step 2: 執行測試確認失敗

```bash
uv run pytest tests/test_text.py -v
```

預期失敗：

```
E   ModuleNotFoundError: No module named 'psr.text'
```

### Step 3: 寫最小實作

建立 `src/psr/text.py`：

```python
import unicodedata

from zhconv import convert


def normalize(s: str) -> tuple[str, list[int]]:
    """正規化字串供比對用，回傳 (正規化後字串, 索引映射)。

    orig_index[i] 是正規化後字串第 i 個字元對應回原始字串 s 的字元索引。

    逐「來源字元」處理，而不是對整個字串一次做正規化，理由在下面每一步都要說明：
    unicodedata.normalize("NFKC", ...) 這類正規化可能把一個字元展開成多個
    字元（例如全形數字、部分相容字元）。如果對整個字串一口氣做 NFKC，
    展開後的字元數就不再跟原始字元數一一對應，索引映射會在這一步就悄悄壞掉，
    之後所有以這張表為基礎的比對——包括 align.py 的斷點映射——全部都是錯的，
    而且不會報錯，只會給出看起來合理但其實對不上時間軸的結果。
    """
    normalized_chars: list[str] = []
    orig_index: list[int] = []

    for i, ch in enumerate(s):
        # 1. NFKC：全形轉半形、相容字元展開。單一字元可能展開成多個。
        nfkc = unicodedata.normalize("NFKC", ch)
        for nfkc_ch in nfkc:
            # 2. 繁簡統一（僅供比對用，不影響最終顯示文字，因為我們只回傳
            #    normalized_chars，原始文字仍保留在 Cue.text 裡）。
            folded = convert(nfkc_ch, "zh-cn")
            for folded_ch in folded:
                # 3. 拉丁字母 casefold（比 lower() 更嚴格的大小寫無關比較）
                cf = folded_ch.casefold()
                for cf_ch in cf:
                    # 4. 丟棄標點（Unicode 類別開頭 P）、分隔符（開頭 Z）與空白
                    category = unicodedata.category(cf_ch)
                    if category.startswith("P") or category.startswith("Z") or cf_ch.isspace():
                        continue
                    normalized_chars.append(cf_ch)
                    orig_index.append(i)

    return "".join(normalized_chars), orig_index
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_text.py -v
```

預期：`5 passed`（含 300 個 hypothesis 案例的 property test）。

### Step 5: commit

```bash
git add src/psr/text.py tests/test_text.py
git commit -m "feat(text): add normalize() with per-character index mapping"
```

---

## Task 6: 顯示寬度

**Files:**
- Modify: `src/psr/text.py`
- Modify: `tests/test_text.py`

### Step 1: 寫失敗的測試

在 `tests/test_text.py` 加入：

```python
from psr.text import display_width


def test_display_width_pure_chinese():
    assert display_width("你好嗎最近過得如何呀") == 10.0


def test_display_width_pure_latin():
    assert display_width("Python") == 3.0


def test_display_width_mixed():
    assert display_width("Python你好") == 5.0
```

### Step 2: 執行測試確認失敗

```bash
uv run pytest tests/test_text.py -v
```

預期失敗：

```
E   ImportError: cannot import name 'display_width' from 'psr.text'
```

### Step 3: 寫最小實作

在 `src/psr/text.py` 加入：

```python
def display_width(s: str) -> float:
    """計算字串在字幕排版中的顯示寬度。螢幕錄製字幕規定單行 <=20 全形字寬。

    unicodedata.east_asian_width(ch) 回傳 "W"（Wide，如中文）或 "F"
    （Fullwidth，如全形標點）記 1.0；其餘（拉丁字母、數字、半形符號）記 0.5，
    這樣「Python」(6 個半形字元) 只佔 3.0 個全形字寬，符合視覺上的實際佔用。
    """
    width = 0.0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            width += 1.0
        else:
            width += 0.5
    return width
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_text.py -v
```

預期：`8 passed`

### Step 5: commit

```bash
git add src/psr/text.py tests/test_text.py
git commit -m "feat(text): add display_width() for CJK-aware line width"
```

---

## Task 7: 字元流建構

**Files:**
- Create: `src/psr/align.py`
- Create: `tests/test_align_streams.py`

### Step 1: 寫失敗的測試

建立 `tests/test_align_streams.py`：

```python
from psr.models import Word
from psr.align import word_stream, line_stream


def test_word_stream_concatenates_and_maps_char_to_word():
    words = [Word(text="AB", start=0.0, end=1.0), Word(text="C", start=1.0, end=1.5)]
    text, char_to_word = word_stream(words)
    assert text == "ABC"
    assert char_to_word == [0, 0, 1]


def test_word_stream_empty():
    assert word_stream([]) == ("", [])


def test_line_stream_concatenates_and_tracks_boundaries():
    lines = ["AB", "CDE"]
    text, char_to_line, boundaries = line_stream(lines)
    assert text == "ABCDE"
    assert char_to_line == [0, 0, 1, 1, 1]
    assert boundaries == [0, 2]


def test_line_stream_empty():
    assert line_stream([]) == ("", [], [])
```

### Step 2: 執行測試確認失敗

```bash
uv run pytest tests/test_align_streams.py -v
```

預期失敗：

```
E   ModuleNotFoundError: No module named 'psr.align'
```

### Step 3: 寫最小實作

建立 `src/psr/align.py`：

```python
from psr.models import Word


def word_stream(words: list[Word]) -> tuple[str, list[int]]:
    """把 word 清單串接成一條字元流，並回傳每個字元對應的 word index。
    這是原始側（ASR 逐字稿）的字元流。"""
    text_parts: list[str] = []
    char_to_word: list[int] = []
    for word_idx, word in enumerate(words):
        for ch in word.text:
            text_parts.append(ch)
            char_to_word.append(word_idx)
    return "".join(text_parts), char_to_word


def line_stream(lines: list[str]) -> tuple[str, list[int], list[int]]:
    """把字幕行清單串接成一條字元流。這是潤稿側的字元流。

    回傳 (串接後文字, char_index -> line_index 映射, 每行起始的 char offset 清單)。
    boundaries 的第一個元素永遠是 0（第一行從頭開始）。
    """
    text_parts: list[str] = []
    char_to_line: list[int] = []
    boundaries: list[int] = []
    offset = 0
    for line_idx, line in enumerate(lines):
        boundaries.append(offset)
        for ch in line:
            text_parts.append(ch)
            char_to_line.append(line_idx)
        offset += len(line)
    return "".join(text_parts), char_to_line, boundaries
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_align_streams.py -v
```

預期：`4 passed`

### Step 5: commit

```bash
git add src/psr/align.py tests/test_align_streams.py
git commit -m "feat(align): add word_stream and line_stream character-flow builders"
```

---

## Task 8: 斷點映射（演算法核心）

**Files:**
- Modify: `src/psr/align.py`
- Create: `tests/test_align_boundaries.py`

這是整個對齊演算法最核心、最容易踩雷的一步，三個非協商的硬性要求：

1. **`difflib.SequenceMatcher(None, norm_orig, norm_poly, autojunk=False)`——`autojunk=False` 是強制的，沒有例外。** `SequenceMatcher` 預設的 autojunk 啟發式會把「長度 >=200 的序列中出現次數超過 1%」的元素當成雜訊丟掉。中文逐字稿裡「的」「是」「我」「這」這類高頻字幾乎必中這個門檻，一旦被當雜訊丟掉，`SequenceMatcher` 找到的 `equal` 區塊會**靜默地**變少變爛——不會拋例外、不會有警告，只會給出一份看起來正常、實際上完全對不上時間軸的字幕。
2. 每個潤稿側的斷點位置 `b`：落在某個 `equal` 區塊內（`j1 <= b < j2`）→ 精確線性映射 `i1 + (b - j1)`；沒有落在任何 `equal` 區塊內 → 吸附到最近的 `equal` 區塊邊界。
3. **吸附平手時固定取「前者」（poly 座標較小、較早出現的那個邊界）**——這是一個用整數距離比較實作的決定性 tie-break，不是浮點數比較，也不是依賴 dict 或 set 的隱含順序。

### Step 1: 寫失敗的測試

建立 `tests/test_align_boundaries.py`：

```python
from psr.align import map_boundaries, has_anchor


def test_map_boundaries_identity():
    assert map_boundaries("abcdef", "abcdef", [0, 3, 6]) == [0, 3, 6]


def test_map_boundaries_snaps_across_inserted_text():
    # poly 在 orig 的 "abc" 之後插入了 "XXX"，boundary 落在插入區塊內時
    # 一律吸附到最近的 equal 邊界。
    orig = "abcdef"
    poly = "abcXXXdef"
    assert map_boundaries(orig, poly, [4]) == [3]


def test_map_boundaries_across_deleted_text():
    orig = "abcZZZdef"
    poly = "abcdef"
    assert map_boundaries(orig, poly, [3]) == [6]


def test_map_boundaries_tie_break_takes_preceding_edge():
    # orig="abcXYdef", poly="abcPQdef"：XY 被換成 PQ（同長度 replace）。
    # poly 上 b=4（P 和 Q 之間）與左邊 equal 區塊尾端（j=3）、右邊 equal 區塊
    # 開頭（j=5）等距，平手時固定取「前者」——回傳 i=3，不是 i=5。
    orig = "abcXYdef"
    poly = "abcPQdef"
    assert map_boundaries(orig, poly, [4]) == [3]


def test_map_boundaries_completely_unrelated_strings_are_all_none():
    assert map_boundaries("abc", "xyz", [0, 1, 2, 3]) == [None, None, None, None]


def test_has_anchor_overlap_exactly_min_len_is_true():
    opcodes = [("equal", 0, 4, 0, 4)]
    assert has_anchor(opcodes, 0, 4, min_len=4) is True


def test_has_anchor_overlap_one_below_min_len_is_false():
    opcodes = [("equal", 0, 3, 0, 3)]
    assert has_anchor(opcodes, 0, 3, min_len=4) is False
```

### Step 2: 執行測試確認失敗

```bash
uv run pytest tests/test_align_boundaries.py -v
```

預期失敗：

```
E   ImportError: cannot import name 'map_boundaries' from 'psr.align'
```

### Step 3: 寫最小實作

在 `src/psr/align.py` 加入：

```python
import difflib


def map_boundaries(norm_orig: str, norm_poly: str, boundaries: list[int]) -> list[int | None]:
    """把潤稿正規化字串上的斷點位置，映射回原始正規化字串上的位置。

    autojunk=False 是強制的：預設的 autojunk 啟發式會把「長度 >=200 的序列中
    出現超過 1% 的元素」當雜訊丟掉。中文的「的」「是」「我」「這」這類高頻字
    在長逐字稿裡幾乎必中，一旦被當雜訊丟掉，equal 區塊會靜默地變少變爛——
    不會拋例外，只會給出錯誤的時間軸。
    """
    matcher = difflib.SequenceMatcher(None, norm_orig, norm_poly, autojunk=False)
    opcodes = matcher.get_opcodes()
    return [_map_one_boundary(opcodes, b) for b in boundaries]


def _map_one_boundary(opcodes, b: int) -> int | None:
    equal_blocks = [
        (i1, i2, j1, j2) for tag, i1, i2, j1, j2 in opcodes if tag == "equal" and j1 < j2
    ]

    # 精確落在某個 equal 區塊內：線性映射
    for i1, i2, j1, j2 in equal_blocks:
        if j1 <= b < j2:
            return i1 + (b - j1)

    if not equal_blocks:
        return None

    # 吸附到最近的 equal 區塊邊界。用整數距離比較，平手時取 edge_j 較小
    # （較早出現）的那個候選——這是決定性 tie-break，不依賴浮點數或字典順序。
    best_edge_i: int | None = None
    best_edge_j: int | None = None
    best_dist: int | None = None
    for i1, i2, j1, j2 in equal_blocks:
        for edge_j, edge_i in ((j1, i1), (j2, i2)):
            dist = abs(edge_j - b)
            if (
                best_dist is None
                or dist < best_dist
                or (dist == best_dist and edge_j < best_edge_j)
            ):
                best_dist = dist
                best_edge_j = edge_j
                best_edge_i = edge_i
    return best_edge_i


def has_anchor(opcodes, orig_lo: int, orig_hi: int, min_len: int = 4) -> bool:
    """檢查 [orig_lo, orig_hi) 這段原始字元區間內，是否至少有一個長度 >= min_len
    的 equal 區塊與它重疊。這是防止「斷點映射得到值」但「這段內容其實已經
    面目全非」的防線——map_boundaries 只保證吸附得到一個位置，不保證那個
    位置附近的內容真的還能在原文裡找到對應。"""
    for tag, i1, i2, j1, j2 in opcodes:
        if tag != "equal":
            continue
        overlap_lo = max(i1, orig_lo)
        overlap_hi = min(i2, orig_hi)
        if overlap_hi - overlap_lo >= min_len:
            return True
    return False
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_align_boundaries.py -v
```

預期：`7 passed`

### Step 5: commit

```bash
git add src/psr/align.py tests/test_align_boundaries.py
git commit -m "feat(align): add map_boundaries() with autojunk=False and deterministic tie-break"
```

---

## Task 9: 錨點品質檢查

`has_anchor` 已經在 Task 8 跟 `map_boundaries` 一起實作了（兩者共用同一份 opcodes，放在同一個檔案裡更自然）。這個任務把它的測試獨立列出來，是因為它在設計文件裡是獨立的一道防線，值得有自己明確的驗收標準——這裡不重複實作，只補齊 Task 8 尚未涵蓋的邊界案例（多個 equal 區塊、區間完全不重疊）。

**Files:**
- Modify: `tests/test_align_boundaries.py`

### Step 1: 寫失敗的測試

在 `tests/test_align_boundaries.py` 加入：

```python
def test_has_anchor_picks_best_among_multiple_equal_blocks():
    # 第一個 equal 區塊太短（長度 2），第二個夠長（長度 5），只要有一個
    # 符合門檻就算數。
    opcodes = [
        ("equal", 0, 2, 0, 2),
        ("replace", 2, 3, 2, 3),
        ("equal", 3, 8, 3, 8),
    ]
    assert has_anchor(opcodes, 0, 8, min_len=4) is True


def test_has_anchor_no_overlap_with_query_range_is_false():
    # equal 區塊存在，但完全落在查詢範圍之外
    opcodes = [("equal", 0, 10, 0, 10)]
    assert has_anchor(opcodes, 20, 30, min_len=4) is False
```

### Step 2: 執行測試確認失敗

由於 `has_anchor` 在 Task 8 已存在，這兩個新測試案例應該直接通過（`has_anchor` 的邏輯本來就該處理這些情況）。先確認：如果失敗，代表 Task 8 的實作有誤，需要回頭修正 `has_anchor`，而不是新增程式碼。

```bash
uv run pytest tests/test_align_boundaries.py -v
```

若這一步意外失敗，先不要往下走：回到 Task 8 的 `has_anchor` 實作檢查邏輯，修正後再回來繼續。

### Step 3: 寫最小實作

（無需新增實作——`has_anchor` 的邏輯已經是通用的，天然涵蓋多區塊與零重疊的情況。若上一步測試通過，跳過本步驟。）

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_align_boundaries.py -v
```

預期：`9 passed`

### Step 5: commit

```bash
git add tests/test_align_boundaries.py
git commit -m "test(align): add multi-block and no-overlap cases for has_anchor"
```

---

## Task 10: align() 整合

**Files:**
- Modify: `src/psr/align.py`
- Create: `tests/test_align.py`

這一步把 Task 5（`normalize`）、Task 7（`word_stream`/`line_stream`）、Task 8-9（`map_boundaries`/`has_anchor`）串起來，是整個對齊演算法的入口函式。**任一行找不到足夠的錨點，整個窗口就降級為 `None`**（設計文件 §7）——不是只把那一行標記失敗，而是連同同一個窗口內其他本來對得上的行也一起放棄。原因：只降級單行會在前後製造時間軸縫隙，需要額外的縫合邏輯，而縫合邏輯本身就是新的 bug 來源。保守降級讓失敗清楚可見（某段字幕突然變成 raw 斷句就是訊號），不會製造難以察覺的微妙錯位。

### Step 1: 寫失敗的測試

建立 `tests/test_align.py`：

```python
from psr.models import Word, Cue
from psr.align import align


def _tutorial_words():
    return [
        Word("我", 0.0, 0.2), Word("們", 0.2, 0.4), Word("先", 0.4, 0.6),
        Word("來", 0.6, 0.8), Word("安", 0.8, 1.0), Word("裝", 1.0, 1.2),
        Word("Python", 1.2, 1.8),
    ]


def test_align_identity_polish():
    words = _tutorial_words()
    lines = ["我們先來安裝Python"]
    result = align(words, lines)
    assert result == [Cue(index=1, start=0.0, end=1.8, text="我們先來安裝Python")]


def test_align_with_correction_still_maps_full_span():
    # ASR 把「安」聽成同音字「後」，潤稿修正回「安」。修正是行內部的單字替換，
    # 不影響行首/行尾這兩個邊界點的映射，所以整行時間應該和沒有修正時一樣。
    words = [
        Word("我", 0.0, 0.2), Word("們", 0.2, 0.4), Word("先", 0.4, 0.6),
        Word("來", 0.6, 0.8), Word("後", 0.8, 1.0), Word("裝", 1.0, 1.2),
        Word("Python", 1.2, 1.8),
    ]
    lines = ["我們先來安裝Python"]
    result = align(words, lines)
    assert result == [Cue(index=1, start=0.0, end=1.8, text="我們先來安裝Python")]


def test_align_unanchored_line_degrades_to_none():
    words = _tutorial_words()
    lines = ["今天天氣真好嗎"]  # 與原文完全無關，找不到任何長度 >=4 的 equal 區塊
    assert align(words, lines) is None


def test_align_empty_words_returns_none():
    assert align([], ["某些文字"]) is None


def test_align_empty_lines_returns_none():
    assert align(_tutorial_words(), []) is None
```

### Step 2: 執行測試確認失敗

```bash
uv run pytest tests/test_align.py -v
```

預期失敗：

```
E   ImportError: cannot import name 'align' from 'psr.align'
```

### Step 3: 寫最小實作

在 `src/psr/align.py` 加入（記得在檔案頂端加上 `import bisect` 與 `from psr.models import Word, Cue`、`from psr.text import normalize`）：

```python
import bisect

from psr.models import Word, Cue
from psr.text import normalize


def align(words: list[Word], lines: list[str]) -> list[Cue] | None:
    """把 LLM 潤稿後的字幕行貼回 ASR 的 word 時間軸。

    LLM 潤稿時完全看不到任何時間碼（設計文件 §6），時間軸永遠只從
    words 的 start/end 推導，杜絕潤稿把時間戳一起「潤」壞的可能。

    任一行找不到足夠錨點時，整個窗口降級為 None（呼叫端應改用
    segment.raw_segment）——只降級單行會在前後製造時間軸縫隙，
    縫合邏輯本身就是新的 bug 來源，所以採取「一行壞、全窗降級」的保守策略。
    """
    if not words or not lines:
        return None

    orig_text, char_to_word = word_stream(words)
    poly_text, char_to_line, boundaries = line_stream(lines)

    norm_orig, orig_norm_map = normalize(orig_text)
    norm_poly, poly_norm_map = normalize(poly_text)

    # 把「poly 原始字元流上的行起點」換算成「poly 正規化字元流上的位置」。
    # poly_norm_map 是 normalized_pos -> raw_pos（非遞減），bisect_left 找到
    # 第一個 raw_pos >= 目標值的 normalized 位置——也就是「原始位置在正規化
    # 後最靠前但不早於它」的落點，剛好處理掉邊界字元被正規化丟棄的情況。
    boundaries_with_end = boundaries + [len(poly_text)]
    norm_boundaries = [
        bisect.bisect_left(poly_norm_map, raw_b) for raw_b in boundaries_with_end
    ]

    matcher = difflib.SequenceMatcher(None, norm_orig, norm_poly, autojunk=False)
    opcodes = matcher.get_opcodes()
    mapped = map_boundaries(norm_orig, norm_poly, norm_boundaries)

    cues: list[Cue] = []
    for line_idx, line in enumerate(lines):
        lo = mapped[line_idx]
        hi = mapped[line_idx + 1]
        if lo is None or hi is None or lo >= hi:
            return None
        if not has_anchor(opcodes, lo, hi):
            return None

        orig_char_lo = orig_norm_map[lo]
        orig_char_hi = orig_norm_map[hi - 1]
        word_lo = char_to_word[orig_char_lo]
        word_hi = char_to_word[orig_char_hi]

        cues.append(Cue(
            index=line_idx + 1,
            start=words[word_lo].start,
            end=words[word_hi].end,
            text=line,
        ))

    return cues
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_align.py -v
```

預期：`5 passed`

再跑一次整個 `align` 模組的所有測試，確保沒有破壞前面幾個任務：

```bash
uv run pytest tests/test_align_streams.py tests/test_align_boundaries.py tests/test_align.py -v
```

預期：`18 passed`

### Step 5: commit

```bash
git add src/psr/align.py tests/test_align.py
git commit -m "feat(align): add align() to map polished lines back to word timestamps"
```

---

## Task 11: raw 斷句降級

**Files:**
- Create: `src/psr/segment.py`
- Create: `tests/test_segment.py`

`align()` 降級成 `None`，或整個 polish 階段失敗時，需要一個完全不靠 LLM、純規則、決定性的斷句方式當保底——這就是 `raw_segment`。它直接用 word 本身的寬度與間隔切字幕，不重寫任何文字。

### Step 1: 寫失敗的測試

建立 `tests/test_segment.py`：

```python
from psr.models import Word
from psr.segment import raw_segment


def test_raw_segment_single_cue_when_within_limits():
    words = [Word("你", 0.0, 0.2), Word("好", 0.2, 0.4), Word("嗎", 0.4, 0.6)]
    cues = raw_segment(words, max_width=20.0, max_gap=0.6)
    assert len(cues) == 1
    assert cues[0].text == "你好嗎"
    assert cues[0].start == 0.0
    assert cues[0].end == 0.6


def test_raw_segment_splits_on_width_overflow():
    words = [Word("你", 0.0, 0.2), Word("好", 0.2, 0.4), Word("嗎", 0.4, 0.6)]
    cues = raw_segment(words, max_width=1.5, max_gap=0.6)
    assert [c.text for c in cues] == ["你", "好", "嗎"]
    assert [c.index for c in cues] == [1, 2, 3]


def test_raw_segment_splits_on_gap_overflow():
    words = [Word("你", 0.0, 0.2), Word("好", 1.0, 1.2)]  # gap = 0.8s > max_gap
    cues = raw_segment(words, max_width=20.0, max_gap=0.6)
    assert len(cues) == 2
    assert cues[0].text == "你"
    assert cues[1].text == "好"


def test_raw_segment_empty_words():
    assert raw_segment([]) == []
```

### Step 2: 執行測試確認失敗

```bash
uv run pytest tests/test_segment.py -v
```

預期失敗：

```
E   ModuleNotFoundError: No module named 'psr.segment'
```

### Step 3: 寫最小實作

建立 `src/psr/segment.py`：

```python
from psr.models import Word, Cue
from psr.text import display_width


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
        text=text,
    )
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_segment.py -v
```

預期：`4 passed`

### Step 5: commit

```bash
git add src/psr/segment.py tests/test_segment.py
git commit -m "feat(segment): add raw_segment() deterministic fallback segmentation"
```

---

## Task 12: 時長與行寬修正

**Files:**
- Create: `src/psr/refine.py`
- Create: `tests/test_refine.py`

不管字幕是從 `align()` 還是 `raw_segment()` 來的，都可能出現時長不合法的 cue（太長或太短）。`enforce_duration` 負責把它們修到合法範圍內，而且**絕不製造重疊**。

> **已知限制（明確記錄，不是缺陷）：** 太長的 cue 被切開時，文字是依照「切點前累積了幾個 word 的字元數」按比例切開 `cue.text`，這個假設在 `cue.text` 是底層 words 文字的直接串接時（例如 `raw_segment` 的輸出，或潤稿沒有增刪字數時）是精確的。如果 `cue.text` 是經過大幅改寫的潤稿文字，字元數與底層 word 不會一一對應，切出來的文字邊界可能不夠精確——但時間軸本身（`start`/`end`）永遠是從實際 word 邊界算出來的，不會因此失準。

### Step 1: 寫失敗的測試

建立 `tests/test_refine.py`：

```python
from psr.models import Word, Cue
from psr.refine import enforce_duration


def test_enforce_duration_splits_at_largest_gap():
    words = [Word("A", 0, 1), Word("B", 1, 2), Word("C", 5, 6), Word("D", 6, 7)]
    cue = Cue(index=1, start=0, end=7, text="ABCD")
    result = enforce_duration([cue], words, min_s=0.5, max_s=5.0)
    assert result == [
        Cue(index=1, start=0, end=2, text="AB"),
        Cue(index=2, start=5, end=7, text="CD"),
    ]


def test_enforce_duration_extension_blocked_by_next_cue():
    words = [Word("A", 0, 0.2), Word("B", 0.3, 1.0)]
    cues = [Cue(index=1, start=0, end=0.2, text="A"), Cue(index=2, start=0.3, end=1.0, text="B")]
    result = enforce_duration(cues, words, min_s=0.5, max_s=7.0)
    # 延長被下一條字幕的 start 卡住，無法真的延到 0.5 秒
    assert result[0].end == 0.3
    assert result[0].end <= result[1].start


def test_enforce_duration_never_creates_overlap():
    words = [Word("A", 0, 0.1), Word("B", 0.15, 0.3), Word("C", 0.35, 0.5)]
    cues = [
        Cue(index=1, start=0, end=0.1, text="A"),
        Cue(index=2, start=0.15, end=0.3, text="B"),
        Cue(index=3, start=0.35, end=0.5, text="C"),
    ]
    result = enforce_duration(cues, words, min_s=0.5, max_s=7.0)
    for a, b in zip(result, result[1:]):
        assert a.end <= b.start
```

### Step 2: 執行測試確認失敗

```bash
uv run pytest tests/test_refine.py -v
```

預期失敗：

```
E   ModuleNotFoundError: No module named 'psr.refine'
```

### Step 3: 寫最小實作

建立 `src/psr/refine.py`：

```python
from psr.models import Word, Cue


def enforce_duration(
    cues: list[Cue],
    words: list[Word],
    min_s: float = 0.5,
    max_s: float = 7.0,
) -> list[Cue]:
    """修正字幕時長：太長的在字間最大間隔處遞迴切開；太短的往後延到
    不會與下一條字幕重疊為止。絕不製造重疊。"""
    split_cues = _split_long_cues(cues, words, max_s)
    return _extend_short_cues(split_cues, min_s)


def _words_in_cue(cue: Cue, words: list[Word]) -> list[Word]:
    return [w for w in words if w.start >= cue.start and w.end <= cue.end]


def _split_long_cues(cues: list[Cue], words: list[Word], max_s: float) -> list[Cue]:
    result: list[Cue] = []
    for cue in cues:
        result.extend(_split_one(cue, words, max_s))
    return _reindex(result)


def _split_one(cue: Cue, words: list[Word], max_s: float) -> list[Cue]:
    duration = cue.end - cue.start
    if duration <= max_s:
        return [cue]

    cue_words = _words_in_cue(cue, words)
    if len(cue_words) < 2:
        # 沒有字間間隔可切，只能保留原樣（不製造無中生有的斷點）
        return [cue]

    # 找字間最大間隔作為切點
    best_gap = -1.0
    split_at = None
    for i in range(len(cue_words) - 1):
        gap = cue_words[i + 1].start - cue_words[i].end
        if gap > best_gap:
            best_gap = gap
            split_at = i

    left_words = cue_words[: split_at + 1]
    right_words = cue_words[split_at + 1 :]
    split_char = sum(len(w.text) for w in left_words)
    left_text = cue.text[:split_char]
    right_text = cue.text[split_char:]

    left = Cue(index=cue.index, start=left_words[0].start, end=left_words[-1].end, text=left_text)
    right = Cue(index=cue.index, start=right_words[0].start, end=right_words[-1].end, text=right_text)

    return _split_one(left, words, max_s) + _split_one(right, words, max_s)


def _extend_short_cues(cues: list[Cue], min_s: float) -> list[Cue]:
    result = list(cues)
    for i, cue in enumerate(result):
        duration = cue.end - cue.start
        if duration >= min_s:
            continue
        if i + 1 < len(result):
            limit = result[i + 1].start
        else:
            limit = cue.start + min_s  # 最後一條沒有下一條可比對，直接延到 min_s
        new_end = min(cue.start + min_s, limit)
        result[i] = Cue(index=cue.index, start=cue.start, end=new_end, text=cue.text)
    return result


def _reindex(cues: list[Cue]) -> list[Cue]:
    return [Cue(index=i + 1, start=c.start, end=c.end, text=c.text) for i, c in enumerate(cues)]
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_refine.py -v
```

預期：`3 passed`

### Step 5: commit

```bash
git add src/psr/refine.py tests/test_refine.py
git commit -m "feat(refine): add enforce_duration() to split/extend cue durations"
```

---

## Task 13: 驗證器

**Files:**
- Create: `src/psr/validate.py`
- Create: `tests/test_validate.py`

設計文件 §8 每一列規則都獨立寫成一個小 predicate 函式，每個都能單獨測試——這樣以後某條規則要調整（例如行寬上限改成 25），不用去猜會不會動到其他規則。

### Step 1: 寫失敗的測試

建立 `tests/test_validate.py`：

```python
from psr.models import Cue
from psr.validate import (
    validate,
    _check_intervals_valid,
    _check_monotonic,
    _check_bounds,
    _check_line_width,
    _check_duration,
    _check_reading_speed,
    _check_english_tokens_intact,
    _check_contiguous_indices,
)


def test_intervals_valid_pass():
    assert _check_intervals_valid([Cue(1, 0.0, 1.0, "A")]) == []


def test_intervals_valid_fail():
    assert _check_intervals_valid([Cue(1, 1.0, 1.0, "A")]) != []


def test_monotonic_pass():
    cues = [Cue(1, 0.0, 1.0, "A"), Cue(2, 1.0, 2.0, "B")]
    assert _check_monotonic(cues) == []


def test_monotonic_fail():
    cues = [Cue(1, 0.0, 1.5, "A"), Cue(2, 1.0, 2.0, "B")]
    assert _check_monotonic(cues) != []


def test_bounds_pass():
    cues = [Cue(1, 0.0, 1.0, "A")]
    assert _check_bounds(cues, audio_duration=10.0) == []


def test_bounds_fail_negative_start():
    cues = [Cue(1, -0.5, 1.0, "A")]
    assert _check_bounds(cues, audio_duration=10.0) != []


def test_bounds_fail_end_exceeds_audio_duration():
    cues = [Cue(1, 0.0, 11.0, "A")]
    assert _check_bounds(cues, audio_duration=10.0) != []


def test_line_width_pass():
    cues = [Cue(1, 0.0, 1.0, "你好")]
    assert _check_line_width(cues) == []


def test_line_width_fail():
    cues = [Cue(1, 0.0, 1.0, "你" * 21)]
    assert _check_line_width(cues) != []


def test_duration_pass():
    cues = [Cue(1, 0.0, 1.0, "A")]
    assert _check_duration(cues) == []


def test_duration_fail_too_short():
    cues = [Cue(1, 0.0, 0.1, "A")]
    assert _check_duration(cues) != []


def test_duration_fail_too_long():
    cues = [Cue(1, 0.0, 8.0, "A")]
    assert _check_duration(cues) != []


def test_reading_speed_pass():
    cues = [Cue(1, 0.0, 2.0, "你好")]  # 2 全形字 / 2 秒 = 1 <= 9
    assert _check_reading_speed(cues) == []


def test_reading_speed_fail():
    cues = [Cue(1, 0.0, 1.0, "你" * 10)]  # 10 全形字 / 1 秒 = 10 > 9
    assert _check_reading_speed(cues) != []


def test_english_tokens_intact_pass():
    cues = [Cue(1, 0.0, 1.0, "你好 Python"), Cue(2, 1.0, 2.0, "很棒")]
    assert _check_english_tokens_intact(cues) == []


def test_english_tokens_intact_fail():
    cues = [Cue(1, 0.0, 1.0, "安裝 Pyth"), Cue(2, 1.0, 2.0, "on 很簡單")]
    assert _check_english_tokens_intact(cues) != []


def test_contiguous_indices_pass():
    cues = [Cue(1, 0.0, 1.0, "A"), Cue(2, 1.0, 2.0, "B")]
    assert _check_contiguous_indices(cues) == []


def test_contiguous_indices_fail():
    cues = [Cue(1, 0.0, 1.0, "A"), Cue(3, 1.0, 2.0, "B")]
    assert _check_contiguous_indices(cues) != []


def test_validate_passing_cues_returns_empty_list():
    cues = [Cue(1, 0.0, 1.0, "你好"), Cue(2, 1.0, 2.0, "世界")]
    assert validate(cues, audio_duration=2.0) == []


def test_validate_collects_multiple_violations():
    cues = [Cue(1, 0.0, 0.1, "你" * 25)]
    violations = validate(cues, audio_duration=10.0)
    assert len(violations) >= 2  # 時長太短 + 行寬超標
```

### Step 2: 執行測試確認失敗

```bash
uv run pytest tests/test_validate.py -v
```

預期失敗：

```
E   ModuleNotFoundError: No module named 'psr.validate'
```

### Step 3: 寫最小實作

建立 `src/psr/validate.py`：

```python
from psr.models import Cue
from psr.text import display_width


def validate(cues: list[Cue], audio_duration: float) -> list[str]:
    """驗證字幕清單是否符合設計文件 §8 的所有規則，回傳違規訊息清單
    （空清單代表通過）。"""
    violations: list[str] = []
    violations.extend(_check_intervals_valid(cues))
    violations.extend(_check_monotonic(cues))
    violations.extend(_check_bounds(cues, audio_duration))
    violations.extend(_check_line_width(cues))
    violations.extend(_check_duration(cues))
    violations.extend(_check_reading_speed(cues))
    violations.extend(_check_english_tokens_intact(cues))
    violations.extend(_check_contiguous_indices(cues))
    return violations


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
```

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_validate.py -v
```

預期：`20 passed`

### Step 5: commit

```bash
git add src/psr/validate.py tests/test_validate.py
git commit -m "feat(validate): add validate() with per-rule predicate functions"
```

---

## Task 14: Property-based 與 metamorphic 測試

**Files:**
- Create: `tests/test_align_properties.py`

這是整份計畫裡唯一能抓到「沒人想到的組合」的測試技術：單元測試只測我們自己想到的案例，property test 讓 hypothesis 在一個「理論上就該合法」的輸入定義域裡亂試，找出這個定義域裡仍然存在、但沒被明確寫成單元測試的反例。

**設計取捨（先講清楚，避免以為是偷工）：** 這裡刻意把每次生成的 word 清單限制在單一小窗口（5–10 個字、每字時長 0.3–0.5 秒、字間 gap <=0.05 秒）。這不是為了偷懶少測——是因為 `align()` 本身不負責時長/行寬合法性（那是 Task 12 `enforce_duration` 的責任），如果生成任意長度或任意間隔的輸入，很容易生出「align() 正確地」產生一個過長或過寬的 cue，property test 就會一直斷言失敗在跟 `align()` 本身無關的地方。把定義域限制在「本來就該合法」的範圍內，property test 才能真正聚焦在驗證 `align()` 自己的責任：結構性不變量（單調、不重疊、在音訊範圍內）在各種潤稿編輯下永遠成立。

### Step 1: 寫失敗的測試

建立 `tests/test_align_properties.py`：

```python
from hypothesis import given, settings, strategies as st

from psr.align import align
from psr.models import Word
from psr.segment import raw_segment
from psr.validate import validate

CHAR_POOL = list("我們先來後安裝這是的一二三四五六七八九十你好嗎最近過得如何")


@st.composite
def word_lists(draw):
    """產生一個「單一窗口」的 word 清單：字數、每字時長、字間 gap 都控制在
    小範圍內，讓產生出來的視窗天生就落在驗證器的合法範圍內（寬度 <=20、
    時長 0.5-7.0 秒、閱讀速度 <=9）。"""
    n = draw(st.integers(min_value=5, max_value=10))
    words = []
    t = 0.0
    for _ in range(n):
        char = draw(st.sampled_from(CHAR_POOL))
        duration = draw(st.floats(min_value=0.3, max_value=0.5))
        gap = draw(st.floats(min_value=0.0, max_value=0.05))
        start = round(t + gap, 3)
        end = round(start + duration, 3)
        words.append(Word(text=char, start=start, end=end))
        t = end
    return words


@st.composite
def edited_lines(draw, words):
    """對 words 串接後的文字，在 8% 編輯預算內做隨機插入/刪除/替換，模擬
    潤稿（設計文件 §5 的硬不變量：正規化後編輯距離必須 <=8%）。回傳單一行
    組成的清單（模擬單行窗口）。"""
    original = "".join(w.text for w in words)
    budget = max(1, int(len(original) * 0.08))
    n_edits = draw(st.integers(min_value=0, max_value=budget))
    chars = list(original)
    for _ in range(n_edits):
        if not chars:
            break
        op = draw(st.sampled_from(["insert", "delete", "substitute"]))
        pos = draw(st.integers(min_value=0, max_value=len(chars) - 1))
        if op == "insert":
            chars.insert(pos, draw(st.sampled_from(CHAR_POOL)))
        elif op == "delete":
            del chars[pos]
        else:
            chars[pos] = draw(st.sampled_from(CHAR_POOL))
    return ["".join(chars)]


@given(st.data())
@settings(max_examples=300)
def test_align_result_always_satisfies_validator_invariants(data):
    """不管 align() 吐出什麼，只要它沒有降級成 None，結果就必須是一份
    結構完全合法的字幕：單調不重疊、在音訊範圍內、時長合法。"""
    words = data.draw(word_lists())
    lines = data.draw(edited_lines(words))

    result = align(words, lines)

    if result is None:
        return  # 降級是允許的結果，不是失敗

    audio_duration = words[-1].end
    violations = validate(result, audio_duration)
    assert violations == []


@given(word_lists())
@settings(max_examples=200)
def test_identity_polish_matches_raw_segment(words):
    """Metamorphic test：把 raw_segment 切出來的 cue 文字原封不動地當成
    「潤稿結果」餵回 align()（等於沒有潤稿、純粹重新斷句），產生的時間碼
    應該跟 raw_segment 本身在 1ms 內完全一致。

    這裡刻意重用 word_lists()：它產生的字間 gap 上限（0.05s）遠低於
    raw_segment 預設的 max_gap（0.6s），累積寬度上限也遠低於預設的
    max_width（20.0），所以 raw_segment 在這個策略下必定回傳單一 cue，
    讓這個 metamorphic test 不需要額外處理「多 cue 對齊」的邊界情況。
    """
    raw_cues = raw_segment(words)
    assert len(raw_cues) == 1  # 驗證上面這段推理沒有被之後的策略調整破壞

    lines = [cue.text for cue in raw_cues]
    aligned_cues = align(words, lines)

    assert aligned_cues is not None
    assert len(aligned_cues) == len(raw_cues)
    for aligned, raw in zip(aligned_cues, raw_cues):
        assert abs(aligned.start - raw.start) <= 0.001
        assert abs(aligned.end - raw.end) <= 0.001
```

### Step 2: 執行測試確認失敗

由於這兩個測試呼叫的 `align`、`raw_segment`、`validate` 都已在前面的任務實作完成，這一步理論上會**直接通過**，而不是失敗。這種情況下，先確認測試檔本身沒有語法錯誤或 import 錯誤：

```bash
uv run pytest tests/test_align_properties.py --collect-only
```

預期：能正常收集到 2 個測試，沒有 collection error。如果收集階段就報錯（例如打錯函式名稱），修正後再繼續；如果收集成功，直接跳到 Step 4（因為底層實作已經存在，這個任務新增的是「測試覆蓋」本身，不是新的產品程式碼）。

### Step 3: 寫最小實作

（無需新增實作——本任務測試的是既有函式的組合行為。若 Step 2 收集成功，跳過本步驟。）

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_align_properties.py -v
```

預期：

```
tests/test_align_properties.py::test_align_result_always_satisfies_validator_invariants PASSED
tests/test_align_properties.py::test_identity_polish_matches_raw_segment PASSED

============================== 2 passed ==============================
```

（每個測試內部各自執行 300 / 200 個 hypothesis 案例。）

### Step 5: commit

```bash
git add tests/test_align_properties.py
git commit -m "test(align): add property-based and metamorphic invariant tests"
```

---

## Task 15: 對抗性 fixtures 與 golden fixture

**Files:**
- Create: `tests/fixtures/words.json`
- Create: `tests/fixtures/expected.srt`
- Create: `tests/test_golden.py`
- Create: `tests/test_align_adversarial.py`

Golden fixture 是一份完整、真實感的 60 秒範例：一支螢幕錄製教學影片講「安裝 Python、打開終端機、輸入安裝指令、推上 GitHub、透過 API 溝通」，中文為主、夾雜三個英文技術詞（`Python`、`GitHub`、`API`）。`words.json` 是模擬的 ASR 輸出（含一個刻意植入的同音字誤聽：第 25 個字原本該是「指」，ASR 誤聽成「旨」），`expected.srt` 是完整跑過 `align()` → `enforce_duration()` → `render()` 之後的最終輸出，逐位元比對。

對抗性測試共用同一份 `words.json`，但餵給 `align()` 各種「LLM 出包」的潤稿行清單，驗證系統永遠不當機、永遠不產出非法時間軸。

### Step 1: 寫失敗的測試

建立 `tests/fixtures/words.json`（53 個 word，涵蓋 5 句話，句與句之間有 10 秒停頓模擬畫面操作，總長 59.24 秒）：

```json
[
  {"text": "大", "start": 0.0, "end": 0.3},
  {"text": "家", "start": 0.38, "end": 0.66},
  {"text": "好", "start": 0.74, "end": 1.06},
  {"text": "今", "start": 1.14, "end": 1.44},
  {"text": "天", "start": 1.52, "end": 1.8},
  {"text": "我", "start": 1.88, "end": 2.14},
  {"text": "們", "start": 2.22, "end": 2.5},
  {"text": "來", "start": 2.58, "end": 2.84},
  {"text": "安", "start": 2.92, "end": 3.22},
  {"text": "裝", "start": 3.3, "end": 3.6},
  {"text": "Python", "start": 3.68, "end": 4.23},
  {"text": "首", "start": 14.31, "end": 14.59},
  {"text": "先", "start": 14.67, "end": 14.93},
  {"text": "打", "start": 15.01, "end": 15.25},
  {"text": "開", "start": 15.33, "end": 15.61},
  {"text": "終", "start": 15.69, "end": 15.97},
  {"text": "端", "start": 16.05, "end": 16.31},
  {"text": "機", "start": 16.39, "end": 16.69},
  {"text": "然", "start": 26.77, "end": 27.03},
  {"text": "後", "start": 27.11, "end": 27.39},
  {"text": "輸", "start": 27.47, "end": 27.75},
  {"text": "入", "start": 27.83, "end": 28.07},
  {"text": "安", "start": 28.15, "end": 28.43},
  {"text": "裝", "start": 28.51, "end": 28.79},
  {"text": "旨", "start": 28.87, "end": 29.13},
  {"text": "令", "start": 29.21, "end": 29.49},
  {"text": "接", "start": 39.57, "end": 39.85},
  {"text": "著", "start": 39.93, "end": 40.19},
  {"text": "我", "start": 40.27, "end": 40.51},
  {"text": "們", "start": 40.59, "end": 40.85},
  {"text": "要", "start": 40.93, "end": 41.17},
  {"text": "把", "start": 41.25, "end": 41.49},
  {"text": "程", "start": 41.57, "end": 41.83},
  {"text": "式", "start": 41.91, "end": 42.15},
  {"text": "碼", "start": 42.23, "end": 42.51},
  {"text": "推", "start": 42.59, "end": 42.85},
  {"text": "上", "start": 42.93, "end": 43.17},
  {"text": "GitHub", "start": 43.25, "end": 43.85},
  {"text": "這", "start": 53.93, "end": 54.19},
  {"text": "樣", "start": 54.27, "end": 54.55},
  {"text": "團", "start": 54.63, "end": 54.91},
  {"text": "隊", "start": 54.99, "end": 55.25},
  {"text": "成", "start": 55.33, "end": 55.59},
  {"text": "員", "start": 55.67, "end": 55.93},
  {"text": "就", "start": 56.01, "end": 56.25},
  {"text": "能", "start": 56.33, "end": 56.57},
  {"text": "透", "start": 56.65, "end": 56.91},
  {"text": "過", "start": 56.99, "end": 57.25},
  {"text": "API", "start": 57.33, "end": 57.88},
  {"text": "互", "start": 57.96, "end": 58.22},
  {"text": "相", "start": 58.3, "end": 58.54},
  {"text": "溝", "start": 58.62, "end": 58.9},
  {"text": "通", "start": 58.98, "end": 59.24}
]
```

建立 `tests/fixtures/expected.srt`（byte-for-byte，注意每個區塊之間只有一個空行、檔案結尾恰好一個換行）：

```
1
00:00:00,000 --> 00:00:04,230
大家好，今天我們來安裝 Python

2
00:00:14,310 --> 00:00:16,690
首先打開終端機。

3
00:00:26,770 --> 00:00:29,490
然後輸入安裝指令。

4
00:00:39,570 --> 00:00:43,850
接著我們要把程式碼推上 GitHub。

5
00:00:53,930 --> 00:00:59,240
這樣團隊成員就能透過 API 互相溝通。
```

（用編輯器建立這個檔案時要確認：檔案結尾只有一個換行符，不要讓編輯器多加一個空行。）

建立 `tests/test_golden.py`：

```python
import json
from pathlib import Path

from psr.models import Word
from psr.align import align
from psr.refine import enforce_duration
from psr.srt import render

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# 這是「潤稿後」的字幕行。Phase 1 沒有真的呼叫 LLM，這份清單是手動模擬
# LLM 潤稿會輸出的內容：加上標點、把 ASR 誤聽的「旨令」修正回「指令」
# （words.json 裡第 25 個字其實是「旨」，這裡故意寫成正確的「指」，
# 用來驗證 align() 真的能吸收潤稿修正，而不是要求逐字相同）。
POLISHED_LINES = [
    "大家好，今天我們來安裝 Python",
    "首先打開終端機。",
    "然後輸入安裝指令。",
    "接著我們要把程式碼推上 GitHub。",
    "這樣團隊成員就能透過 API 互相溝通。",
]


def _load_words() -> list[Word]:
    raw = json.loads((FIXTURES_DIR / "words.json").read_text(encoding="utf-8"))
    return [Word(text=w["text"], start=w["start"], end=w["end"]) for w in raw]


def test_golden_fixture_byte_for_byte():
    words = _load_words()
    aligned = align(words, POLISHED_LINES)
    assert aligned is not None

    final = enforce_duration(aligned, words)
    actual_srt = render(final)

    expected_srt = (FIXTURES_DIR / "expected.srt").read_text(encoding="utf-8")
    assert actual_srt == expected_srt
```

建立 `tests/test_align_adversarial.py`：

```python
import json
from pathlib import Path

from psr.models import Word
from psr.align import align
from psr.refine import enforce_duration
from psr.validate import validate

FIXTURES_DIR = Path(__file__).parent / "fixtures"

BASE_LINES = [
    "大家好，今天我們來安裝 Python",
    "首先打開終端機。",
    "然後輸入安裝指令。",
    "接著我們要把程式碼推上 GitHub。",
    "這樣團隊成員就能透過 API 互相溝通。",
]


def _load_words() -> list[Word]:
    raw = json.loads((FIXTURES_DIR / "words.json").read_text(encoding="utf-8"))
    return [Word(text=w["text"], start=w["start"], end=w["end"]) for w in raw]


def _assert_graceful(words, lines):
    """對抗性輸入的共同斷言：align() 絕不可拋例外；如果它成功回傳 cues，
    整條 pipeline（含 enforce_duration）跑完後必須完全通過 validate()。
    align() 本身只保證結構性不變量（單調、不重疊、在音訊範圍內）——
    時長落在 [0.5, 7.0] 秒是 enforce_duration 的責任，所以這裡把兩者
    串起來一起驗，這也是為什麼真實 pipeline 裡 enforce_duration 一定要
    緊接在 align() 之後跑：align() 對「整段內容被刪掉」這種編輯只保證
    結構合法，不保證時長合法（被刪掉那段的時間會被前後鄰居吸收）。"""
    result = align(words, lines)
    if result is None:
        return
    final = enforce_duration(result, words)
    violations = validate(final, words[-1].end)
    assert violations == []


def test_llm_drops_a_whole_sentence():
    words = _load_words()
    lines = [BASE_LINES[0], BASE_LINES[1], BASE_LINES[3], BASE_LINES[4]]
    _assert_graceful(words, lines)


def test_llm_inserts_a_hallucinated_sentence():
    words = _load_words()
    lines = list(BASE_LINES)
    lines.insert(2, "這是一句完全捏造、原始逐字稿裡沒有的內容")
    _assert_graceful(words, lines)


def test_llm_reorders_sentences():
    words = _load_words()
    lines = [BASE_LINES[0], BASE_LINES[2], BASE_LINES[1], BASE_LINES[3], BASE_LINES[4]]
    _assert_graceful(words, lines)


def test_llm_hallucinates_ninety_percent_repeated_content():
    words = _load_words()
    lines = [BASE_LINES[0]] + [BASE_LINES[1]] * 9
    _assert_graceful(words, lines)


def test_empty_line_among_valid_lines():
    words = _load_words()
    lines = [BASE_LINES[0], "", BASE_LINES[1], BASE_LINES[2], BASE_LINES[3], BASE_LINES[4]]
    _assert_graceful(words, lines)


def test_pure_english_line():
    words = _load_words()
    lines = list(BASE_LINES)
    lines.append("This is a pure English line with no Chinese at all")
    _assert_graceful(words, lines)
```

### Step 2: 執行測試確認失敗

在建立 fixtures/測試檔之前，這些測試根本不存在；建立完成後，因為所有底層函式（`align`、`enforce_duration`、`render`、`validate`）在 Task 1–13 都已經實作完畢，這一步同樣預期**直接通過**，不是失敗。先確認能正常收集：

```bash
uv run pytest tests/test_golden.py tests/test_align_adversarial.py --collect-only
```

預期：收集到 1 + 6 = 7 個測試，沒有 collection error。如果 `test_golden_fixture_byte_for_byte` 沒有直接通過（多半是 fixture 檔案裡多了/少了換行、或全形/半形標點打錯），先用下面指令印出實際輸出的 `repr()` 跟 fixture 的 `repr()` 逐字元比對：

```bash
uv run python -c "
import json
from pathlib import Path
from psr.models import Word
from psr.align import align
from psr.refine import enforce_duration
from psr.srt import render

words = [Word(**w) for w in json.loads(Path('tests/fixtures/words.json').read_text(encoding='utf-8'))]
lines = ['大家好，今天我們來安裝 Python', '首先打開終端機。', '然後輸入安裝指令。', '接著我們要把程式碼推上 GitHub。', '這樣團隊成員就能透過 API 互相溝通。']
cues = enforce_duration(align(words, lines), words)
print(repr(render(cues)))
"
```

### Step 3: 寫最小實作

（無需新增實作——本任務測試的是既有函式在真實資料與對抗性輸入下的組合行為。若 Step 2 收集且執行皆成功，跳過本步驟。）

### Step 4: 執行測試確認通過

```bash
uv run pytest tests/test_golden.py tests/test_align_adversarial.py -v
```

預期：

```
tests/test_golden.py::test_golden_fixture_byte_for_byte PASSED
tests/test_align_adversarial.py::test_llm_drops_a_whole_sentence PASSED
tests/test_align_adversarial.py::test_llm_inserts_a_hallucinated_sentence PASSED
tests/test_align_adversarial.py::test_llm_reorders_sentences PASSED
tests/test_align_adversarial.py::test_llm_hallucinates_ninety_percent_repeated_content PASSED
tests/test_align_adversarial.py::test_empty_line_among_valid_lines PASSED
tests/test_align_adversarial.py::test_pure_english_line PASSED

============================== 7 passed ==============================
```

### Step 5: commit

```bash
git add tests/fixtures/words.json tests/fixtures/expected.srt tests/test_golden.py tests/test_align_adversarial.py
git commit -m "test(align): add golden fixture and adversarial edge-case tests"
```

---

## 驗收標準

- `uv run pytest` 在 repo 根目錄執行，全部測試綠燈（本計畫完成後應為 72 個測試全數通過，含 hypothesis 內部展開的數百個案例）。
- 整個測試套件執行過程零網路呼叫——`uv run pytest -v` 的輸出裡不應該出現任何逾時或連線相關的錯誤，且可以在斷網環境下直接執行。
- `src/psr/align.py`、`src/psr/validate.py`、`src/psr/srt.py`、`src/psr/text.py`、`src/psr/segment.py`、`src/psr/refine.py` 這幾個檔案裡，檢查所有 `import` 語句：不應該出現 `requests`、`httpx`、`google.*`、`groq`、任何網路 client 函式庫，也不應該出現 `open()`、`Path.read_text()` 等檔案系統存取（測試檔 `tests/test_golden.py`、`tests/test_align_adversarial.py` 讀取 fixture 檔案除外——那是測試基礎設施,不是產品程式碼）。

## 不在此 Phase 範圍

以下項目明確排除在 Phase 1 之外，若實作過程中發現「好像應該順便做一下」，先停下來——這是刻意的範圍邊界，不是遺漏：

- **Google Drive 整合**（`drive.py`：認證、preflight、find-or-update、原子上傳）—— Phase 2。
- **Groq API 呼叫**（`asr/groq.py`）—— Phase 3。
- **Colab CLI 編排**（`asr/colab.py`、`asr/remote_job.py`）—— Phase 5。
- **GitHub Actions workflow**（`.github/workflows/*.yml`）—— Phase 6。
- **glossary.yml 載入與套用**（`config.py` 裡的 glossary 解析、Whisper prompt 組裝）—— Phase 4（潤稿階段才需要）。
- **實際呼叫 LLM 做潤稿**（`polish.py`：窗口切分、快取、JSON schema、8% 編輯距離不變量的執行期檢查）—— Phase 4。本 Phase 的 `align()` 只負責「假設已經拿到潤稿後的文字，怎麼貼回時間軸」，不負責產生這份文字。
- **`manifest.py`（provenance 與 stage key 計算）**、**`issue.py`（issue 內文嚴格解析）**、**`cli.py`**—— 分屬 Phase 2 與 Phase 6，皆需要與外部系統互動或處理不可信輸入，不符合本 Phase「零網路、零憑證」的範圍定義。
