# PDF/OCR 效能與準確度優化實作紀錄（2026-07-04）

## 已完成

- 雙軌審核：可靠內容進 `content`；無可靠文字但確有變更者進 `needs_visual_review`。
- 每筆差異新增穩定 `candidate_id`、風險、分析階段、決策原因、證據與模型版本。
- `preliminary_result → result_updated → complete` 漸進 WebSocket/API；輪詢亦可取得初步報告。
- 背景補強以 `candidate_id` 合併並保留人工審核狀態，避免覆寫 reviewer 操作。
- 初步階段採 144 DPI 視覺候選與保護式頁首／頁尾 OCR；完整階段才執行 200 DPI 一般 OCR、圖片分析與可選召回引擎。
- 實質表格／版面變更不再靜默丟棄；小型 rendering noise 仍可計數降噪。
- 表格依 page、bbox IoU、列欄結構與表頭簽章配對，不依輸出順序。
- PaddleOCR 實驗改為只辨識像素差異 ROI。
- 像素分析加入跨重啟 JSON 快取，鍵含 PDF SHA-256、DPI、OCR 模式、語言與演算法版本。
- 封存前強制分析完成，且所有高風險與待人工區域須審核完成。
- 建立六對版本化黃金 manifest、跨主機 runner 與比較工具。
- Backend／MinerU 直接依賴固定到 OCI 驗證版本；backend 基底 image 固定 digest；離線打包加入 SPDX SBOM。
- CPU 映像固定從 PyTorch 官方 CPU wheel 索引安裝 `torch`／`torchvision`，避免 Linux ARM64 誤選 CUDA wheel 造成映像與 OCI 儲存空間暴增。

## 驗證

- 後端：127 tests passed。
- 前端：TypeScript 與 Vite production build passed。
- Python compileall 與 `git diff --check` passed。
- MacBook Air M4 正式五輪（cold／warm 各 30 runs）：cold 初步 P95 7.41 秒、完整 P95 38.45 秒；初步區域與完整必抓召回皆 100%，禁止誤報與實質視覺靜默抑制皆為 0。
- 同一 CPU-only 正式 Docker 映像在 Mac Docker Desktop 10 vCPU／8GB 正式五輪：cold 初步 P95 10.13 秒、完整 P95 56.04 秒；warm 為 0.020／2.62 秒，四項 SLA 全過、無 OOM，每個變更頁候選最多 3 個。
- `pixel-v4` 修正小型數字區域 NCC 過度抑制；鳳守愛 `24→28` 在初步階段即進入待判讀區域，不再等完整 OCR 才出現。
- CPU-only backend image 驗證為 `torch 2.12.1+cpu`、無 NVIDIA／CUDA 套件，映像約 764MB。
- Mac／OCI 實測結果見[跨主機比較](../benchmarks/results/mac_vs_oci_20260704.md)。

## 尚未升正式的項目

- PaddleOCR／PP-StructureV3 仍為可選實驗引擎，沒有直接升成正式差異來源。
- PaddleOCR-VL／Docling VLM 尚未部署；必須先達到「解決 ≥30% 待判讀區域、額外誤報 ≤5%、完整 P95 ≤90 秒」。
- 現有六對僅能證明既有護欄，precision 與泛化需隨封存案件累積至至少 30 對後再判定。
- OCI 已於 2026-07-05 部署 `b875a9b` CPU-only 映像；鳳守愛 cold／warm smoke 四項守門值全過。現有 OCI 全六組數據仍是修改前工程基線，最佳化版本正式五輪尚待離峰執行。
