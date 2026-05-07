# PDF Check

保險 EDM / PDF 差異比對系統。專案由 `FastAPI + MinerU + Docling + React + react-pdf + SQLite` 組成，目標是把「新舊 PDF 的文字與數字差異」轉成可審核、可搜尋、可匯出的工作流，而不是做像素級美術比對。

> [!TIP]
> **最新更新 (2026-05-08)**: 核心比對引擎升級，導入 **SSIM 子區域變更定位** 與 **區域性 Tesseract OCR**，大幅提升圖片內文字變動（如：費率表、說明圖）的偵測精準度與自動讀取能力。

## 專案目標

- 上傳舊版與新版 PDF，建立一筆比較任務
- 以 MinerU（主）或 Docling（備援）解析文字區塊與表格位置，產生結構化中介資料
- 用段落級 diff 比對出新增、刪除、文字修改、數值修改
- 表格支援 **cell-level diff**：精確標記到單一儲存格，整表大幅變動時自動聚合為一筆整表替換
- 在前端灰階 PDF 上疊加彩色標記，協助審核
- 提供 Markdown、標註 PDF、Excel 等匯出能力
- 透過 WebSocket 回報背景任務進度
- **PDF 驗證封存**：比對完成後可封存版本紀錄，支援多次核驗歷史查詢

## 系統架構

```text
Browser
  ├─ UploadPage: 上傳 PDF、建立任務
  ├─ ComparePage: 差異檢視、搜尋、核對清單、匯出
  ├─ VerificationHistoryModal: 封存核驗歷史查詢
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
  ├─ routes_archive.py: PDF 封存與核驗歷史
  └─ websocket.py: 即時進度推播（含記憶體遺失 fallback）
        │
Services
  ├─ parser_service.py: MinerU（主）/ Docling / PyMuPDF / pdftotext fallback 鏈（並行解析優化）
  ├─ diff_service.py: 段落 diff、cell-level 表格 diff（含70%聚合策略）
  │    ├─ 像素比對：動態 DPI、Sliding Window NCC、自適應 NCC 門檻
  │    ├─ SSIM 子區域變更定位：精確找出圖片內文字修改位置
  │    └─ 鄰近差異合併邏輯
  ├─ archive_service.py: PDF SHA-256 雜湊、封存複製、核驗紀錄
  ├─ checklist_service.py: CSV/Excel 匯入與自動匹配
  ├─ export_service.py: PDF / Excel 匯出
  └─ coord_transformer.py: PDF 座標轉換工具
        │
MinerU API (獨立容器)
  └─ mineru-api:18080  pipeline backend（100% 地端，繁體中文優化）
        │
Persistence
  ├─ SQLite: projects / comparisons / review_logs / users / pdf_archives / verification_sessions
  ├─ uploads: 原始 PDF
  ├─ exports: 匯出物與 markdown
  ├─ archives: 封存 PDF（依 archive_id 子目錄）
  └─ TASK_STORE / CHECKLIST_STORE: 執行中任務與暫時記憶體狀態
```

## 技術棧

### Backend（Python 3.11+）

#### Web 框架 / Web Framework

| 套件 | 版本 | 中文說明 | English Description | 來源 |
|------|------|----------|---------------------|------|
| `fastapi` | ≥0.110 | 高效能非同步 REST API 框架，提供路由、依賴注入、自動產生 OpenAPI 文件 | High-performance async REST API framework with routing, dependency injection, and auto OpenAPI docs | [fastapi.tiangolo.com](https://fastapi.tiangolo.com) |
| `uvicorn` | ≥0.27 | ASGI server，負責運行 FastAPI 並支援 WebSocket 雙向通訊 | ASGI server that runs FastAPI and handles WebSocket connections | [github.com/encode/uvicorn](https://github.com/encode/uvicorn) |
| `pydantic` | ≥2.6 | 資料模型驗證與序列化，定義 `DiffItem`、`BBox` 等所有核心型別 | Data model validation and serialization; defines all core types like `DiffItem` and `BBox` | [docs.pydantic.dev](https://docs.pydantic.dev) |
| `pydantic-settings` | ≥2.2 | 從環境變數或 `.env` 安全載入設定（`MINERU_API_URL`、`DATA_DIR` 等） | Type-safe loading of settings from environment variables or `.env` files | [github.com/pydantic/pydantic-settings](https://github.com/pydantic/pydantic-settings) |
| `python-multipart` | ≥0.0.9 | 解析 `multipart/form-data` 上傳請求，讓 FastAPI 能接收 PDF 檔案 | Parses multipart/form-data upload requests so FastAPI can receive PDF files | [github.com/andrew-d/python-multipart](https://github.com/andrew-d/python-multipart) |

#### PDF 解析 / PDF Parsing

| 套件 | 版本 | 中文說明 | English Description | 來源 |
|------|------|----------|---------------------|------|
| `MinerU 3.x` | — | 主要解析器，以深度學習模型（DocLayout-YOLO）辨識版面並輸出結構化 JSON；cell-level 表格、繁體中文優化；透過 REST API 呼叫獨立 Docker 容器 | Primary parser using DL models (DocLayout-YOLO) to detect layout and export structured JSON; optimized for Traditional Chinese and table cells | [github.com/opendatalab/MinerU](https://github.com/opendatalab/MinerU) |
| `docling` | ≥2.0 | MinerU 不可用時的備援解析器，提供 `cell_bboxes` 精確儲存格座標 | Fallback parser when MinerU is unavailable; provides `cell_bboxes` for precise cell coordinates | [github.com/DS4SD/docling](https://github.com/DS4SD/docling) |
| `pymupdf` (fitz) | ≥1.23 | PDF 備援解析、像素渲染（`get_pixmap`）、標註 PDF 匯出（繪製彩色矩形）、嵌入圖片提取 | PDF fallback parsing, pixel rendering (`get_pixmap`), annotated PDF export (colored rectangles), embedded image extraction | [pymupdf.readthedocs.io](https://pymupdf.readthedocs.io) |
| `lxml` | ≥4.9 | 解析 MinerU 輸出的 HTML 表格（含 rowspan/colspan），轉換為 DataFrame | Parses MinerU's HTML table output (with rowspan/colspan) into DataFrames | [lxml.de](https://lxml.de) |

#### 影像分析 / Image Analysis

| 套件 | 版本 | 中文說明 | English Description | 來源 |
|------|------|----------|---------------------|------|
| `Pillow` | （pymupdf 依賴） | 圖片格式轉換、裁切、二值化預處理（供 Tesseract OCR 使用） | Image format conversion, cropping, and binarization preprocessing (for Tesseract OCR) | [python-pillow.org](https://python-pillow.org) |
| `imagehash` | ≥4.3 | 計算感知哈希（pHash），偵測 PDF 嵌入圖片的內容替換與微調 | Computes perceptual hash (pHash) to detect content changes in embedded PDF images | [github.com/JohannesBuchner/imagehash](https://github.com/JohannesBuchner/imagehash) |
| `numpy` | （依賴自動安裝） | 像素陣列運算，計算 NCC（正規化相關係數）與 SSIM（結構相似度） | Pixel array operations for NCC (Normalized Cross-Correlation) and SSIM (Structural Similarity) computation | [numpy.org](https://numpy.org) |
| `scipy` | （依賴自動安裝） | `ndimage.label` 連通元件分析（標記差異區域）、`uniform_filter`（SSIM 滑動窗口） | Connected component labeling for diff regions (`ndimage.label`), sliding window SSIM (`uniform_filter`) | [scipy.org](https://scipy.org) |
| `tesseract` | 系統安裝 | 開源 OCR 引擎，用於讀取光柵化圖片內的文字和數字（像素 diff fallback） | Open-source OCR engine for reading text and numbers inside rasterized images (pixel diff fallback) | [github.com/tesseract-ocr/tesseract](https://github.com/tesseract-ocr/tesseract) |

#### 資料處理 / Data Processing

| 套件 | 版本 | 中文說明 | English Description | 來源 |
|------|------|----------|---------------------|------|
| `pandas` | ≥2.0 | DataFrame 作為表格 diff 的比較單元；也用於 checklist CSV/Excel 讀寫 | DataFrame as comparison unit for table diff; also handles checklist CSV/Excel I/O | [pandas.pydata.org](https://pandas.pydata.org) |
| `openpyxl` | ≥3.1 | 產生多工作表 Excel 報表（diffs / checklist / summary）並匯入 checklist Excel 檔 | Generates multi-sheet Excel reports (diffs/checklist/summary) and imports checklist Excel files | [openpyxl.readthedocs.io](https://openpyxl.readthedocs.io) |
| `requests` | ≥2.31 | 呼叫 MinerU 容器 REST API（`POST /predict`），傳送 PDF 並取回結構化 JSON | Calls MinerU container REST API (`POST /predict`) to send PDFs and retrieve structured JSON | [docs.python-requests.org](https://docs.python-requests.org) |
| `psutil` | ≥5.9 | 即時監控 CPU 使用率、記憶體占用，提供系統資源狀態 API | Real-time CPU and memory usage monitoring for the system resource status API | [github.com/giampaolo/psutil](https://github.com/giampaolo/psutil) |
| `sqlite3` | 標準庫 | 儲存比較結果、審核紀錄、使用者帳號、PDF 封存與核驗歷史 | Stores comparison results, review logs, user accounts, PDF archives, and verification history | Python 標準庫 |
| `hashlib` | 標準庫 | 計算 SHA-256 用於 PDF 封存去重，相同版本組合不重複儲存 | Computes SHA-256 for PDF archive deduplication; identical version pairs are not stored twice | Python 標準庫 |

#### 測試 / Testing

| 套件 | 版本 | 中文說明 | English Description | 來源 |
|------|------|----------|---------------------|------|
| `pytest` | ≥8.0 | 單元測試框架，覆蓋 diff 邏輯、markdown 產出與座標轉換 | Unit test framework covering diff logic, markdown output, and coordinate transformation | [pytest.org](https://pytest.org) |

---

### MinerU 服務

[MinerU](https://github.com/opendatalab/MinerU) 是上海 AI Lab 開源的高精度文件解析引擎，以深度學習模型（DocLayout-YOLO、LayoutLMv3）辨識標題、段落、表格、公式、圖片等版面元素，並輸出帶座標的結構化 JSON。

在本系統中：

- 以獨立 Docker 容器（`mineru-api:pipeline`）執行，透過 REST API 提供服務
- 使用 `pipeline` backend，**100% 地端，無需聯網**，模型存於 Docker volume `mineru_model_cache`
- 設定 `lang_list=chinese_cht` 確保繁體中文輸出品質
- Backend 透過環境變數 `MINERU_API_URL` 連接，未設定時自動回退至 Docling

---

### Frontend（Node 20+）

#### UI 核心 / UI Core

| 套件 | 版本 | 中文說明 | English Description | 來源 |
|------|------|----------|---------------------|------|
| `react` | ^19.2.4 | 宣告式 UI 函式庫，所有元件以函式元件 + Hooks 撰寫 | Declarative UI library; all components use function components and Hooks | [react.dev](https://react.dev) |
| `react-dom` | ^19.2.4 | 將 React 元件渲染至瀏覽器 DOM | Renders React components to the browser DOM | [react.dev](https://react.dev) |
| `react-router-dom` | ^7.14.0 | SPA 路由管理，含 route-level lazy loading（`UploadPage` / `ComparePage`） | SPA routing with route-level lazy loading for `UploadPage` and `ComparePage` | [reactrouter.com](https://reactrouter.com) |
| `typescript` | ~6.0.2 | 靜態型別檢查，確保元件 props、API 回傳值的型別安全 | Static type checking for component props and API response type safety | [typescriptlang.org](https://www.typescriptlang.org) |

#### PDF 渲染 / PDF Rendering

| 套件 | 版本 | 中文說明 | English Description | 來源 |
|------|------|----------|---------------------|------|
| `react-pdf` | ^10.4.1 | 以 `pdf.js` 渲染 PDF 頁面為 Canvas，支援連續捲動、頁面尺寸取得 | Renders PDF pages to Canvas using `pdf.js`; supports continuous scrolling and page dimension queries | [github.com/wojtekmaj/react-pdf](https://github.com/wojtekmaj/react-pdf) |
| `react-zoom-pan-pinch` | ^4.0.3 | PDF 縮放與平移手勢（滾輪縮放、拖曳平移、觸控支援） | Zoom and pan gestures for PDF (scroll-to-zoom, drag-to-pan, touch support) | [github.com/prc5/react-zoom-pan-pinch](https://github.com/prc5/react-zoom-pan-pinch) |

#### 狀態管理 / State Management

| 套件 | 版本 | 中文說明 | English Description | 來源 |
|------|------|----------|---------------------|------|
| `zustand` | ^5.0.12 | 輕量全域狀態管理，管理 diff 列表、選取狀態、核對清單、灰階切換 | Lightweight global state management for diff list, selection state, checklist, and grayscale toggle | [github.com/pmndrs/zustand](https://github.com/pmndrs/zustand) |

#### 網路請求 / Networking

| 套件 | 版本 | 中文說明 | English Description | 來源 |
|------|------|----------|---------------------|------|
| `axios` | ^1.15.0 | HTTP 客戶端，負責 REST API 呼叫與 Blob 下載（匯出 PDF / Excel） | HTTP client for REST API calls and Blob downloads (PDF/Excel exports) | [axios-http.com](https://axios-http.com) |

#### 樣式與圖示 / Styling & Icons

| 套件 | 版本 | 中文說明 | English Description | 來源 |
|------|------|----------|---------------------|------|
| `tailwindcss` | ^3.4.0 | Utility-first CSS 框架，所有元件樣式以 class 組合而非自訂 CSS | Utility-first CSS framework; all component styles are composed with classes, not custom CSS | [tailwindcss.com](https://tailwindcss.com) |
| `lucide-react` | ^1.8.0 | 一致風格的 SVG 圖示庫，用於按鈕、狀態指示、工具列 | Consistent SVG icon library for buttons, status indicators, and toolbar | [lucide.dev](https://lucide.dev) |
| `postcss` + `autoprefixer` | — | CSS 後處理：自動加入瀏覽器相容前綴（`-webkit-` 等） | CSS post-processing: auto-adds browser compatibility prefixes | [postcss.org](https://postcss.org) |

#### 建構工具 / Build Tooling

| 套件 | 版本 | 中文說明 | English Description | 來源 |
|------|------|----------|---------------------|------|
| `vite` | ^8.0.4 | 前端開發伺服器（HMR）與生產打包，設定了 `/api`、`/ws`、`/health` proxy | Frontend dev server (HMR) and production bundler; configured with `/api`, `/ws`, `/health` proxy | [vitejs.dev](https://vitejs.dev) |
| `@vitejs/plugin-react` | ^6.0.1 | Vite 的 React 插件，提供 Babel/SWC 快速重新整理（Fast Refresh） | Vite plugin for React with Babel/SWC Fast Refresh | [github.com/vitejs/vite-plugin-react](https://github.com/vitejs/vite-plugin-react) |

## 目前功能範圍

### 已完成

- PDF 上傳與背景比對任務
- WebSocket 進度更新（含任務從記憶體遺失後的 fallback 重建）
- Diff 結果查詢
- 差異搜尋與定位
- 灰階 PDF + 彩色疊圖標註（DiffOverlay 精確定位優化）
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
- **零漏報優化 (Zero-Miss Tuning)** — 調降像素門檻與面積，小區域自適應 NCC (0.70)，確保人為修改無所遁形
- **SSIM 子區域變更定位** — 利用 Structural Similarity 精確定位圖片內的差異子區域，搭配 Tesseract OCR 讀出文字
- **並行解析優化** — parser_service 並行呼叫 MinerU，縮短大型 PDF 等待時間
- **Sliding Window 差異合併** — 鄰近 diff 自動聚合，避免 UI 被碎片化標記淹沒
- **動態 DPI 像素比對** — 依頁面內容密度自適應渲染解析度
- **PDF 驗證封存** — 比對完成後一鍵封存原始 PDF 與標註 PDF，SHA-256 去重避免重複儲存
- **核驗歷史查詢** — `VerificationHistoryModal` 顯示每次核驗的審核者、確認數、標記數與備注
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
│   │   ├── routes_auth.py
│   │   ├── routes_compare.py
│   │   ├── routes_review.py
│   │   ├── routes_checklist.py
│   │   ├── routes_export.py
│   │   ├── routes_project.py
│   │   ├── routes_archive.py
│   │   └── websocket.py
│   ├── models/
│   ├── services/
│   │   ├── parser_service.py
│   │   ├── diff_service.py
│   │   ├── archive_service.py
│   │   ├── checklist_service.py
│   │   ├── export_service.py
│   │   └── coord_transformer.py
│   ├── tests/
│   ├── main.py
│   ├── config.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── components/
│   │   │   ├── DiffOverlay.tsx
│   │   │   ├── DiffPopup.tsx
│   │   │   ├── PDFViewer.tsx
│   │   │   ├── SyncScrollContainer.tsx
│   │   │   ├── ChecklistPanel.tsx
│   │   │   └── VerificationHistoryModal.tsx
│   │   ├── pages/
│   │   ├── services/
│   │   ├── stores/
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
├── docs/
├── samples/
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
- **macOS啟動**: 雙擊 `start-mac.command`
- **macOS停止**: 雙擊 `stop-mac.command`

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
uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

若不啟動 MinerU 容器，省略 `MINERU_API_URL` 即可，解析器自動退回 Docling。

### Frontend

```bash
cd /path/to/PDF_check/frontend
npm ci
npm run dev
```

Vite 已設定 proxy（本機開發 backend port 為 8001）：

- `/api` -> `http://localhost:8001`
- `/ws` -> `ws://localhost:8001`
- `/health` -> `http://localhost:8001`

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
- 磁碟需求：建議預留 **30GB 以上**（含模型快取 ~5-8GB + runtime + archives）
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

`backend/services/parser_service.py` 採多層 fallback 鏈（並行解析優化）：

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
- **Sliding Window 鄰近差異合併**：鄰近 bbox 自動聚合，避免碎片化標記
- **動態 DPI 像素比對**：依內容密度選擇合適渲染解析度
- **自適應 NCC 門檻**：小區域（<2000px）採寬鬆 0.70，大區域採嚴格 0.94，降低小文字漏報
- **SSIM 子區域定位**（`_ssim_map` + `_locate_image_changes`）：用 Structural Similarity 精確定位圖片內差異，再以 Tesseract OCR 讀出前後文字
- **嵌入圖片比對**：pHash 偵測圖片替換、尺寸變更或內容微調
- 最後依頁碼與座標排序並編成 `d001`, `d002`, ...
- **聯集策略**：文字 diff + 表格 diff + 像素 diff + 圖片 diff 取聯集，確保無遺漏任何變更

### 4. PDF 封存與核驗流程

`backend/services/archive_service.py`：

- 計算 SHA-256 雜湊，相同 hash pair 不重複封存（去重）
- 複製原始 PDF 與標註 PDF 至 `archives/{archive_id}/`
- 每次核驗建立 `verification_sessions` 紀錄（審核者、確認數、標記數、備注）
- 前端 `VerificationHistoryModal` 可查詢同一比對的所有核驗歷史

### 5. 前端渲染

前端比對頁由 `frontend/src/pages/ComparePage.tsx` 驅動：

- `SearchBar` 提供搜尋與差異列表
- `SyncScrollContainer` 控制雙欄同步滾動
- `PDFViewer` 用 `react-pdf` 顯示 PDF
- `DiffOverlay` 把 diff bbox 疊在當前頁（精確定位優化）
- `DiffPopup` 處理審核與標記問題
- `ChecklistPanel` / `ChecklistUpload` 處理核對清單
- `VerificationHistoryModal` 顯示封存核驗歷史

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
- `GET /api/export/{comparison_id}/log-txt`

### Archive（封存與核驗）

- `POST /api/archive/{comparison_id}/verify` — 封存比對並建立核驗紀錄
- `GET /api/archive/{comparison_id}/history` — 查詢比對的封存與核驗歷史
- `GET /api/archive/by-archive/{archive_id}/sessions` — 查詢封存下的所有核驗 session
- `GET /api/archive/files/{archive_id}/{file_type}` — 下載封存的 PDF（`old_pdf` / `new_pdf` / `annotated_pdf`）

### Project

- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{project_id}/comparisons`

### Auth

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
- `comparisons`（含 `old_hash` / `new_hash` 欄位）
- `review_logs`
- `checklists`
- `users` — 帳號密碼管理 (pbkdf2 雜湊)
- `pdf_archives` — 封存紀錄（SHA-256 去重、archive_id 目錄對應）
- `verification_sessions` — 每次核驗的快照（審核者、確認數、標記數）

### Runtime 檔案

典型目錄：

- `runtime/uploads/old`
- `runtime/uploads/new`
- `runtime/exports`
- `runtime/exports/markdown`
- `runtime/archives/{archive_id}/`
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
- 技術架構: `docs/technical-architecture.md`
- 效能量測: `docs/performance-benchmark.md`
- Docker 快速啟動: `DEPLOY.md`
