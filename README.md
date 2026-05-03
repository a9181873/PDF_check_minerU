# PDF Check

保險 EDM / PDF 差異比對系統。專案由 `FastAPI + MinerU + Docling + React + react-pdf + SQLite` 組成，目標是把「新舊 PDF 的文字與數字差異」轉成可審核、可搜尋、可匯出的工作流，而不是做像素級美術比對。

## 專案目標

- 上傳舊版與新版 PDF，建立一筆比較任務
- 以 MinerU（主）或 Docling（備援）解析文字區塊與表格位置，產生結構化中介資料
- 用段落級 diff 比對出新增、刪除、文字修改、數值修改
- 表格支援 **cell-level diff**：精確標記到單一儲存格，整表大幅變動時自動聚合為一筆整表替換
- 在前端灰階 PDF 上疊加彩色標記，協助審核
- 提供 Markdown、標註 PDF、Excel 等匯出能力
- 透過 WebSocket 回報背景任務進度

## 系統架構

```text
Browser
  ├─ UploadPage: 上傳 PDF、建立任務
  ├─ ComparePage: 差異檢視、搜尋、核對清單、匯出
  └─ react-pdf/pdf.js: PDF 渲染與座標對位
        │
        ├─ REST API (/api/*)
        └─ WebSocket (/ws/compare/{task_id})
              │
FastAPI
  ├─ routes_auth.py: 帳號登入、使用者管理 (JWT)
  ├─ routes_compare.py: 任務建立、狀態查詢、結果與 PDF/Markdown 下載
  ├─ routes_review.py: 差異審核與摘要
  ├─ routes_checklist.py: 核對清單匯入與更新
  ├─ routes_export.py: 匯出標註 PDF / Excel / TXT
  ├─ routes_project.py: 專案列表與比較歷史
  └─ websocket.py: 即時進度推播
        │
Services
  ├─ parser_service.py: MinerU（主）/ Docling / PyMuPDF / pdftotext fallback 鏈
  ├─ diff_service.py: 段落 diff、cell-level 表格 diff（含70%聚合策略）
  ├─ checklist_service.py: CSV/Excel 匯入與自動匹配
  ├─ export_service.py: PDF / Excel 匯出
  └─ coord_transformer.py: PDF 座標轉換工具
        │
MinerU API (獨立容器)
  └─ mineru-api:18080  pipeline backend（100% 地端，繁體中文優化）
        │
Persistence
  ├─ SQLite: projects / comparisons / review_logs / users
  ├─ uploads: 原始 PDF
  ├─ exports: 匯出物與 markdown
  └─ TASK_STORE / CHECKLIST_STORE: 執行中任務與暫時記憶體狀態
```

## 技術棧

### Backend

- `FastAPI`: API 與靜態檔服務
- `uvicorn`: ASGI server
- **`MinerU 3.x`**: 高精度 PDF 結構化解析（主要解析器，cell-level 表格、繁體中文優化）
- `docling`: PDF 解析備援（MinerU 不可用時自動切換）
- `pandas` / `openpyxl`: 表格與 checklist 匯入 / 匯出
- `PyMuPDF`: PDF fallback 解析與標註匯出
- `sqlite3`: 比較結果與審核紀錄
- `pytest`: 單元測試

### MinerU 服務

- 獨立 Docker 容器（`mineru-api:pipeline`），透過 REST API 提供服務
- 使用 `pipeline` backend，100% 離線，模型存於 Docker volume
- 設定 `lang_list=chinese_cht` 確保繁體中文輸出正確
- Backend 透過環境變數 `MINERU_API_URL` 連接，未設定時自動回退至 Docling

### Frontend

- `React 19`
- `React Router 7`
- `Vite 8`
- `react-pdf`
- `Zustand`
- `Tailwind CSS`
- `Axios`
- `lucide-react`

## 目前功能範圍

### 已完成

- PDF 上傳與背景比對任務
- WebSocket 進度更新
- Diff 結果查詢
- 差異搜尋與定位
- 灰階 PDF + 彩色疊圖標註
- 核對清單匯入與人工更新
- Markdown 匯出
- 標註 PDF 匯出
- Excel 審核報表匯出
- 審核紀錄 TXT 匯出（人類可讀格式）
- 專案列表與比較紀錄查詢（含搜尋與列表呈現）
- Docker 與一鍵啟動腳本
- 前端 route-level 與 component-level code-splitting
- **帳號密碼管理機制** — JWT 認證、登入頁面、帳號管理頁面、審核自動帶入帳號
- **響應式 DiffPopup** — 內容修改框依瀏覽器解析度自適應，底部按鈕永遠可見
- **四路聯集比對引擎** — 整合文字、表格、像素、嵌入圖片 (pHash) 的全方位比對
- **零漏報優化 (Zero-Miss Tuning)** — 調降像素門檻 (15) 與面積 (200 px)，提高 NCC (0.98) 嚴格度，確保人為修改無所遁形
- **專案設定審核人員** — 在上傳頁面即時顯示當前審核者，並記錄至審核日誌中

### 目前限制

- checklist 會持久化到 SQLite，但 `CHECKLIST_STORE` 仍保留作為執行中快取
- 審核 summary 以每個 `diff_item_id` 最新一筆 `review_logs` 為準
- 若本機開發未指定 `DATA_DIR`，建議明確設定 runtime 路徑
- MinerU cell bbox 目前由整表 bbox 推算（MinerU API 不提供單格座標），前端標記精確到整格欄位而非像素

## 目錄結構

```text
PDF_check/
├── backend/
│   ├── api/
│   ├── models/
│   ├── services/
│   ├── tests/
│   ├── scripts/
│   ├── main.py
│   ├── config.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/
│   │   ├── stores/
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
├── docs/
├── samples/
├── scripts/
├── docker-compose.yml
├── 一鍵啟動PDF比對系統.command
├── 一鍵停止PDF比對系統.command
├── 一鍵啟動PDF比對系統.bat
└── 一鍵停止PDF比對系統.bat
```

## 啟動方式

### 一鍵啟動 / 停止

- **Windows啟動**: 雙擊 `一鍵啟動PDF比對系統.bat`
- **Windows停止**: 雙擊 `一鍵停止PDF比對系統.bat`
- **macOS啟動**: 雙擊 `一鍵啟動PDF比對系統.command`
- **macOS停止**: 雙擊 `一鍵停止PDF比對系統.command`

啟動腳本會先檢查 Docker 是否存在與是否啟動，再執行 `docker compose up -d`，接著輪詢確認服務可用後才自動開啟畫面。

### Docker 啟動

```bash
cd /path/to/PDF_check
docker compose up --build -d
```

首次 build 時 MinerU image 會自動下載 pipeline 模型（約 5-8GB），之後模型快取在 `mineru_model_cache` volume，重建不需重複下載。

啟動後：

- 前端入口: `http://localhost:8000`
- API 基底: `http://localhost:8000/api`
- 健康檢查: `http://localhost:8000/health`
- MinerU API（內網）: `http://mineru-api:18080`（僅 backend 可存取）

停止：

```bash
docker compose down
```

### 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `MINERU_API_URL` | `http://mineru-api:18080` | MinerU REST API 位址；空值 = 停用 MinerU，回退至 Docling |
| `DATA_DIR` | `/app/runtime` | Runtime 資料目錄 |
| `OCR_LANGS` | `chi_tra+chi_sim+eng` | Docling OCR 語言（備援用） |
| `DEBUG` | `false` | 開啟 debug 模式 |

## 本機開發

### Backend

```bash
cd /path/to/PDF_check/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATA_DIR=/path/to/PDF_check/runtime
# 可選：指向本機執行中的 MinerU，留空則退回 Docling
export MINERU_API_URL=http://localhost:18080
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

若不啟動 MinerU 容器，省略 `MINERU_API_URL` 即可，解析器自動退回 Docling。

### Frontend

```bash
cd /path/to/PDF_check/frontend
npm ci
npm run dev
```

Vite 已設定 proxy：

- `/api` -> `http://localhost:8000`
- `/ws` -> `ws://localhost:8000`
- `/health` -> `http://localhost:8000`

## 推薦硬體規格

導入 MinerU 後，解析精度顯著提升（cell-level 表格），但對記憶體需求也相應增加。

### MinerU POC 實測（macOS M 系列 CPU）

| 檔案 | 大小 | 耗時 | 記憶體增量 | 表格數 |
|------|------|------|-----------|--------|
| 金利樂.pdf | 3.1MB | ~17s | +2.2GB | 5 |
| 臻鑽旺旺.pdf | 6.5MB | ~15s | +0.3GB（已快取）| 4 |

### 建議規格（3–5 人共用）

| 等級 | 規格 | 適用情境 |
|------|------|----------|
| 最低可用 | 8 核心 CPU / **16GB RAM** / SSD | 1-2 人輕度使用 |
| **建議（3–5 人）** | **12 核心以上 CPU / 32GB RAM / SSD** | 日常並發 2-3 任務 |
| 高效部署 | 16 核心 / 64GB RAM / NVMe SSD | 4-5 人並發 + 大型 DM |

### 補充

- MinerU 首次啟動需載入 pipeline 模型（約 3-5GB），之後保持常駐
- Docker volume `mineru_model_cache` 儲存模型，避免每次重建重複下載
- 磁碟需求：建議預留 **30GB 以上**（含模型快取 ~5-8GB + runtime）
- GPU 非必要，但若配備 CUDA GPU（8GB+ VRAM）可顯著加速大型 PDF 解析

## 核心資料流

### 1. 上傳與任務建立

前端呼叫：

- `POST /api/compare/upload`

表單欄位：

- `old_pdf`
- `new_pdf`
- `project_id` 可選

後端會：

- 檢查副檔名是否為 PDF
- 在 `uploads/old` 與 `uploads/new` 寫入原始檔
- 建立 `comparisons` 資料列
- 建立 `TASK_STORE` 任務狀態
- 用 `BackgroundTasks` 進入解析與 diff 流程

### 2. 解析流程

`backend/services/parser_service.py` 採多層 fallback 鏈：

1. **MinerU**（預設，若 `MINERU_API_URL` 已設定）— REST API 呼叫，`pipeline` backend，`lang_list=chinese_cht`
2. `Docling`（MinerU 不可用時自動切換）
3. `PyMuPDF`
4. `pdftotext`

MinerU 輸出 `content_list`（JSON）包含每個文字區塊與表格的座標（top-left origin）；系統自動轉換為底部原點座標以統一後續處理。表格輸出含完整 rowspan/colspan HTML，解析為 DataFrame 後存入 `ParsedTable`。

輸出中介資料型別：

- `ParsedDocument`
- `ParsedParagraph`
- `ParsedTable`（含 `cell_bboxes` 若 Docling 路徑）
- `BBox`

所有 bbox 會標準化為 PDF bottom-left 座標系，方便後端匯出與前端疊圖共用。

### 3. Diff 流程

`backend/services/diff_service.py` 包含段落 diff 與 **cell-level 表格 diff**：

- 先正規化段落文字（NFKC + 去除零寬字元）
- 用 `SequenceMatcher` 比較 old/new 段落序列
- `replace` 時再做逐段配對
- 透過 regex 判斷是否含數值，分成 `number_modified` 與 `text_modified`
- `insert/delete` 轉成 `added/deleted`
- **Cell-level 表格 diff**：逐格比較 DataFrame，產生精確到儲存格的 `DiffItem`
- **70% 聚合策略**：若變更格數 ≥ 70% 則合併為一筆「整表替換」diff，避免 UI 被百筆小 diff 淹沒
- **嵌入圖片比對**：利用 PyMuPDF 提取圖片並計算 pHash (感知哈希)，偵測圖片替換、尺寸變更或內容微調
- 最後依頁碼與座標排序並編成 `d001`, `d002`, ...
- **聯集策略**：文字 diff + 表格 diff + 像素 diff + 圖片 diff 取聯集，確保無遺漏任何變更

### 4. 前端渲染

前端比對頁由 `frontend/src/pages/ComparePage.tsx` 驅動：

- `SearchBar` 提供搜尋與差異列表
- `SyncScrollContainer` 控制雙欄同步滾動
- `PDFViewer` 用 `react-pdf` 顯示 PDF
- `DiffOverlay` 把 diff bbox 疊在當前頁
- `DiffPopup` 處理審核與標記問題
- `ChecklistPanel` / `ChecklistUpload` 處理核對清單

目前已做兩層 code-splitting：

- 路由層: `UploadPage` / `ComparePage`
- 元件層: `PDFViewer` / `ChecklistUpload` / `DiffPopup`

這樣首頁不會先載入 PDF runtime，只有進入比對頁才會載入 `react-pdf` 與 `pdfjs`。

## API 摘要

### Compare

- `POST /api/compare/upload`
- `GET /api/compare/{task_id}/status`
- `GET /api/compare/{task_id}/result`
- `GET /api/compare/{task_id}/markdown`
- `GET /api/compare/{task_id}/markdown/{old|new}`
- `GET /api/compare/{task_id}/pdf/{old|new}`
- `WS /ws/compare/{task_id}`

### Review

- `POST /api/review/{comparison_id}/confirm`
- `GET /api/review/{comparison_id}/summary`

### Checklist

- `POST /api/checklist/{comparison_id}/import`
- `GET /api/checklist/{comparison_id}`
- `PATCH /api/checklist/{comparison_id}/{item_id}`

### Export

- `GET /api/export/{comparison_id}/pdf`
- `GET /api/export/{comparison_id}/excel`
- `GET /api/export/{comparison_id}/report`
- `GET /api/export/{comparison_id}/log`
- `GET /api/export/{comparison_id}/log-csv`
- `GET /api/export/{comparison_id}/log-txt` ← 新增

### Project

- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{project_id}/comparisons`

### Auth (新增)

- `POST /api/auth/login` — 帳號密碼登入
- `GET /api/auth/me` — 取得登入使用者資訊
- `GET /api/auth/users` — 列出所有帳號 (admin)
- `POST /api/auth/users` — 建立帳號 (admin)
- `PUT /api/auth/users/{id}` — 修改帳號 (admin)
- `DELETE /api/auth/users/{id}` — 刪除帳號 (admin)

## 資料儲存

### SQLite

由 `backend/models/database.py` 建立並維護：

- `projects`
- `comparisons`
- `review_logs`
- `checklists`
- `users` — 帳號密碼管理 (pbkdf2 雜湊)

實際上目前：

- `projects`, `comparisons`, `review_logs`, `checklists` 都會寫入 SQLite
- `CHECKLIST_STORE` 仍保留為記憶體快取，避免重複 decode 與提升 API 回應速度

### Runtime 檔案

典型目錄：

- `runtime/uploads/old`
- `runtime/uploads/new`
- `runtime/exports`
- `runtime/exports/markdown`
- `runtime/app.db`

Docker compose 會把這些資料掛進 volume，避免容器重啟後消失。

## 匯出能力

`backend/services/export_service.py` 提供：

- 標註 PDF
  - 在新版 PDF 上以彩色矩形標示 bbox
  - annotation note 寫入 diff 類型與 old/new 值
- Excel 報表
  - `diffs` 工作表
  - `checklist` 工作表
  - `summary` 工作表
- Review Report PDF
  - comparison 摘要
  - diff 統計
  - checklist 統計
  - diff / checklist 細項清單
- Review Log JSON
  - 完整 diff / checklist / review_logs 原始資料
  - 適合留存、串接、技術追查
- Review Log CSV
  - 每筆審核動作一列
  - 補上 diff 內容與 matched checklist item
  - 適合直接開 Excel 檢視

## 驗證方式

### Frontend

```bash
cd /path/to/PDF_check/frontend
npm run build
npm run lint
```

### Backend

```bash
cd /path/to/PDF_check/backend
pytest
```

目前測試覆蓋：

- diff 邏輯
- markdown 產出
- 座標轉換

## 文件索引

- 開發手冊: `docs/dev-handbook.md`
- Docker 快速啟動: `docs/docker-quickstart.md`
- 效能量測: `docs/performance-benchmark.md`
