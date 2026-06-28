# PDF Check MinerU 技術使用現況（2026-06-28）

## 1. 執行摘要

目前正式路線維持 Docker Compose，前端、FastAPI、Docling 與 MinerU 都在 Linux containers 內執行，不依賴 GPU。系統已從「MinerU 與 Docling 同時重跑」改成「PyMuPDF 快篩、Docling 優先、MinerU fallback」，並加入有限佇列、重型 parser semaphore、SHA-256 快取與 single-flight，主要目標是控制 CPU-only 主機的延遲與記憶體尖峰。

2026-06-28 驗證狀態：後端 120 項測試通過、前端 production build 通過；本機 Docker 完成 6 組、12 份 PDF、60 頁商品 DM 回歸；正式程式部署基線為 `6863872`。OCI 的 MinerU 3.4.0、`six 1.17.0` 與 backend 健康端點均已確認正常。

## 2. 正式技術組成

| 層級 | 使用技術 | 目前用途與狀態 |
|------|----------|----------------|
| 前端 | React 19、TypeScript 6、Vite 8、Zustand、React PDF | PDF 顯示、差異覆蓋、審核、搜尋、匯出、歷史紀錄；production build 已驗證 |
| API | FastAPI、Uvicorn | REST、WebSocket、檔案上傳、任務狀態；同步 SQLite route 由 threadpool 執行 |
| 任務控制 | `compare_job_runner` | 程序內有限佇列；限制同時執行與等待數，超量時回傳可預期錯誤 |
| 流程協調 | `compare_orchestrator` | 統一解析、比對、快照、裁切、報表與資料庫寫入流程 |
| 輕量解析 | PyMuPDF | 永遠優先讀取文字、字元 bbox、頁面圖片與幾何線條；也是無模型表格快篩來源 |
| 表格解析 | Docling | 疑似表格時的第一個重型引擎，優先取得 cell-level bbox |
| 複雜解析/OCR | MinerU pipeline REST API | Docling 無有效表格時 fallback；影像型 PDF OCR recall 預設關閉、需明確啟用 |
| 最終備援 | pdftotext、Tesseract | 前述解析失敗時使用；定位精度與速度較差 |
| 差異演算法 | 文字、表格、像素、SSIM、NCC、pHash、區域 OCR 聯集 | 兼顧內容差異與可審核視覺證據，最後做鄰近合併與去重 |
| 儲存 | SQLite + Docker volume | 保存帳號、專案、比對、審核、封存、runtime 上傳與匯出檔 |
| 部署 | Docker Compose | 本機使用 bridge network；OCI 使用外部 Docker network 接反向代理 |

## 3. PDF 實際處理路徑

1. FastAPI 接收新舊 PDF，有限佇列先檢查執行中與等待中的任務數。
2. PyMuPDF 讀取內嵌文字、bbox、圖片與繪圖線段，並判斷是否為 image-only PDF、是否疑似有表格。
3. 一般文字 PDF 且沒有表格跡象時，直接沿用 PyMuPDF 結果，不啟動模型。
4. 疑似表格時依 `TABLE_PARSER_STRATEGY=docling_first` 執行 Docling；只有 Docling 失敗或沒有有效表格才呼叫 MinerU。
5. 任一方為 image-only PDF 時，正式預設保留像素／視覺差異。只有 `ENABLE_IMAGE_TEXT_RECALL=true` 才額外執行 MinerU forced-OCR，產生 `alignment`、`heuristic` 或 `hybrid` 文字候選。
6. 差異引擎聯集文字、表格、像素與圖片結果，執行 bbox 鄰近合併、框中框去除與排序，再寫入 SQLite 並透過 WebSocket 通知前端。

這個路由的核心取捨是：PyMuPDF 負責便宜且穩定的文字／幾何工作；Docling 補格子座標；MinerU 處理複雜中文表格與可選 OCR。三者不是每份 PDF 都同時執行。

## 4. 併發、快取與資源控制

| 設定 | Docker 預設 | 作用 |
|------|-------------|------|
| `COMPARE_MAX_CONCURRENCY` | `1` | 同時執行的完整比對任務上限 |
| `COMPARE_MAX_PENDING_TASKS` | `4` | 等待中的任務上限，避免無限堆積 |
| `HEAVY_PARSER_MAX_CONCURRENCY` | `1` | Docling、MinerU、OpenDataLoader 重型解析同時執行上限 |
| `ENABLE_LIGHTWEIGHT_TABLE_PROBE` | `true` | 無表格跡象時跳過重型 parser |
| `ENABLE_PARSER_CACHE` | `true` | PDF SHA-256 程序內解析快取 |
| `PARSER_CACHE_MAX_ENTRIES` | `8` | 解析快取最大文件數 |
| `ENABLE_PIXEL_DIFF_CACHE` | `true` | 新舊 PDF 配對的像素、NCC、OCR 結果快取 |
| `PIXEL_DIFF_CACHE_MAX_ENTRIES` | `8` | 像素差異配對快取上限 |
| `MINERU_TIMEOUT_SECONDS` | `300` | 單次 MinerU API timeout |

single-flight 會讓相同 SHA-256 PDF 在同一時間只解析一次；其他呼叫等待同一結果。快取目前是程序內 bounded cache，容器重啟後會清空，不是跨重啟持久快取。

## 5. 前後端架構改善狀況

- `routes_compare.py` 不再直接承擔整個解析／比對流程；業務流程移到 orchestrator，較容易單元測試與替換 parser。
- 含同步 SQLite I/O 的 route 使用同步 handler，FastAPI 會放入 threadpool，避免同步資料庫操作卡住 event loop 與其他 WebSocket/API 請求。
- `UploadPage` 的檔案上傳區已移成獨立元件，避免父元件重繪時 input 被 React 卸載重建。
- Axios client、diff helper、對話框 focus trap 與列表篩選邏輯集中管理，降低重複與狀態漂移。
- WebSocket 回報完成後會中止舊的 HTTP polling，避免較晚抵達的舊回應覆蓋完成狀態。
- Escape 關閉與 focus trap 已套用至主要自訂對話框，改善鍵盤與無障礙操作。

仍待拆分的最大技術債是 `diff_service.py`；本輪先抽離流程協調，尚未把文字、像素、OCR、bbox 幾何全面拆成獨立 domain module。

## 6. Docker 與 OCI 現況

Compose 主要服務：

- `mineru-api-minerU`：MinerU pipeline API，容器內 `18080`，有 `/health` healthcheck。
- `backend-minerU`：FastAPI `8000`，同一 image 內包含 Vite 編譯後的 React static files。
- `backend_runtime_minerU`：SQLite、上傳、快照、裁切與匯出資料。
- `backend_hf_cache_minerU`、`mineru_model_cache_minerU`：runtime 模型快取。

OCI 使用 ARM64、CPU-only。正式主機保留環境專用 compose override：backend 採 Docker 動態 host port，並加入既有 external network 讓反向代理依容器名稱連線；因此不應用本機 compose 直接覆蓋 OCI 設定。

MinerU 模型在 Dockerfile 的 build 階段下載並寫入 image layer。runtime volume 不會提供給 build；只有 Docker/BuildKit layer cache 能避免重下。只要基底 image 或 pip layer 改變，模型 layer 就可能失效。

## 7. 目前實際版本與供應鏈狀況

2026-06-28 OCI 重建觀察到：

| 容器 | 主要實際版本 |
|------|--------------|
| MinerU | MinerU 3.4.0、six 1.17.0、Torch 2.12.1、Python 3.13 |
| Backend | Docling 2.107.0、PyMuPDF 1.27.2.3、FastAPI 0.138.1、Uvicorn 0.49.0、Python 3.11 |
| Frontend | React 19.2.4、Vite 8.0.8、TypeScript 6.0.2 |

目前 requirements 多數使用最低版本範圍，完整 transitive dependencies 未 lock。ARM64 建置時，MinerU 與 Docling／Torch 即使以 CPU-only 執行，仍下載多個 CUDA wheel，造成建置時間長、image 大與磁碟使用增加。這不是 GPU 已啟用，而是上游 wheel dependency resolution 的結果。

建議下一步：固定已驗證版本與 image digest、建立 CPU-only requirements/profile、確認 Torch CPU wheel 在 ARM64 的可用來源，再以相同黃金樣本比較準確率與效能，避免只為瘦身改壞辨識結果。

## 8. 2026-06-28 全 PDF 實測

| 指標 | 結果 |
|------|------|
| 案例 | 6 組 |
| PDF | 12 份 |
| 頁數／段落 | 60 頁／698 段 |
| OCR 快取 | 12 份皆 miss |
| 模型載入後區間 | 54 頁，345.44 秒 |
| 觀察吞吐 | 6.40 秒/頁，9.38 頁/分鐘 |
| 候選差異數 | alignment 10、heuristic 6、hybrid 8 |

首份 PDF 包含模型冷啟動，但腳本未記錄開始時間；CPU、RSS 與各 phase 耗時也沒有寫入該 JSON，因此不能把上表當成完整冷啟動 SLA。候選差異數沒有人工真值，也不能直接當準確率。完整逐案結果與 OCR 噪音案例見 `full_pdf_regression_2026-06-28.md`。

## 9. 已知風險與優先順序

| 優先 | 風險／缺口 | 建議處理 |
|------|------------|----------|
| P0 | 沒有人工標註黃金答案 | 建立 precision、recall、F1 與 bbox/page accuracy 回歸集 |
| P0 | Python／模型 transitive dependency 未 lock | 固定版本與 image digest，建立可重現 SBOM |
| P1 | ARM64 CPU-only image 仍含大型 CUDA wheel | 建立 CPU-only profile，量測 image、冷啟動、RAM 與辨識回歸 |
| P1 | A/B JSON 未記錄完整 phase timing | 加入 cold start、parse、diff、CPU、RSS、cache hit 欄位 |
| P1 | `diff_service.py` 仍過大 | 逐步拆成 text、image、OCR、bbox、normalization 模組 |
| P2 | 程序內佇列與快取無法跨重啟復原 | 多節點或高可用需求出現時再導入 Redis／持久化 worker |

## 10. 維運檢查

```bash
# 查看容器與 health 狀態
docker compose ps

# 驗證 MinerU runtime 相依套件
docker exec mineru-api-minerU python -c "import six; print(six.__version__)"

# 健康端點
docker exec mineru-api-minerU curl -fsS http://localhost:18080/health
docker exec pdf-check-minerU python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read().decode())"

# 僅重建前後端；不觸碰 MinerU image
docker compose build backend-minerU
docker compose up -d backend-minerU
```

完整重建 MinerU 前，先確認磁碟空間、BuildKit cache 與模型來源連線；不要假設 runtime model volume 可以替代 build 階段下載。
