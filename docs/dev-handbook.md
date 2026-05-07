# PDF Check 開發手冊

這份文件面向開發者，重點不是操作教學，而是說明目前程式的技術設計、模組邊界、資料流、實作現況與擴充方向。內容以目前程式碼為準，而不是理想藍圖。

## 1. 系統定位

本系統聚焦在「保險 PDF 文件的新舊文字差異審核」。

設計原則：

- 以內容差異為主，不做版面像素還原
- 前端畫面優先支援審核效率，而不是重型編輯
- 後端以可觀測、可匯出、可追蹤為優先
- 對於耗時工作採背景任務 + WebSocket 進度更新

非目標：

- 不做完整 OCR 工作台
- 不做全量版控系統
- 不做美術版面相似度評分

## 2. 執行架構

### 2.1 Runtime 拓樸

```text
React SPA
  ├─ UploadPage
  └─ ComparePage
       │
       ├─ REST API
       └─ WebSocket
            │
FastAPI
  ├─ routes_compare
  ├─ routes_review
  ├─ routes_checklist
  ├─ routes_export
  ├─ routes_project
  └─ websocket
       │
Services
  ├─ parser_service
  ├─ diff_service
  ├─ checklist_service
  ├─ export_service
  └─ coord_transformer
       │
SQLite + runtime files + in-memory stores
```

### 2.2 非同步模型

目前沒有 Celery、RQ 或獨立 worker。上傳 API 使用 `FastAPI BackgroundTasks` 執行比對工作：

1. API 收到檔案
2. 寫入本機 / volume
3. 建立 comparison 記錄
4. 將 `_run_compare_task()` 放入背景任務
5. 前端透過 WebSocket 與 polling 追蹤狀態

這個模型對單機部署很簡單，但也代表：

- 背景任務與 API 進程生命週期綁在一起
- 若服務重啟，執行中任務不會自動恢復
- 不適合高併發長任務場景

## 3. 後端模組說明

### 3.1 `backend/main.py`

責任：

- 建立 FastAPI app
- 掛載 CORS
- 註冊所有 router
- 啟動時建立 runtime 目錄與初始化 SQLite
- 掛載 `/uploads` 與 SPA 靜態檔

重要設計：

- 靜態站點掛載放在最後，避免先吃掉 `/api/*` 與 `/health`
- `check_dir=False` 讓容器內靜態目錄不存在時不會在 import 當下崩潰

### 3.2 `backend/config.py`

責任：

- 集中管理 `DATA_DIR`, `HF_HOME`, `debug`, `allowed_origins`
- 正規化 `DEBUG` 字串布林值

注意：

- 若本機沒有 `runtime/` 目錄，`data_dir` 會 fallback 到 `/app/runtime`
- 本機開發建議明確設定 `DATA_DIR`

### 3.3 `backend/api/routes_compare.py`

責任：

- 驗證與保存 PDF 上傳
- 啟動背景比較任務
- 提供 status / result / markdown / pdf download API

關鍵流程：

1. `_assert_pdf()` 驗證副檔名
2. `_save_upload()` 將檔名包成 `task_id_original_name`
3. `_run_compare_task()` 依序執行：
   - parse old
   - parse new
   - export markdown
   - generate diff report
   - save result / error

### 3.4 `backend/api/websocket.py`

責任：

- 輪詢 `TASK_STORE`
- 在狀態變動時推送 `progress`
- 任務完成推送 `complete`
- 任務失敗推送 `error`

這裡是 server push，不依賴資料庫查詢，延遲低，但只對執行中的 process state 有效。

### 3.5 `backend/api/routes_review.py`

責任：

- 接受審核動作
- 記錄 `review_logs`
- 回傳 summary

重要行為：

- `confirm_diff()` 會修改載入到記憶體中的 `DiffReport` item 狀態
- `review_summary()` 的 authoritative source 是 `review_logs`
- summary 會以每個 `diff_item_id` 最新一筆 action 為準，而不是直接數 log 筆數

目前 `confirm_diff()` 在更新記憶體中 report 後，也會把新的 report state 回寫 SQLite，避免服務重啟後審核狀態遺失。

### 3.6 `backend/api/routes_checklist.py`

責任：

- 匯入 checklist 檔案
- 自動 match 到 diff item
- 提供 list / patch API

目前限制：

- checklist 會寫入 SQLite `checklists.items_json`
- `CHECKLIST_STORE` 仍保留作為 process memory cache

### 3.7 `backend/api/routes_export.py`

責任：

- 匯出標註 PDF
- 匯出 Excel
- 匯出真正的 review report PDF

目前 report PDF 為程式生成型摘要報告，不是設計版報告模板，但已不再是 `/pdf` 的 alias。

## 4. 服務層說明

### 4.1 `parser_service.py`

`ParsedDocument` 是後端比對流程的核心中介型別，欄位包含：

- `pages`
- `paragraphs`
- `tables`
- `raw_json`
- `markdown_text`

解析策略：

1. `Docling`
2. `PyMuPDF`
3. `pdftotext`

關鍵點：

- Docling bbox 會轉成 bottom-left PDF 座標
- 若 Docling 沒產生足夠 paragraph，會從 markdown 補 synthetic paragraph
- fallback 解析器雖精度較低，但讓服務不會因單一引擎失敗而整體中斷

### 4.2 `diff_service.py`

差異引擎核心，整合多路比對技術：

`diff_paragraphs()`：
- 對 old/new paragraph text 先做 whitespace normalize (NFKC)
- 用 `SequenceMatcher.get_opcodes()` 產生差異碼
- `_guess_diff_type()` 根據 regex 決定 `number_modified` 或 `text_modified`

`diff_tables()`：
- **Cell-level diff**：逐格比對 DataFrame 內容
- **70% 聚合策略**：若表格變動格數超過 70%，自動合併為單一「整表替換」項，避免 UI 碎片化

`diff_images()` (2026-05-08 重大更新)：
- **感知雜湊 (pHash)**：初步判斷圖片是否變動或替換
- **SSIM 子區域定位**：針對 pHash 匹配的圖片，用滑動窗口 SSIM 偵測細微局部變更（如費率數字修改）
- **區域性 OCR**：對 SSIM 標記區域調用 Tesseract OCR，並將結果回傳為 `TEXT_MODIFIED`

`diff_pixels()`：
- **動態 DPI**：Phase 1 低解析度掃描頁面差異，Phase 2 高解析度分析變更頁
- **自適應 NCC**：小區域採寬鬆門檻 (0.70)，捕捉極微小文字變動

後處理：
- **`_merge_nearby_diffs()`**：使用 Union-Find 演算法對空間鄰近的差異項進行物理聚合，解決解析器斷行產生的碎片標記。
- **去重機制**：自動移除「框中框」重疊項。

### 4.3 `checklist_service.py`

責任是把 CSV / Excel 轉成 `ChecklistItem`，再用關鍵字與 expected value 自動對到 diff item。這層不是 fuzzy semantic engine，而是規則型匹配，適合審核流程中的明確欄位驗證。

### 4.4 `export_service.py`

PDF 匯出：

- 使用 `PyMuPDF`
- 取 `new_bbox` 優先，否則 fallback `old_bbox`
- 在 PDF 上畫矩形並加 highlight annotation

Excel 匯出：

- `diffs`
- `checklist`
- `summary`

目前 `summary.flagged` 是固定 `0`，尚未整合 review_logs 的 flagged 統計。

## 5. 資料模型與持久化

### 5.1 SQLite 表

目前會初始化這些表：

- `projects`
- `comparisons`
- `review_logs`
- `checklists`

其中 `comparisons` 額外擴充欄位：

- `error_message`
- `old_markdown_path`
- `new_markdown_path`

### 5.2 實際持久化狀態

| 項目 | 持久化方式 | 備註 |
|------|------------|------|
| project | SQLite | 已完成 |
| comparison metadata | SQLite | 已完成 |
| diff_result_json | SQLite | 已完成 |
| review log | SQLite | 已完成 |
| checklist data | SQLite + 記憶體快取 | 已落地 |
| running task state | 記憶體 | `TASK_STORE` |

### 5.3 座標系統

前後端協作的關鍵在 bbox 座標：

- 後端統一輸出 PDF bottom-left 座標
- 前端 overlay 會根據畫布大小與 PDF page size 換算成畫面座標

這樣同一筆 diff 可以同時支援：

- PDF 畫面高亮
- PDF 匯出矩形
- 搜尋跳轉定位

## 6. 前端模組說明

### 6.1 `App.tsx`

目前已做 route-level lazy loading：

- `UploadPage`
- `ComparePage`

好處：

- 首頁不必預先下載 compare workspace
- 重資產延後到真正進入比對頁才載入

### 6.2 `UploadPage.tsx`

責任：

- 舊版 / 新版 PDF 選取
- 副檔名與大小驗證
- project id 輸入
- 成功建立任務後跳轉 `/compare/:taskId`

### 6.3 `ComparePage.tsx`

這是前端的 orchestration layer。

責任：

- 從 URL 讀 `taskId`
- 建立 WebSocket
- fallback polling status
- 載入 report / checklist
- 控制 tab / popup / panel / scroll sync
- 呼叫 review / export API

這個元件目前仍然偏大，但已進行 component-level lazy loading：

- `PDFViewer`
- `ChecklistUpload`
- `DiffPopup`

### 6.4 `PDFViewer.tsx`

責任：

- 透過 `react-pdf` 顯示指定頁
- 控制頁碼、縮放、旋轉、灰階
- 顯示 children overlay

技術重點：

- PDF worker 走本地打包資產，不依賴外部 CDN
- 這讓企業內網或無外網環境更穩

### 6.5 `SyncScrollContainer.tsx`

責任：

- 左右欄同步滾動
- 避免 scroll event 互相反覆觸發
- 支援隱藏左欄

### 6.6 `compareStore.ts`

目前用 Zustand 管理：

- 任務狀態
- report
- 搜尋篩選結果
- checklist
- 左欄隱藏 / 同步滾動 / popup 等 UI 狀態

這層把視圖與資料狀態拆開，讓 `ComparePage` 的事件處理仍可維持可控。

## 7. 打包與效能優化

目前已做的優化：

- `ComparePage` route lazy loading
- `PDFViewer` / `ChecklistUpload` / `DiffPopup` component lazy loading
- Vite `manualChunks` 拆分：
  - `react-core`
  - `app-vendor`
  - `pdf-runtime`
  - `ui-icons`

目前效益：

- 首頁只需載入 `UploadPage`
- 進入比對頁時才下載 `react-pdf` 與 `pdfjs`
- PDF worker 獨立成資產，不阻塞首頁

## 8. Docker 與部署

### 8.1 Compose

`docker-compose.yml` 使用單一 `backend` service，容器內同時服務：

- FastAPI API
- 靜態前端檔
- WebSocket

### 8.2 Image build

`backend/Dockerfile` 採 multi-stage build：

1. Node stage build 前端
2. Python stage 安裝後端依賴
3. 複製 frontend `dist` 到 backend `static`

這是目前一鍵啟動可工作的關鍵：Docker build context 已調整到專案根目錄，避免 `COPY ../frontend` 類型錯誤。

### 8.3 啟動腳本

一鍵啟動腳本除了 `docker compose up --build -d` 外，還會：

- 檢查 Docker 是否存在
- 檢查 Docker daemon 是否啟動
- 輪詢 `/health`
- 服務就緒後才自動開啟瀏覽器

## 9. API 清單

### Compare

- `POST /api/compare/upload`
- `GET /api/compare/{task_id}/status`
- `GET /api/compare/{task_id}/result`
- `GET /api/compare/{task_id}/markdown`
- `GET /api/compare/{task_id}/markdown/{version}`
- `GET /api/compare/{task_id}/pdf/{version}`

### WebSocket

- `WS /ws/compare/{task_id}`

事件格式：

- `progress`
- `complete`
- `error`

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

### Project

- `POST /api/projects`
- `GET /api/projects`
- `GET /api/projects/{project_id}/comparisons`

## 10. 測試與驗證

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

現有測試覆蓋：

- `test_diff.py`
- `test_markdown.py`
- `test_coord_transformer.py`

## 11. 已知風險與後續建議

### 高優先

- 讓 review 狀態與 `diff_result_json` / `review_logs` 長期維持單一來源設計
- 提升 table diff 定位精度到 cell bbox
- 增加 report PDF 模板化版型

### 中優先

- 將背景任務改成獨立 worker queue
- 匯出 summary sheet 時納入 flagged 真實統計
- 增加 API 整合測試與 smoke test

### 低優先

- 支援批次比較 dashboard
- 支援更細緻的 diff filter 與 bookmark
- 支援完整報告 PDF 模板，而非暫時 alias `/report -> /pdf`
