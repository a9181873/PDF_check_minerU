# PaddleOCR 實驗版導入說明

## 目標

本功能是企業內網可部署的 OCR 第二引擎實驗版，不使用外部 API Key，不把 PDF 送出內網。第一階段只把 PaddleOCR 結果寫入 `engine_stats` / `engine_warnings` 做 A/B 評估，不直接改變正式差異清單。

## 第一版狀態

- 已接入 `backend/services/paddle_ocr_adapter.py`，採 lazy import；未安裝 PaddleOCR 時不影響主流程。
- 已加入 `backend/scripts/run_paddleocr_experiment.py`，可不啟動 API 直接跑兩份 PDF 做 A/B。
- 已加入單元測試，確認 PaddleOCR 候選數字差異會寫入 report metadata。
- 目前正式差異清單仍以既有 MinerU / Docling / PyMuPDF / visual diff 為準。
- 目前基礎 image 不預載 PaddleOCR；真實模型測試需另做 PaddleOCR Docker profile 或在測試機安裝套件與模型。

## 目前正式流程

正式差異清單不是全頁 OCR，也不是 PaddleOCR。現行主流程採分層策略：

| 層級 | 技術 | 用途 | 是否進正式差異 |
|---|---|---|---|
| 文字層 | PyMuPDF / fitz | 直接讀 PDF 內建文字，避免 OCR 誤讀 | 是 |
| 表格層 | MinerU / Docling | 補表格與 cell bbox；有文字層 PDF 會併入表格比對 | 是 |
| 影像定位 | PyMuPDF raster + pixel diff | image-only PDF 先找出哪裡有變，不直接全頁 OCR | 候選定位 |
| 局部 OCR | Tesseract | 只對差異框做小範圍 OCR，例如 footer 版號、Control No、圖片內小數字 | 可靠時才進正式差異 |
| 圖片比較 | ImageHash / SSIM | 偵測嵌入圖片內容變化 | 可靠文字/數字才進正式差異 |
| 實驗層 | PaddleOCR | A/B 候選與統計 | 預設不進正式差異 |

已驗證案例：

- `台灣人壽鳳守愛防癌定期健康保險_商品DM_20260213適用.pdf`
- `台灣人壽鳳守愛防癌定期健康保險_商品DM_20260506適用.pdf`

預期正式差異包含：

- `Page 2 圖片數字變更: 24 -> 28`
- `Page 6 footer control/version: Version 2026.02 / OP-2602-0081 -> Version 2026.05 / 2605-OP-0029`

## 啟用方式

預設關閉。測試時用環境變數開啟：

```bash
ENABLE_PADDLE_OCR_EXPERIMENT=true
PADDLE_OCR_LANG=ch
PADDLE_OCR_DPI=200
PADDLE_OCR_MAX_PAGES=20
PADDLE_OCR_MIN_CONFIDENCE=0.35
```

## 企業部署原則

- 不使用 Google / Azure / AWS OCR API。
- 不需要外部 API Token。
- 正式環境不建議 runtime 自動下載模型。
- PaddleOCR 套件與模型應在 Docker image build 階段預載，或由離線模型包匯入。
- 第一階段只針對 image-only / mixed PDF 做候選辨識，避免所有 PDF 全量加跑造成硬體暴衝。
- OCI / 內網正式機未確認前，不要把 PaddleOCR 候選直接併入正式 diff item。

## Report 觀察欄位

開啟後可在比對報告中查看：

- `engine_stats.paddle_ocr.enabled`
- `engine_stats.paddle_ocr.old_paragraphs`
- `engine_stats.paddle_ocr.new_paragraphs`
- `engine_stats.paddle_ocr.candidate_diff_count`
- `engine_stats.paddle_ocr.changed_numeric_tokens`
- `engine_stats.paddle_ocr.unconfirmed_changed_numeric_tokens`
- `engine_warnings[]`

若 PaddleOCR 發現數字變動，但主流程尚未確認，會出現警示：

```text
paddle_ocr: detected N numeric tokens not confirmed by primary diff
```

## 硬體影響

正式流程的效能策略：

- **不做全頁 OCR**：image-only PDF 先用低 DPI 快速掃描找有差異頁，再只針對差異區塊處理。
- **只做局部 OCR**：Tesseract 只跑 header/footer 高價值欄位與小型差異框，不對整份 PDF 全量 OCR。
- **圖片小數字 fallback**：像 `24年 -> 28年` 這類小框會多做一次放大局部 OCR；成本跟差異框數量成正比，通常遠低於全頁 OCR。
- **PaddleOCR 預設關閉**：不會增加正式任務時間；開啟後只做實驗統計。
- **快取/背景化**：old/new 解析可並行，截圖/crop 可在報告完成後背景產生，避免拖慢差異清單可用時間。

| 模式 | 影響 |
|---|---|
| 預設關閉 | 無額外負載 |
| 影像型 PDF 才啟用 | CPU/RAM 中等增加 |
| 所有 PDF 全量啟用 | CPU/RAM 明顯增加，不建議第一階段使用 |
| GPU 模式 | 可提升吞吐，但需額外管理 CUDA / 驅動 / 顯存 |

建議測試機至少 `8 vCPU / 32GB RAM / 512GB SSD`。多人正式機建議 `12+ vCPU / 64GB RAM / 1TB SSD`。

平台建議：

| 平台 | 建議 |
|------|------|
| macOS | M4 / 24GB / 512GB 可測；常跑 OCR 回歸建議 M4 Pro / 48GB / 1TB |
| Windows 10/11 | 8 核以上、32GB RAM、1TB NVMe，Docker Desktop + WSL2 請調高 CPU/RAM 配額 |
| Windows Server | 不建議直接用 Docker Desktop；請在 Hyper-V/VMware 建 Ubuntu VM，VM 至少 8 vCPU / 32GB / 512GB |
| Linux / OCI | 正式測試首選；8 vCPU / 32GB / 512GB 起，多人與長期主力 12+ vCPU / 64GB / 1TB |

第一輪實測先保守設定：

- `PADDLE_OCR_DPI=200`
- `PADDLE_OCR_MAX_PAGES=20`
- 同時比對任務數維持 1 到 2 個
- 用 `/api/system/resource-logs` 觀察 `elapsed_seconds`、`peak_memory_mb`、`peak_cpu_percent`

## 評估指標

1. 數字/百分比漏報是否下降。
2. `unconfirmed_changed_numeric_tokens` 是否真的是有效差異。
3. 每份 PDF 增加的處理秒數。
4. CPU/RAM 峰值。
5. 誤報是否可由高風險提示接受。

## 快速測試腳本

不啟動 API 時，可直接跑：

```bash
cd backend
ENABLE_PADDLE_OCR_EXPERIMENT=true \
python scripts/run_paddleocr_experiment.py /path/old.pdf /path/new.pdf --force-image-mode
```

輸出會包含：

- `elapsed_seconds`
- `summary`
- `total_diffs`
- `engine_warnings`
- `paddle_ocr`

## 後續升級條件

只有當實測樣本顯示 PaddleOCR 候選差異穩定有效，才考慮把候選差異升級為正式 diff item；否則維持高風險提示，交由人工覆核。

升級前至少要完成：

1. 固定商品 DM / 條款 / 費率表黃金測試集。
2. 統計數字與百分比漏報下降幅度。
3. 統計誤報增加幅度。
4. 在 OCI 或等效 Linux Server 上跑資源量測。
5. 保留 feature flag，可一鍵關閉回到既有流程。
