from hypothesis import given, settings, strategies as st

from psr.text import display_width, normalize


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


def test_display_width_pure_chinese():
    assert display_width("你好嗎最近過得如何呀") == 10.0


def test_display_width_pure_latin():
    assert display_width("Python") == 3.0


def test_display_width_mixed():
    assert display_width("Python你好") == 5.0
