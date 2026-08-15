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


def test_clean_text_removes_space_between_cjk_but_keeps_it_around_ascii():
    from psr.segment import clean_text
    # Whisper 的中文 word token 帶前導空格（實測 ' 來'），
    # 直接串接會產生「導演 來個特寫」這種夾雜空格的中文字幕。
    assert clean_text("導演 來個特寫") == "導演來個特寫"
    # 但英文術語兩側的空格是必要的，不能一併刪掉。
    assert clean_text("安裝 Python 環境") == "安裝 Python 環境"
    assert clean_text("  前後空白  ") == "前後空白"


def test_raw_segment_strips_whisper_leading_spaces():
    words = [Word("導", 0.0, 0.4), Word("演", 0.4, 0.6),
             Word(" 來", 0.6, 0.9), Word("個", 0.9, 1.1)]
    cues = raw_segment(words)
    assert " " not in cues[0].text, f"字幕殘留空格：{cues[0].text!r}"
