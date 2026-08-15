from psr.models import Word, Cue


def enforce_duration(
    cues: list[Cue],
    words: list[Word],
    min_s: float = 0.5,
    max_s: float = 7.0,
    audio_duration: float | None = None,
) -> list[Cue]:
    """修正字幕時長：太長的在字間最大間隔處遞迴切開；太短的往後延或向鄰居
    借時間。絕不製造重疊。

    audio_duration 給定時，最後一條字幕不會被延長超過音訊結尾——否則
    validate 的邊界檢查會判它違規。省略時不設上限（最後一條照常延到 min_s）。
    """
    split_cues = _split_long_cues(cues, words, max_s)
    return _extend_short_cues(split_cues, min_s, audio_duration)


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
    if len(cue.text) < 2:
        # 文字只有一個字元，切開必然有一半是空的。寧可留一條過長的字幕，
        # 也不要產生一條佔著螢幕時間卻沒有字的空白字幕。
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

    # 切點的字元位置用 ASR 左半的字元數估計，然後**箝制在兩側都非空的範圍內**。
    #
    # 這個估計本身是不精確的：那是 ASR 原始逐字稿的字元數，而 cue.text 是潤稿
    # 後的文字，兩者字元不保證對應——潤稿會改字、加標點、刪贅字，那正是它的
    # 目的。但潤稿多半只微調長度，所以估計在常態下是準的，比用時間比例去推
    # 字元位置更好（講者停頓時時間比例會嚴重偏離字元比例）。
    #
    # 箝制不是美化，是防災。潤稿若把句子大幅縮短，未箝制的 split_char 會超出
    # 文字長度，cue.text[:split_char] 回傳整串、cue.text[split_char:] 回傳空
    # 字串，產出一條佔著數秒螢幕時間卻沒有字的空白字幕——而且不拋任何錯誤，
    # 時長合法、不重疊、行寬 0、閱讀速度 0，所有其他規則都抓不到它。
    split_time = left_words[-1].end
    split_char = sum(len(w.text) for w in left_words)
    split_char = max(1, min(len(cue.text) - 1, split_char))

    left_text = cue.text[:split_char]
    right_text = cue.text[split_char:]

    # 保留 cue 原本的外側邊界，只在中間切開。用 left_words[0].start 當左半起點
    # 會在 cue 起始於某個 word 內部時丟失原本的起始時間。
    left = Cue(index=cue.index, start=cue.start, end=split_time, text=left_text)
    right = Cue(index=cue.index, start=right_words[0].start, end=cue.end, text=right_text)

    return _split_one(left, words, max_s) + _split_one(right, words, max_s)


_EPS = 1e-9


def _extend_short_cues(
    cues: list[Cue], min_s: float, audio_duration: float | None = None
) -> list[Cue]:
    """把過短的字幕延長到 min_s。

    這個函式會收到兩種形狀完全不同的輸入，兩種都必須處理：

      - segment.raw_segment 的輸出「有空檔」→ 直接往空檔延伸即可
      - align 的輸出「首尾相接」（cue[i].end == cue[i+1].start）→ 空檔為零，
        只能向鄰居借時間，也就是推移兩者共用的邊界，且只借到鄰居本身仍保有
        min_s 為止

    只實作前者的話，align 輸出中任何過短的字幕都會原封不動通過，接著被
    validate 判為違規、導致整個窗口降級——延長功能形同虛設。
    """
    result = list(cues)
    for i, cue in enumerate(result):
        start, end = cue.start, cue.end
        if end - start >= min_s:
            continue

        # 1) 先吃掉與下一條之間的空檔（若有）。用 max 避免在異常輸入下反而縮短。
        if i + 1 < len(result):
            limit = result[i + 1].start
        else:
            # 最後一條沒有下一條擋著，但不能延過音訊結尾。
            limit = start + min_s if audio_duration is None else min(start + min_s, audio_duration)
        end = min(start + min_s, max(end, limit))

        # 2) 仍不足就向右鄰借，推移共用邊界。借完右鄰仍有 min_s，
        #    所以之後輪到它時不會被判定為過短，不會連鎖。
        if start + min_s - end > _EPS and i + 1 < len(result):
            nxt = result[i + 1]
            borrow = min(start + min_s - end, max(0.0, (nxt.end - nxt.start) - min_s))
            if borrow > 0:
                end += borrow
                result[i + 1] = Cue(index=nxt.index, start=end, end=nxt.end, text=nxt.text)

        # 3) 還不足就向左鄰借。左鄰已處理過，同樣只借到它仍保有 min_s。
        if start + min_s - end > _EPS and i > 0:
            prv = result[i - 1]
            borrow = min(start + min_s - end, max(0.0, (prv.end - prv.start) - min_s))
            if borrow > 0:
                start -= borrow
                result[i - 1] = Cue(index=prv.index, start=prv.start, end=start, text=prv.text)

        # 兩邊都借不到時就維持原樣：這代表整段真的沒有空間，
        # 交給 validate 攔下並降級，比硬造出重疊誠實。
        result[i] = Cue(index=cue.index, start=start, end=end, text=cue.text)
    return result


def _reindex(cues: list[Cue]) -> list[Cue]:
    return [Cue(index=i + 1, start=c.start, end=c.end, text=c.text) for i, c in enumerate(cues)]
