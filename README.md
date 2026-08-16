# polish-screen-record

**把 Google Drive 或 YouTube 上的長時間螢幕錄影，自動變成讀得順的繁體中文字幕。**
開一個 issue、貼上連結、加一個 label，十分鐘後 SRT 就出現在影片旁邊。

[![ci](https://github.com/htlin222/polish-screen-record/actions/workflows/ci.yml/badge.svg)](https://github.com/htlin222/polish-screen-record/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![tests](https://img.shields.io/badge/tests-211%20passing-brightgreen.svg)](tests/)

> 一支 87 分鐘的教學影片，端到端 **602 秒**、成本 **$0.008 美金**，全部跑在免費的 GitHub Actions 與 Colab T4 上。

---

## 它解決什麼問題

自動語音辨識給你的是**一長串沒有標點的字**。直接拿去當字幕，會得到這種東西：

```
今天這堂課是關於提示詞設計與實作技巧那我
覺得要了解我們接下來一個半小時要做什麼
```

斷在詞中間、沒有標點、繁簡混雜。而多數「AI 字幕」工具的做法是把逐字稿丟給大型語言模型，請它「潤稿並斷行」——然後你會發現時間軸開始漂移，因為模型同時在改文字**和**決定斷點，沒有東西能保證兩者對得起來。

這個專案的做法不同：

```
今天這堂課是關於提示詞設計與實作技巧。
那我覺得要了解我們接下來一個半小時要做什麼事情，
我們就要先從標題開始談起。
```

---

## 核心設計：先斷句，再定時

整條 pipeline 最重要的一個決定是**不讓語言模型碰時間碼**。

| 階段 | 做什麼 | 保證 |
| --- | --- | --- |
| **1. 加標點** | LLM 只在原文插入標點，**一個字都不改** | 去掉標點後與原文逐字相同 |
| **2. 對回時間** | 純函式查表 | 每個字元都對得到它所屬的 word |
| **3. 修整** | 確定性規則：碎片吸收、時長修正、折行 | 不重疊、不空白、可讀 |

因為第一階段的不變量可以**嚴格驗證**，第二階段就從「猜測」變成「查表」——不需要 diff、不需要錨點、不可能漂移。副產品是一個其他做法拿不到的健康指標：

```
原文覆蓋率：100.0%
```

低於 100% 就代表有內容在過程中掉了。

<details>
<summary>為什麼不讓 LLM 一次做完？（實測數據）</summary>

先前的版本正是那樣做的，然後用 `difflib` 把結果貼回時間軸。同一支影片的對照：

| | LLM 同時潤稿+斷句 | 先斷句再定時 |
| --- | --- | --- |
| 驗證違規 | 307 | **166** |
| 原文覆蓋率 | 無法檢查 | **100.0%** |
| 最長字幕 | 無法拆解的長句 | 14.6 秒 |

更麻煩的是失效模式：模型的斷句失控時，出現過整個窗口只回 2 行（預期 105 行）、55% 的字幕不足兩個字元。而「合併」只能把碎片黏回去，**不能拆開過長的句子**——那是架構本身的限制，不是調 prompt 能解決的。

</details>

---

## 特色

- **雙轉錄引擎**：Colab T4 免費 GPU 為主（13.2 倍實時），Groq Whisper API 為備。基礎設施層失敗才 fallback，程式錯誤直接失敗而不被掩蓋。
- **內容定址的階段式 pipeline**：每階段 key = `hash(階段名 + 版本 + 輸入雜湊 + 參數)`。Drive 上已存在且 key 相符的產物直接重用。resume 是免費附贈的。
- **Drive `md5Checksum` 零傳輸取得**：5.98 GB 的影片不用下載一個位元組就拿得到內容指紋。
- **確定性繁化**：查表而非 LLM。刻意採 OpenCC `s2tw`（純字形）而非 `s2twp`——後者會把「打開」改成「開啟」、「權限」改成「許可權」，逐字稿是**轉錄**不是在地化。
- **可維護的術語表**：`glossary.yml` 一份餵兩處，同時修正 ASR 誤聽與潤稿用詞。
- **最小權限**：`drive.readonly` + `drive.file` 的組合讓 token 在數學上無法修改任何不是它建立的檔案。Colab VM 只拿唯讀短效 token，從頭到尾看不到 refresh token。
- **211 個測試，全部零網路**。CI 另檢查純函式核心沒有偷偷引入網路相依。

---

## 快速開始

### 需要什麼

| 項目 | 說明 |
| --- | --- |
| Google Cloud 專案 | 啟用 Drive API，自建 OAuth 桌面用戶端（gcloud 內建的用戶端被 Google 封鎖存取 Drive） |
| DeepSeek API key | 加標點用。87 分鐘影片約 $0.008 美金 |
| Colab 帳號 | 免費層即可 |
| Groq API key | 選用，Colab 拿不到 GPU 時的備援 |

### 安裝

```bash
git clone https://github.com/htlin222/polish-screen-record
cd polish-screen-record
uv sync --frozen
```

### 設定 GitHub Secrets

```bash
gh secret set GCP_ADC_JSON        < ~/.config/gcloud/application_default_credentials.json
gh secret set GOOGLE_OAUTH_CLIENT < client_secret.json
gh secret set GOOGLE_OAUTH_TOKEN  < token.json
gh secret set DEEPSEEK_API_KEY
gh secret set GROQ_API_KEY        # 選用
```

不需要 fine-grained PAT——workflow 用 Actions 自動注入的 `GITHUB_TOKEN` 就夠，它每次執行重新簽發、結束即失效。

### 使用

開一個 issue，內文貼上連結：

```
https://drive.google.com/file/d/xxxxxxxxxxxxxxxxxxxxxxxxxxx/view
```

或

```
https://www.youtube.com/watch?v=xxxxxxxxxxx
```

加上 `srt` label。十分鐘後 SRT 出現在影片旁邊，並在 issue 留言回報。

`srt-dryrun` 會跑完整流程但不寫入 Drive，適合調整術語表時使用。

---

## 架構

```
issue（貼連結，加 srt label）
  │
  ├─ 權限閘門：只有 repo 擁有者加的 label 才觸發
  ├─ 嚴格解析：恰好一個連結，0 個或 2 個都失敗而非猜測
  │
  ├─ preflight ── Drive md5Checksum（零傳輸）
  │
  ├─ 轉錄
  │    Colab T4 ── VM 直接從 Drive/YouTube 抓影片，runner 不碰 GB 級檔案
  │    └ 失敗 → Groq Whisper（切塊 + 時間偏移合併）
  │
  ├─ 加標點 ── LLM 只加標點，去標點後須與原文逐字相同
  ├─ 對回時間 ── 純函式查表
  ├─ 修整 ── 碎片吸收、時長修正、折行、繁化
  ├─ 驗證 ── 單調、不重疊、非空、行寬、閱讀速度
  │
  └─ 寫回 Drive ── find-or-update 冪等，最終 SRT 最後上傳（順序即 checkpoint）
```

### 模組

| 模組 | 職責 |
| --- | --- |
| `punctuate.py` | 第一階段：加標點與不變量檢查 |
| `timeline.py` | 第二階段：對回時間、依標點與靜音斷句 |
| `refine.py` | 碎片吸收、時長修正、折行 |
| `validate.py` | 後置條件檢查 |
| `text.py` | 正規化與索引映射、顯示寬度、繁化 |
| `drive.py` | OAuth、preflight、冪等寫入、重試 |
| `asr/` | Colab 編排、Colab VM 上執行的工作、Groq fallback |
| `glossary.py` | 術語表載入（Whisper 224-token prompt 與潤稿 prompt） |
| `manifest.py` | 內容定址的階段 key 與 provenance |

---

## 已知限制

- 驗證器的行寬與閱讀速度閾值照通用字幕規範訂，但講課字幕的優先序不同（內容正確、語句通順優先於行寬）。目前會回報數十個這類違規。
- YouTube 路徑有單元測試與 `yt-dlp` metadata 驗證，但端到端尚未實跑。
- 兩個不同 issue 指向同一支影片時仍會並行（concurrency group 只能用 issue number）。原子寫入保證不會產生半截檔案，但後完成者會覆蓋先完成者。

---

## 授權

MIT。詳見 [LICENSE](LICENSE)。
