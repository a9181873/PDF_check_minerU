# PDF 解析與比對效能量測

## 目的

用固定腳本在不同硬體（macOS、Windows 工作站、Linux / OCI Server）測量 PDF 解析與比對成本，作為硬體採購、Docker 資源分配與回歸測試的依據。

- PDF 解析時間與比對時間（每次 run 的 elapsed seconds）
- 解析過程 CPU 使用率（平均/峰值）
- 解析過程記憶體使用量（平均/峰值 RSS）
- 使用的解析引擎（PyMuPDF / MinerU / Docling / fallback）
- 影像型 PDF 是否啟用 `ENABLE_IMAGE_TEXT_RECALL`
- visual fallback、OCR recall 與 table diff 的輸出量

## 量測方式分工

| 方式 | 用途 | 是否代表真實 OCR 行為 |
|------|------|------------------------|
| `backend/scripts/benchmark_parser.py` | 快速比較 parser 在不同主機上的耗時與 RSS | 否，主要量測 parser 層 |
| `GET /api/system/resource-logs` | 查看實際比對任務的 CPU/RAM/耗時 | 是，前提是透過系統上傳比對 |
| `backend/scripts/compare_recall_strategies.py` | 對 `商品DM/` 跑 MinerU forced-OCR A/B，含 `alignment` / `heuristic` / `hybrid` | 是，但需可連到 MinerU API |
| `backend/scripts/run_paddleocr_experiment.py` | 對兩份 PDF 跑 PaddleOCR metadata A/B，觀察候選數字差異與額外耗時 | 是，但需測試環境已安裝 PaddleOCR / PaddlePaddle 與模型 |
| `docs/recall-regression-runbook.md` | 真實容器端到端回歸 | 是，最接近正式環境 |

> 注意：host Python 可能沒有 `fitz`、Tesseract、Docling 或 MinerU 連線；判斷真實 OCR 品質時，請以 Docker 容器流程為準。

## Parser 量測腳本

- 腳本位置：`backend/scripts/benchmark_parser.py`
- 輸出格式：`JSON + CSV`
- 預設輸出資料夾：`backend/benchmarks/`

## 本機執行（macOS / Linux）

```bash
cd /path/to/PDF_check/backend
source .venv/bin/activate
python scripts/benchmark_parser.py \
  --pdf ../samples/台灣人壽金利樂利率變動型養老保險.pdf \
  --pdf ../samples/台灣人壽臻鑽旺旺變額萬能壽險.pdf \
  --warmup 1 \
  --repeat 3 \
  --cache-mode cold \
  --tag macbook
```

## Windows 工作站執行（PowerShell）

```powershell
cd C:\path\to\PDF_check\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:OCR_LANGS = "chi_tra+chi_sim+eng"

python scripts\benchmark_parser.py \
  --pdf ..\samples\台灣人壽金利樂利率變動型養老保險.pdf \
  --pdf ..\samples\台灣人壽臻鑽旺旺變額萬能壽險.pdf \
  --warmup 1 \
  --repeat 3 \
  --cache-mode cold \
  --tag windows
```

## 報表重點欄位

- `hardware`: 主機硬體與環境快照（CPU 核心數、總記憶體、平台資訊）
- `files[].runs[]`: 每次量測明細
  - `elapsed_sec`
  - `peak_rss_bytes`
  - `avg_cpu_percent` / `peak_cpu_percent`
  - `engine`
  - `table_engine`
  - `cache_hit`
- `files[].summary`: 每份 PDF 的聚合結果（平均、最小、最大）

`--cache-mode cold` 會在每次量測前清除程序內解析快取，適合比較引擎本身；`warm` 保留 SHA-256 快取，適合量測重複比對。同一程序產生的 Java／OCR 子程序會納入 RSS/CPU；獨立 MinerU 容器仍需搭配容器監控判讀。

完整比對報告的 `engine_stats.pixel_cache_hit` 會標示像素/NCC/OCR 是否直接命中配對快取；`parser_routing.old/new.cache_hit` 則是兩側文件解析快取。

## 真實比對資源紀錄

系統每次比對會寫入資源紀錄，可直接看實際 workload：

```bash
curl http://localhost:8001/api/system/resource-logs
curl http://localhost:8001/api/system/resource-logs/{task_id}
```

欄位重點：

- `elapsed_seconds`: 任務總耗時
- `peak_memory_mb`: 後端 process 峰值 RSS
- `avg_cpu_percent` / `peak_cpu_percent`: CPU 使用率；多核心時可能超過 100%
- `system_info.cpu_count` / `system_info.total_memory_gb`: 主機資源

## 商品 DM OCR A/B

影像型 PDF 的重負載請用 `商品DM/` 跑固定樣本：

```bash
cd backend
OCR_CACHE_DIR=/tmp/pdfcheck_ocr_cache \
python scripts/compare_recall_strategies.py \
  --dm-root ../商品DM \
  --output /tmp/dm_recall_ab.json
```

- 預設輸出 `alignment`、`heuristic` 與 `hybrid`。
- `OCR_CACHE_DIR` 會依 PDF SHA-256 快取 MinerU OCR 結果；第一次最慢，後續重跑主要測 diff 策略。
- 若要判斷正式部署品質，請優先看 `hybrid` 的可讀性與 visual bbox 是否保留，而不是單看 diff 筆數。

## PaddleOCR 實驗量測

PaddleOCR 第一版預設關閉，只量測候選 metadata。測試機需先預載 PaddleOCR 套件與模型：

```bash
cd backend
ENABLE_PADDLE_OCR_EXPERIMENT=true \
python scripts/run_paddleocr_experiment.py /path/old.pdf /path/new.pdf --force-image-mode
```

判讀重點：

- `elapsed_seconds`: 啟用 PaddleOCR 後增加的總耗時。
- `paddle_ocr.candidate_diff_count`: PaddleOCR 候選差異筆數。
- `paddle_ocr.changed_numeric_tokens`: OCR 看到的新舊數字 token 變化。
- `paddle_ocr.unconfirmed_changed_numeric_tokens`: 既有正式 diff 尚未確認的候選數字。
- `engine_warnings`: 是否出現 `paddle_ocr` 提醒或錯誤。

正式評估時，請與 `/api/system/resource-logs` 搭配看 CPU/RAM 峰值，並人工抽樣確認候選數字是否真的是有效差異。

## 硬體判讀準則

| 現象 | 代表意義 | 建議 |
|------|----------|------|
| CPU 長時間滿載、RAM 還有餘裕 | MinerU / OCR CPU-bound | 增加 CPU 核心或提升單核效能 |
| RAM 接近上限、Docker 開始變慢 | 模型與多任務擠壓記憶體 | 升到 32GB 以上，或限制同時比對數 |
| SSD 空間快速下降 | runtime、快照、匯出與 Docker image 累積 | 增加容量，定期備份與清理舊封存 |
| Windows 工作站 Docker 偶發卡頓 | WSL2 / Docker Desktop 資源分配不足 | 在 Docker Desktop 調高 CPU/RAM，或改 Linux Server |
| Windows Server 維運複雜 | Linux containers 跑在 VM 層較穩 | 用 Ubuntu VM + Docker Engine 部署 |

## 建議比較方法

1. macOS 與 Windows 使用相同 `--warmup` / `--repeat`。
2. 先看 `elapsed_sec_avg` 與 `peak_rss_mb_max`。
3. 確認 `engine_set` 相同，避免拿 Docling / fallback / MinerU 不同路徑直接比較。
4. 若 Windows 首次 run 明顯較慢，先排除模型初次下載與 WSL2 初次啟動影響（看 warmup 後的平均值）。
5. 影像型 PDF 請另外跑容器回歸；parser benchmark 不能代表 OCR recall 品質。
