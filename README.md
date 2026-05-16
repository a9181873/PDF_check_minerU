# PDF Check MinerU

PDF Check MinerU 是一套用來比對「舊版 PDF」與「新版 PDF」差異的本地端審核工具。它會把 PDF 解析成文字、表格和位置資訊，再把新增、刪除、文字修改、數字修改標在畫面上，讓審核人員可以逐筆確認、留下紀錄，最後匯出報告或封存。

這個專案特別適合保險 DM、條款、費率表、簡章、公告等需要反覆改版與人工審核的 PDF。

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
- 使用 MinerU 優先解析 PDF，Docling 作為備援

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

第一次啟動會下載 MinerU 模型，檔案較大，可能需要一段時間。模型會存在 Docker volume 裡，之後重建通常不用重新下載。

## 初次登入

系統第一次啟動時會建立 `admin` 管理者帳號。

密碼來源：

- 若有設定 `DEFAULT_ADMIN_PASSWORD`，就使用該密碼。
- 若沒有設定，系統會自動產生密碼並寫入 runtime 目錄的 `.initial_admin_password`。

第一次登入後，建議立刻到帳號管理頁修改密碼，並刪除 `.initial_admin_password`。

Docker 環境可用以下方式讀取初始密碼：

```bash
docker exec pdf-check-minerU cat /app/runtime/.initial_admin_password
```

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
| `MINERU_API_URL` | `http://mineru-api-minerU:18080` | MinerU 解析服務位置 |
| `DATA_DIR` | `/app/runtime` | 上傳檔案、資料庫、匯出檔案存放位置 |
| `OCR_LANGS` | `chi_tra+chi_sim+eng` | OCR 使用繁中、簡中與英文 |
| `ENABLE_DOCLING_PARALLEL` | `false` | 是否同時跑 Docling；預設關閉以節省 CPU/RAM |
| `MINERU_PREFERRED_WAIT_SECONDS` | `30` | 若開啟並行解析，優先等待 MinerU 的秒數 |
| `GENERATE_SNAPSHOTS` | `true` | 比對完成後是否產生頁面快照 |
| `SNAPSHOT_DIFF_PAGES_ONLY` | `true` | 只為有差異的頁面產生快照 |
| `JWT_SECRET` | 自動產生 | 登入 token 加密用密鑰 |
| `DEFAULT_ADMIN_PASSWORD` | 空 | 初始 admin 密碼，建議正式部署時自行設定 |

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

以 1 到 3 人同時使用作為一般情境。

| 情境 | 建議規格 |
|------|----------|
| 輕量測試 | 4 核 CPU、16GB RAM、100GB SSD |
| 1 到 3 人穩定使用 | 4 到 8 核 CPU、24GB RAM、200GB 以上 SSD |
| 較大 PDF 或多人同時使用 | 8 核以上 CPU、32GB RAM、512GB 以上 SSD |

說明：

- MinerU 模型較吃記憶體。
- PDF 頁數多、圖片多、表格多時，CPU 和 RAM 需求會上升。
- GPU 不是必要，但若部署環境支援 CUDA，MinerU 解析速度通常會更好。

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
| Docling | `>=2.0` | PDF 解析備援 | MinerU 不可用時仍能解析 PDF，避免服務完全中斷 | https://github.com/docling-project/docling |
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
| MinerU | 主要 PDF 解析器，輸出文字、表格與版面資訊 | 對複雜 PDF、中文文件與表格解析較適合，是目前準確率優先的主解析器 | https://github.com/opendatalab/MinerU |
| ModelScope model cache | MinerU 模型快取來源之一 | 模型下載後快取，可避免每次重建都重新下載大型模型 | https://www.modelscope.cn |
| Hugging Face cache | 部分 Python/模型工具可能使用的模型快取路徑 | 保留常見模型快取位置，方便未來擴充或備援工具使用 | https://huggingface.co |
| Tesseract OCR | 圖片文字辨識 | 當文字藏在圖片或掃描區塊時，可協助讀出圖片中的字 | https://github.com/tesseract-ocr/tesseract |
| Poppler | PDF 工具組，提供部分 PDF 處理能力 | 是許多 PDF 工具常用底層元件，可補足 PDF 轉換與處理能力 | https://poppler.freedesktop.org |
| SQLite | 本地資料庫 | 不需額外架資料庫服務，適合單機部署並保存審核與封存紀錄 | https://www.sqlite.org |
| Docker | 容器化部署 | 把後端、前端與 MinerU 包在固定環境，降低不同電腦部署差異 | https://www.docker.com |

## 下一步優化方向

原則：準確率最重要。速度與省資源的優化，不能讓差異辨識能力下降；若有取捨，應保留可開關設定，讓管理者依文件類型選擇。

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
| P1 | 依 PDF hash 快取解析結果 | 同一份 PDF 被重複比對時，不必重新解析，可大幅節省時間 |
| P1 | 先做頁級變更偵測 | 先判斷哪些頁可能有變，再把重型 OCR/SSIM 放到可疑頁面 |
| P1 | 把 snapshot 改成可控產生 | 預設可只在留存或匯出時產生，降低平常比對的等待時間 |
| P2 | 對大 PDF 做任務佇列 | 限制同時解析數，避免多人同時使用時互相搶 CPU/RAM |
| P2 | 前端延遲載入重型元件 | 只有進入比對頁才載入 PDF runtime，首頁維持快速開啟 |

### 同步做：更省資源

| 優先 | 建議 | 為什麼 |
|------|------|--------|
| P0 | 正式 runtime 移除測試工具 | `pytest` 只放 `requirements-dev.txt`，降低正式容器套件數與資安掃描噪音 |
| P0 | 補齊 `.dockerignore` | 排除 `.venv`、runtime、dist、node_modules，避免 Docker build context 從 KB 變成 GB |
| P1 | 預設 MinerU 優先、Docling 備援 | 避免每次都同時跑兩套解析器，節省 CPU/RAM；遇到疑難文件再開並行 |
| P1 | 只對疑似圖片差異跑 OCR | OCR 成本高，集中在必要區域可省資源 |
| P1 | 只保存必要 snapshot | 有差異頁優先保存，完整快照改成使用者需要時再產生 |
| P2 | 建立資源用量儀表 | 長期記錄每次任務的頁數、耗時、CPU、RAM，作為硬體規格調整依據 |
| P2 | 規劃 CPU-only / GPU profile | 目前保留 Torch/CUDA 相關依賴，方便未來 GPU 機器使用；若要做 CPU-only 精簡版，需先確認準確率不受影響 |

### 建議執行順序

1. 先做黃金測試集與準確率報表。
2. 補齊疑難 PDF 回歸測試，避免辨識能力倒退。
3. 再做 PDF hash 解析快取。
4. 接著做頁級變更偵測，讓重型解析只跑在必要頁面。
5. 最後做任務佇列、資源儀表與 CPU-only/GPU profile 規劃，提升多人使用穩定性並保留未來 GPU 彈性。

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
- 效能量測：`docs/performance-benchmark.md`
- Docker 快速啟動：`DEPLOY.md`
