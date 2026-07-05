# PDF Check MinerU

PDF Check MinerU 是一套用來比對「舊版 PDF」與「新版 PDF」差異的本地端審核工具。它會把 PDF 解析成文字、表格和位置資訊，再把新增、刪除、文字修改、數字修改標在畫面上，讓審核人員可以逐筆確認、留下紀錄，最後匯出報告或封存。

這個專案特別適合保險 DM、條款、費率表、簡章、公告等需要反覆改版與人工審核的 PDF。

## 目前技術狀態（2026-07-05）

| 項目 | 正式使用狀況 |
|------|--------------|
| 部署 | 維持 Docker Compose；本機與 OCI 均使用 Linux containers |
| 後端 | FastAPI + 有限比對佇列 + 流程協調器；同步 SQLite I/O 交由 FastAPI threadpool，避免阻塞 event loop |
| 解析 | PyMuPDF 輕量快篩 → Docling 表格解析 → MinerU fallback；影像型 PDF 預設保留視覺差異，MinerU OCR 召回需明確開啟 |
| 資源控制 | 重型 parser 與比對任務預設各只同時執行 1 個，並限制等待佇列，適合 CPU-only 主機 |
| 快取 | PDF SHA-256 解析快取、single-flight、像素/NCC/OCR 配對快取與跨重啟磁碟快取均已啟用 |
| 前端 | React 19 + TypeScript 6 + Vite 8；支援 WebSocket 進度、輪詢取消、虛擬列表與對話框鍵盤操作 |
| 正式驗證 | 後端 127 項測試通過、前端 production build 通過；Mac M4 原生與正式 Docker 映像皆完成 cold＋warm 各 30 runs 驗收 |
| OCI | ARM64、CPU-only、MinerU 3.4.0；`b875a9b` 已部署，後端為 764MB `torch +cpu` 映像；鳳守愛 cold smoke 初步／完整 4.74／18.62 秒 |

現行資料流、模組邊界與部署架構請看 `docs/technical-architecture.md`；本輪效能與準確度實作紀錄見 `docs/ocr_optimization_implementation_2026-07-04.md`。

## 2026-07-04：雙軌證據與漸進分析

比對結果已改成兩條明確的審核軌道：

- `content`：有可靠新舊值的文字、數字、條款與表格內容差異。
- `needs_visual_review`：像素證明區域有變，但 OCR 無法可靠解讀；仍會保留 bbox 與裁切圖，不再只縮成一個 `suppressed_count`。

每筆差異現在帶有穩定 `candidate_id`、`risk_level`、`decision_reason`、`evidence[]` 與模型版本資訊。API/WebSocket 會先送 `preliminary_result`，有啟用 OCR 召回或第二引擎時再送 `result_updated`，最後送 `complete`。分析未完成、關鍵差異或待人工區域未審完時不得封存。

另新增：

- 依 PDF 雜湊與演算法設定建立的跨重啟像素分析快取。
- 依 page、bbox IoU、列欄結構與表頭簽章配對表格，不再只依輸出順序。
- PaddleOCR 實驗只辨識已變更 ROI，不再無條件全頁重跑。
- `benchmarks/golden/v1/manifest.json` 六對商品 DM 黃金回歸集。
- `backend/scripts/run_golden_benchmark.py`，可用完全相同條件比較 Mac、OCI 與未來地端主機。

## 一句話說明

把兩份 PDF 丟進系統，系統會找出差異，讓人員在畫面上確認，並保存「誰在什麼時間審了什麼」。

## 適合誰使用

| 角色 | 可以做什麼 |
|------|------------|
| 審核人員 | 上傳新舊 PDF、查看差異、標記確認或異常、填寫備註 |
| 管理者 | 管理帳號、查看留存紀錄、匯出審核資料 |
| 開發/維運人員 | 部署 Docker、調整解析設定、檢查資源用量 |

## 主要功能

- 上傳兩份 PDF 進行比對
- 支援案號，匯出與封存檔名可加上案號前綴
- 專案設定可自動建議，也可手動修改
- 在 PDF 畫面上標示差異位置
- 搜尋差異內容、頁碼、審核人員、案號與備註
- 審核每一筆差異，記錄狀態、審核人員與備註
- 若審核紀錄被修改，保留修改前後摘要
- 匯出標註 PDF、Excel、審核紀錄 TXT/CSV
- 留存 PDF 與核驗歷史，之後可查詢當時的審核結果
- 先用 PyMuPDF 快篩表格，再依 Docling → MinerU 循序解析，兼顧格子座標與複雜表格 fallback

## 使用流程

1. 登入系統。
2. 在上傳頁輸入案號，這是選填欄位。
3. 選擇舊版 PDF 與新版 PDF。
4. 專案設定會依檔名自動建議，也可以自己改。
5. 按下開始比對。
6. 進入比對畫面後，逐筆確認差異。
7. 需要時匯出報告或留存 PDF。
8. 之後可從最近比對紀錄或核驗歷史查詢。

## 快速啟動

### Windows

雙擊：

```text
一鍵啟動PDF比對系統.bat
```

停止服務時雙擊：

```text
一鍵停止PDF比對系統.bat
```

### macOS

雙擊：

```text
start-mac.command
```

停止服務時雙擊：

```text
stop-mac.command
```

### Docker

```bash
docker compose up --build -d
```

啟動後打開：

```text
http://localhost:8001
```

停止：

```bash
docker compose down
```

第一次建置 MinerU image 時會下載 pipeline 模型，檔案較大，可能需要一段時間。模型會被寫入 image layer；只要 Docker build cache 未失效，後續建置可重用該層。runtime 的 ModelScope volume 用於容器執行期間的快取，不會取代 build 階段的模型下載。

## 初次登入

系統第一次啟動時會建立 `admin` 管理者帳號。

目前採固定本機管理員登入設定。系統不會產生 `.initial_admin_password`，也不會在 log 或畫面顯示初始密碼資訊。

注意：啟動時會確保 `admin` 帳號存在、啟用且具管理員權限。若正式環境要改成非固定密碼，需調整後端 `ensure_default_admin()` 的啟動策略。

## 系統怎麼判斷差異

簡化版流程如下：

```text
上傳 PDF
  -> 解析文字、表格、圖片與座標
  -> 比對舊版與新版內容
  -> 產生差異清單
  -> 在 PDF 畫面上標示位置
  -> 人工審核與留存紀錄
```

系統不是單純用肉眼截圖比對。它會同時看幾種資料：

- 文字內容是否新增、刪除或修改
- 數字是否變更
- 表格儲存格是否變更
- 圖片或掃描區域是否有差異
- PDF 上的座標位置，讓差異可以被標在正確頁面

## 重要設定

| 變數 | 預設值 | 白話說明 |
|------|--------|----------|
| `MINERU_API_URL` | 空值（Host） / `http://mineru-api-minerU:18080`（Docker） | MinerU 解析服務位置；空值時會略過 MinerU、走備援解析路徑 |
| `DATA_DIR` | `<repo>/runtime`（Host） / `/app/runtime`（Docker） | 上傳檔案、資料庫、匯出檔案存放位置 |
| `ENABLE_PADDLE_OCR_EXPERIMENT` | `false` | 實驗性本機 PaddleOCR 第二引擎；預設關閉，只寫入 `engine_stats` / `engine_warnings` 做 A/B 評估 |
| `PADDLE_OCR_LANG` | `ch` | PaddleOCR 語言設定 |
| `PADDLE_OCR_DPI` | `200` | PaddleOCR PDF rasterize DPI；越高越吃 CPU/RAM |
| `PADDLE_OCR_MAX_PAGES` | `20` | 單份 PDF 最多實驗辨識頁數，避免測試時硬體負載失控 |
| `PADDLE_OCR_MIN_CONFIDENCE` | `0.35` | PaddleOCR 候選文字最低信心分數；第一階段只影響實驗統計，不直接改正式差異 |
| `OCR_LANGS` | `chi_tra+chi_sim+eng` | OCR 使用繁中、簡中與英文 |
| `ENABLE_IMAGE_TEXT_RECALL` | `false` | 影像型 PDF 是否額外跑 MinerU OCR 召回層 |
| `IMAGE_TEXT_RECALL_STRATEGY` | `alignment` | 召回層策略，可選 `alignment`、`heuristic`、`hybrid` |
| `TABLE_PARSER_STRATEGY` | `docling_first` | 表格引擎順序；預設先取 Docling cell bbox，無表格時才 fallback MinerU。`parallel_race` 僅供舊版 A/B |
| `ENABLE_LIGHTWEIGHT_TABLE_PROBE` | `true` | 先用 PyMuPDF 幾何線條／數字格網快篩；無表格跡象時不載入重型引擎 |
| `HEAVY_PARSER_MAX_CONCURRENCY` | `1` | MinerU／Docling／OpenDataLoader 同時執行上限，避免 CPU-only 主機過度併發 |
| `ENABLE_PARSER_CACHE` | `true` | 依 PDF SHA-256 快取解析結果；同一服務程序內重複比對不重新解析 |
| `PARSER_CACHE_MAX_ENTRIES` | `8` | 記憶體解析快取最多保留文件數 |
| `ENABLE_PIXEL_DIFF_CACHE` | `true` | 依新舊 PDF 內容雜湊快取像素/NCC/OCR 結果，重新比對時不重跑 OCR |
| `PIXEL_DIFF_CACHE_MAX_ENTRIES` | `8` | 記憶體像素差異快取最多保留文件配對數 |
| `ENABLE_PERSISTENT_ANALYSIS_CACHE` | `true` | 將昂貴像素分析寫入 runtime 快取，容器重啟後仍可重用 |
| `PERSISTENT_ANALYSIS_CACHE_MAX_ENTRIES` | `128` | 每種分析 artifact 最多保留筆數 |
| `ENABLE_DOCLING_PARALLEL` | `true` | 舊版相容設定；只有 `TABLE_PARSER_STRATEGY=parallel_race` 的 A/B 情境才有意義 |
| `GENERATE_SNAPSHOTS` | `true` | 比對完成後是否產生頁面快照 |
| `SNAPSHOT_DIFF_PAGES_ONLY` | `true` | 只為有差異的頁面產生快照 |
| `JWT_SECRET` | 自動產生 | 登入 token 加密用密鑰 |

## 影像型 PDF 召回模式

當新舊 PDF 都是掃描圖或圖片字時，純像素 diff 雖然能知道「哪裡有變」，但不一定能提供可直接閱讀的文字片段。這時可開啟召回層，強制用 MinerU OCR 補文字線索。

- 正式預設仍是 `ENABLE_IMAGE_TEXT_RECALL=false`
- 相容性預設策略是 `IMAGE_TEXT_RECALL_STRATEGY=alignment`
- 若你在跑 `商品DM/` 這類 image-only 樣本回歸，建議先用 `hybrid` 看輸出品質

| 策略 | 適合情境 | 特性 |
|------|----------|------|
| `alignment` | 先求穩定、要減少 OCR 重切段碎片 | 用文字序列對齊，比舊版 bbox 配對更能吃掉重分段噪音 |
| `heuristic` | 要回看舊行為、做回歸對照 | 走舊的 bbox/位置配對路徑，適合拿來對比歷史結果 |
| `hybrid` | 要在真實樣本上兼顧召回與可讀性 | 綜合 `alignment` 與 `heuristic`，會壓掉客服電話、日期碎片等雜訊，保留長中文新增、日期/文號、費率數字變更 |

在已可連到 MinerU API 的後端環境，可直接用 A/B 腳本掃 `商品DM/`：

```bash
cd backend
OCR_CACHE_DIR=/tmp/pdfcheck_ocr_cache \
python scripts/compare_recall_strategies.py \
  --dm-root ../商品DM \
  --output /tmp/dm_recall_ab.json
```

說明：

- 腳本會比較 `alignment` 與 `heuristic`，並預設額外輸出 `hybrid`
- `OCR_CACHE_DIR` 會依 PDF 的 SHA-256 快取 OCR 結果，重跑時可省下大量時間
- 更完整的真實容器回歸流程，請看 `docs/recall-regression-runbook.md`
- 過去商品 DM 的 A/B 分析紀錄，請看 `docs/image_text_recall_strategy_ab_2026-05-26.md`

## PaddleOCR 實驗版

PaddleOCR 已接入第一版本機第二 OCR 引擎，但目前是企業導入前的 A/B 實驗模式：

- 預設關閉，不影響現有 MinerU / Docling / visual diff 正式流程。
- 不使用外部 OCR API，也不需要 API Token；PDF 不會因這個功能送出內網。
- 第一階段只寫入 `engine_stats.paddle_ocr` 與 `engine_warnings`，不直接把候選結果升成正式差異。
- 主要觀察影像型 PDF、掃描 PDF、圖片字、費率/百分比數字是否有漏報改善。
- 正式 Docker image 預設不含 PaddleOCR 套件與模型；要實測需另外做 PaddleOCR profile 或在企業內網 image build 階段預載。

快速單機測試：

```bash
cd backend
ENABLE_PADDLE_OCR_EXPERIMENT=true \
python scripts/run_paddleocr_experiment.py /path/old.pdf /path/new.pdf --force-image-mode
```

輸出重點看：

- `paddle_ocr.candidate_diff_count`
- `paddle_ocr.changed_numeric_tokens`
- `paddle_ocr.unconfirmed_changed_numeric_tokens`
- `engine_warnings`

若 `unconfirmed_changed_numeric_tokens` 在真實樣本中經人工確認多數有效，下一階段才考慮把它升級為正式高風險差異；否則維持提示給 reviewer 覆核。完整說明請看 `docs/paddleocr-experiment.md`。

## 資料會存在哪裡

Docker 部署時，資料會存在 Docker volume，容器重啟後不會消失。

主要資料：

| 資料 | 用途 |
|------|------|
| SQLite database | 專案、比對紀錄、審核紀錄、帳號、封存紀錄 |
| uploads | 原始上傳 PDF |
| exports | 匯出 PDF、Excel、TXT、CSV |
| archive | 留存用 PDF 與核驗歷史 |
| snapshots | 稽核用頁面快照 |
| model cache | MinerU / Hugging Face / ModelScope 模型快取 |

## 資料來源與隱私邊界

| 來源 | 內容 | 是否外傳 |
|------|------|----------|
| 使用者上傳 | 舊版 PDF、新版 PDF、核對清單 CSV/Excel | 不會主動外傳，保存在本機/伺服器 runtime |
| 使用者輸入 | 案號、專案設定、審核狀態、審核備註 | 不會主動外傳，寫入 SQLite |
| MinerU 模型 | PDF 版面解析模型 | 第一次建置可能下載模型；解析時在本機/容器內執行 |
| Python/npm 套件 | 系統執行需要的開源套件 | 安裝或建置時從套件來源下載 |
| 匯出檔案 | 標註 PDF、Excel、TXT、CSV | 由使用者自行下載與保存 |

正式使用時，建議把伺服器放在公司可控網路內，並定期備份 runtime volume。

## 推薦硬體

目前實際瓶頸不是前端，而是 Docker 常駐的 `backend-minerU` + `mineru-api-minerU`、MinerU/Docling 模型、影像型 PDF 的 OCR，以及大量快照/封存檔。預設 compose 不啟用 GPU，所以請先用 CPU 與 RAM 規劃；GPU 只視為未來加速選項，不是部署必要條件。

| 情境 | CPU | RAM | SSD | 建議用途 |
|------|-----|-----|-----|----------|
| 最低試跑 | 4 核 | 16GB | 120GB 以上 | 功能展示、短 PDF、少量比對；不適合長時間跑商品 DM 回歸 |
| 單人正式使用 | 6 到 8 核 | 24GB | 256GB 以上 | 一般保險 DM / 條款比對、少量封存 |
| 1 到 3 人穩定使用 | 8 核以上 | 32GB | 512GB 以上 | Docker 常駐、較長 PDF、週期性商品 DM 回歸 |
| 長期主力 / 多任務 | 12 核以上 | 48 到 64GB | 1TB NVMe | 多份影像型 PDF、OCR A/B、保留大量 runtime 與匯出檔 |

實務建議：

- `16GB RAM` 只算能跑，不算舒服。MinerU、Docling、Docker Desktop、瀏覽器與開發工具同時開時很容易逼近上限。
- `24GB RAM` 是單人使用的合理起點；要常跑 `商品DM/` 回歸或多份 PDF，建議直上 `32GB` 以上。
- `256GB SSD` 不建議當長期主機。Docker image、ModelScope/Hugging Face 快取、runtime、匯出 PDF、快照 PNG 會持續累積。
- 一份 4 到 6 頁的影像型商品 DM 若進 MinerU forced-OCR，CPU-only 環境可能跑數分鐘；多人同時使用時請用任務佇列或限制同時比對數。

### 平台採購建議

| 平台 | 建議規格 | 適合情境 | 備註 |
|------|----------|----------|------|
| macOS / Mac mini | `M4 / 24GB / 512GB` 起；長期主力建議 `M4 Pro / 48GB / 1TB` | 本機開發、小型內部機、1 到 3 人使用 | 不建議 `16GB` 或 `256GB`；M4 Pro 的 CPU 與記憶體頻寬比較適合常跑 OCR 回歸 |
| Windows 10/11 工作站 | Intel Core i7/i9 或 AMD Ryzen 7/9、8 核以上、32GB RAM、1TB NVMe | 使用者端試跑、內部單機部署、需要 Windows 桌面操作 | 建議 Windows 11 Pro/Enterprise + WSL2 + Docker Desktop；BIOS/UEFI 必須開虛擬化 |
| Windows Server 主機 | 8 到 16 vCPU、32 到 64GB RAM、512GB 到 1TB SSD | 公司既有 Windows Server 機房 | 不建議直接把 Docker Desktop 當正式服務；建議在 Hyper-V/VMware 上跑 Ubuntu VM，再於 VM 內用 Docker Engine 部署 |
| Linux Server / OCI | 8 vCPU、32GB RAM、512GB SSD 起；長期主力建議 12+ vCPU、64GB RAM、1TB SSD | 正式內網服務、OCI VM、長時間常駐 | 最推薦的正式部署型態；x86_64 與 ARM64 都可，CPU-only OCR 速度取決於核心數與單核效能 |

Apple 官方 Mac mini 規格目前顯示：M4 為 10 核 CPU、120GB/s 記憶體頻寬；M4 Pro 為 12 核 CPU、273GB/s 記憶體頻寬，並提供 Thunderbolt 5。官方規格與購買頁可參考：<https://www.apple.com/mac-mini/specs/>、<https://www.apple.com/shop/buy-mac/mac-mini>

## 開發與測試

### 後端

正式服務依賴：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

測試依賴另外安裝，避免把 pytest 放進正式 runtime image：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest
```

### 前端

```bash
cd frontend
npm ci
npm run dev
```

檢查：

```bash
npm run lint
npm run build
```

## 專業詞彙中英對照

| 中文 | English | 白話說明 |
|------|---------|----------|
| 差異比對 | Diff / Difference Comparison | 找出兩份文件哪裡不一樣 |
| 解析器 | Parser | 把 PDF 內容拆成文字、表格、圖片與座標的工具 |
| 光學字元辨識 | OCR, Optical Character Recognition | 從圖片或掃描頁面讀出文字 |
| 座標框 | Bounding Box, BBox | PDF 上某段文字或表格的位置範圍 |
| 結構化資料 | Structured Data | 讓程式能理解的文字、表格、頁碼、座標資料 |
| 備援 | Fallback | 主要方法失敗時，自動改用下一個方法 |
| 雜湊 | Hash | 用一串固定長度的值代表檔案內容，常用來判斷檔案是否相同 |
| 封存 | Archive | 保存當時的 PDF、審核結果與核驗紀錄 |
| 核驗歷史 | Verification History | 每次留存與審核狀態的歷史紀錄 |
| 感知雜湊 | Perceptual Hash, pHash | 用來判斷圖片看起來是否相似 |
| 結構相似度 | SSIM, Structural Similarity | 比較兩張圖片結構是否相似的方法 |
| 正規化相關係數 | NCC, Normalized Cross-Correlation | 用來比對小區域影像是否相似 |
| WebSocket | WebSocket | 讓前端即時收到比對進度 |
| REST API | REST API | 前端呼叫後端功能的 HTTP 介面 |
| Runtime | Runtime | 系統執行時產生與使用的資料，例如上傳檔、資料庫、匯出檔 |
| CI | Continuous Integration | 自動跑測試與檢查的流程 |

## 套件與資料來源

### 後端套件

| 套件 | 版本設定 | 用途 | 為什麼使用 | 來源 |
|------|----------|------|------------|------|
| FastAPI | `>=0.110` | 後端 API 框架 | 開發速度快，內建 OpenAPI 文件，適合檔案上傳、背景任務與審核 API | https://fastapi.tiangolo.com |
| Uvicorn | `>=0.27` | 執行 FastAPI 的 ASGI server | 支援非同步請求與 WebSocket，讓比對進度可以即時回傳前端 | https://www.uvicorn.org |
| Pydantic | `>=2.6` | 資料驗證與型別模型 | 可在資料進出 API 時先檢查格式，降低錯誤資料寫入審核紀錄的風險 | https://docs.pydantic.dev |
| pydantic-settings | `>=2.2` | 從環境變數讀取設定 | 讓本機、Docker、OCI 可以用同一份程式搭配不同設定部署 | https://docs.pydantic.dev/latest/concepts/pydantic_settings |
| python-multipart | `>=0.0.9` | 接收 PDF 上傳表單 | FastAPI 接收 PDF 檔案上傳時需要它解析 multipart form data | https://github.com/Kludex/python-multipart |
| Docling | `>=2.0` | 預設重型表格解析器 | 只在輕量快篩發現表格跡象時啟動，優先取得 cell-level bbox | https://github.com/docling-project/docling |
| pandas | `>=2.0` | 表格資料處理 | 表格差異需要逐列逐欄比較，pandas 適合處理這類結構化資料 | https://pandas.pydata.org |
| openpyxl | `>=3.1` | Excel 匯入與匯出 | 審核人員常用 Excel 檢視報表，也支援匯入核對清單 | https://openpyxl.readthedocs.io |
| PyMuPDF | `>=1.23` | PDF 讀取、渲染、標註匯出 | 可直接處理 PDF 頁面、座標與標註，是產生標註 PDF 的核心工具 | https://pymupdf.readthedocs.io |
| psutil | `>=5.9` | CPU/RAM 資源監控 | 可觀察比對期間硬體用量，協助評估推薦規格與穩定性 | https://github.com/giampaolo/psutil |
| imagehash | `>=4.3` | 圖片感知雜湊比對 | PDF 內有圖片或掃描區塊時，可偵測看起來相似但內容被改過的圖片 | https://github.com/JohannesBuchner/imagehash |
| requests | `>=2.31` | 呼叫 MinerU API | 後端需要把 PDF 傳給 MinerU 容器，並取回解析結果 | https://requests.readthedocs.io |
| lxml | `>=4.9` | 解析 HTML 表格 | MinerU 可能回傳 HTML 表格，lxml 可正確處理 rowspan/colspan 等複雜表格 | https://lxml.de |
| pytest | `>=9.0.3,<10` | 測試工具，只放在開發/CI 環境 | 用來確認差異比對、匯出與資料留存沒有被改壞；不放入正式 runtime image | https://pytest.org |

### 前端套件

| 套件 | 版本設定 | 用途 | 為什麼使用 | 來源 |
|------|----------|------|------------|------|
| React | `^19.2.4` | 前端 UI | 適合建立互動式審核畫面，例如差異列表、PDF 檢視器、彈窗與搜尋 | https://react.dev |
| React DOM | `^19.2.4` | 將 React 畫到瀏覽器 | React 網頁應用的必要執行層 | https://react.dev |
| React Router | `^7.14.0` | 頁面路由 | 讓登入、上傳、比對、帳號管理等頁面清楚分開 | https://reactrouter.com |
| React PDF | `^10.4.1` | 在瀏覽器顯示 PDF | 可把 PDF 頁面渲染到網頁上，讓差異標記能直接疊在文件上 | https://github.com/wojtekmaj/react-pdf |
| react-zoom-pan-pinch | `^4.0.3` | PDF 縮放與拖曳 | 審核細小文字或表格時，需要穩定的縮放與平移操作 | https://github.com/BetterTyped/react-zoom-pan-pinch |
| Zustand | `^5.0.12` | 前端狀態管理 | 比 Redux 輕量，足以管理目前差異、頁面、搜尋與審核狀態 | https://zustand-demo.pmnd.rs |
| Axios | `^1.15.0` | 呼叫後端 API | 支援一般 JSON 請求與 Blob 檔案下載，適合匯出 PDF/Excel | https://axios-http.com |
| Tailwind CSS | `^3.4.0` | 前端樣式 | 用一致的工具類別快速維持表單、按鈕、列表與工具列樣式 | https://tailwindcss.com |
| Lucide React | `^1.8.0` | 圖示 | 圖示風格一致，讓返回、下載、搜尋、設定等操作更容易辨識 | https://lucide.dev |
| Vite | `^8.0.4` | 前端開發與打包 | 啟動快、打包快，適合 React 專案日常開發與正式部署 | https://vite.dev |
| TypeScript | `~6.0.2` | 型別檢查 | 可提早發現 API 欄位、元件 props、狀態資料不一致的問題 | https://www.typescriptlang.org |
| ESLint | `^9.39.4` | 程式碼檢查 | 幫助維持程式碼品質，避免常見 React Hooks 與未使用變數問題 | https://eslint.org |

### 解析模型與系統工具

| 名稱 | 用途 | 為什麼使用 | 來源 |
|------|------|------------|------|
| MinerU | 複雜表格與可選影像 OCR fallback | Docling 無有效表格或啟用影像召回時使用，避免平常常駐重複運算 | https://github.com/opendatalab/MinerU |
| ModelScope model cache | MinerU 模型快取來源之一 | 模型下載後快取，可避免每次重建都重新下載大型模型 | https://www.modelscope.cn |
| Hugging Face cache | 部分 Python/模型工具可能使用的模型快取路徑 | 保留常見模型快取位置，方便未來擴充或備援工具使用 | https://huggingface.co |
| Tesseract OCR | 圖片文字辨識 | 當文字藏在圖片或掃描區塊時，可協助讀出圖片中的字 | https://github.com/tesseract-ocr/tesseract |
| PaddleOCR | 實驗性第二 OCR 引擎 | 本機/內網 OCR 候選來源，不需外部 API Token；第一階段只做 A/B metadata，不直接改正式差異 | https://github.com/PaddlePaddle/PaddleOCR |
| Poppler | PDF 工具組，提供部分 PDF 處理能力 | 是許多 PDF 工具常用底層元件，可補足 PDF 轉換與處理能力 | https://poppler.freedesktop.org |
| SQLite | 本地資料庫 | 不需額外架資料庫服務，適合單機部署並保存審核與封存紀錄 | https://www.sqlite.org |
| Docker | 容器化部署 | 把後端、前端與 MinerU 包在固定環境，降低不同電腦部署差異 | https://www.docker.com |

## 下一步優化方向

原則：準確率最重要。速度與省資源的優化，不能讓差異辨識能力下降；若有取捨，應保留可開關設定，讓管理者依文件類型選擇。

### 目前 PDF 比對狀態

截至 2026-06-28，影像型商品 DM 已完成架構修正、CPU-only 解析路由優化與一輪全 PDF Docker 回歸；完整技術現況見 `docs/technical-usage-status_2026-06-28.md`，逐案結果見 `docs/full_pdf_regression_2026-06-28.md`。

| 項目 | 目前做法 |
|------|----------|
| 大表格或大版面差異 | 不再靜默壓掉，會以「表格/版面」項目進正式清單，讓審核人員可點開截圖確認 |
| OCR 文字 | 只保留短數字、頁首/頁尾 Control No/version、可信文字；長段低可信 OCR 會被壓掉，避免亂碼誤報 |
| 效能 | 2026-06-28 冷快取回歸共 60 頁；模型載入後的 54 頁觀察值約 6.40 秒/頁、9.38 頁/分鐘。首份冷啟動開始時間未記錄，不宣稱整批精確耗時 |
| 表格數字 | P0 先保留表格區域可審核證據；逐格表格 OCR/欄列對齊仍屬下一階段 |
| 固定回歸 | 鳳守愛、慈愛微型、新扶愛、美保發、美利保、臻美利六組 `商品DM/` 已跑過 Docker 回歸 |

### 優先做：讓準確率可量測

| 優先 | 建議 | 為什麼 |
|------|------|--------|
| P0 | 建立黃金測試集 | 收集真實保險 DM、條款、費率表，人工標出正確差異，之後每次改程式都能檢查有沒有漏報 |
| P0 | 加入準確率報表 | 記錄命中、漏報、誤報、頁碼錯誤、座標偏移，讓「比較準」變成可量化指標 |
| P0 | 保存解析中介資料 | 留下 MinerU/Docling 解析出的文字、表格、座標，方便追查為什麼某筆差異有抓到或沒抓到 |
| P0 | 建立疑難 PDF 回歸測試 | 把曾經抓不準的案例固定成測試樣本，避免之後優化速度時不小心讓準確率倒退 |
| P1 | 對審核結果做回饋學習 | 人工標成誤判或異常的紀錄，可用來調整門檻與規則 |
| P1 | 強化表格欄列對齊 | 保險文件常改費率表，表格準確率會直接影響整體可信度 |

### 再做：更快，但不犧牲準確

| 優先 | 建議 | 為什麼 |
|------|------|--------|
| 已完成 | 依 PDF hash 快取解析結果 | 使用 SHA-256 bounded cache + single-flight，同一份 PDF 不重複解析 |
| 已完成 | 先做頁級變更偵測 | 72 DPI 快掃先找變更頁，再對候選頁執行 144／200 DPI 分期分析 |
| P1 | 把 snapshot 改成可控產生 | 預設可只在留存或匯出時產生，降低平常比對的等待時間 |
| 已完成（程序內） | 對大 PDF 做有限任務佇列 | `COMPARE_MAX_CONCURRENCY` + `COMPARE_MAX_PENDING_TASKS` 限制執行與等待數；若需跨重啟復原，再升級外部持久化佇列 |
| 已完成 | 前端延遲載入重型元件 | 只有進入比對頁才載入 PDF runtime，首頁維持快速開啟 |

### 同步做：更省資源

| 優先 | 建議 | 為什麼 |
|------|------|--------|
| P0 | 正式 runtime 移除測試工具 | `pytest` 只放 `requirements-dev.txt`，降低正式容器套件數與資安掃描噪音 |
| P0 | 補齊 `.dockerignore` | 排除 `.venv`、runtime、dist、node_modules，避免 Docker build context 從 KB 變成 GB |
| 已完成 | 重型表格引擎改為可回退的循序路由 | 預設 Docling → MinerU，避免兩個都跑但只採用其中一份結果 |
| 已完成 | 只對疑似圖片差異跑 OCR | 初步保留視覺候選；完整階段只對變更 ROI 與保護區域做 OCR |
| P1 | 只保存必要 snapshot | 有差異頁優先保存，完整快照改成使用者需要時再產生 |
| 已完成 | 建立資源用量儀表 | 基準記錄每次任務頁數、分階段耗時、CPU、RAM 與快取命中 |
| 已完成（CPU） | 固定 CPU-only Torch | 正式 CPU 映像使用 `torch==2.12.1+cpu`，禁止把 CUDA wheel 帶進 OCI；GPU 另用獨立 profile 評估 |

### 建議執行順序

1. 先做黃金測試集與準確率報表。
2. 補齊疑難 PDF 回歸測試，避免辨識能力倒退。
3. 再做 PDF hash 解析快取。
4. 以正式基準守住頁級變更偵測與 ROI OCR，不讓速度優化犧牲初步區域召回。
5. 將黃金集擴充至 30 對，再決定是否加入 GPU／VLM profile。

## 專案結構

```text
backend/                  後端 API、PDF 解析、比對、匯出、資料庫
frontend/                 前端畫面
mineru/                   MinerU API 容器設定
docs/                     深入技術文件
samples/                  測試或範例檔案
docker-compose.yml        本機或伺服器部署設定
.dockerignore             Docker build 排除清單，避免把本機快取與測試環境打包
start-mac.command         macOS 一鍵啟動
stop-mac.command          macOS 一鍵停止
一鍵啟動PDF比對系統.bat    Windows 一鍵啟動
一鍵停止PDF比對系統.bat    Windows 一鍵停止
```

## 更多文件

- 開發手冊：`docs/dev-handbook.md`
- 技術架構：`docs/technical-architecture.md`
- 技術使用現況：`docs/technical-usage-status_2026-06-28.md`
- 效能量測：`docs/performance-benchmark.md`
- 2026-06-28 全 PDF 回歸：`docs/full_pdf_regression_2026-06-28.md`
- 影像型 PDF 回歸 Runbook：`docs/recall-regression-runbook.md`
- 商品 DM OCR A/B 紀錄：`docs/image_text_recall_strategy_ab_2026-05-26.md`
- Docker 快速啟動：`DEPLOY.md`
