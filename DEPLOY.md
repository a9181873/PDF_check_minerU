# PDF 比對系統 - 部署指南

保險 DM 雙版本 PDF 比對工具（FastAPI 後端 + React 前端）。

---

## 系統需求

本系統目前以 Linux containers 執行兩個主要服務：`backend-minerU` 與 `mineru-api-minerU`。macOS / Windows 桌面環境建議用 Docker Desktop；正式常駐服務建議用 Linux Server 或 Linux VM 跑 Docker Engine + Compose plugin。

現行漸進式分析、雙軌審核、快取與模組關係見 `docs/technical-architecture.md`。

| 平台 | 建議環境 | 最低試跑 | 正式建議 |
|------|----------|----------|----------|
| macOS | Docker Desktop | Apple Silicon 或 Intel、16GB RAM、120GB SSD | Mac mini `M4 / 24GB / 512GB` 起；常跑 OCR 回歸建議 `M4 Pro / 48GB / 1TB` |
| Windows 10/11 工作站 | Windows 11 Pro/Enterprise + WSL2 + Docker Desktop | 4 核、16GB RAM、120GB SSD | Intel Core i7/i9 或 Ryzen 7/9、8 核以上、32GB RAM、1TB NVMe |
| Windows Server | Hyper-V/VMware 上的 Ubuntu VM | 不建議直接當最低試跑環境 | Host 8 到 16 vCPU、32 到 64GB RAM、512GB 到 1TB SSD；Linux VM 分配至少 8 vCPU / 32GB / 512GB |
| Linux Server / OCI | Docker Engine + Compose plugin | 4 vCPU、16GB RAM、120GB SSD | 8 vCPU、32GB RAM、512GB SSD 起；長期主力建議 12+ vCPU、64GB RAM、1TB SSD |

- **Docker 官方下載**：<https://www.docker.com/products/docker-desktop/>
- **Windows 注意**：需啟用 BIOS/UEFI 虛擬化與 WSL2。Docker Desktop 官方不支援 Windows Server 作為 Desktop 平台；Windows Server 建議改跑 Ubuntu VM 或直接使用 Linux Server。
- **硬碟空間**：80GB 只適合短期試跑；正式環境請用 200GB 以上，長期封存/回歸建議 512GB 到 1TB。
- **RAM**：16GB 只算能跑；24GB 是單人合理起點；多人或常跑影像型 PDF OCR 建議 32GB 以上。

### Docker Desktop 配額不是主機規格

macOS／Windows 即使主機有 24GB 或 32GB RAM，Docker Desktop 仍可能只分配 8GB。效能測試前必須記錄實際容器配額：

```bash
docker info --format '{{.Architecture}} CPU={{.NCPU}} RAM={{.MemTotal}}'
```

若容器 RAM 少於 12GB，結果只能視為低配基準；發生 OOM 時先調整 Docker Desktop Resources，再判斷是否需要採購新硬體。

### Mac／OCI 同資料集效能基準

在 backend image 已建置、repo 掛載到容器的環境執行：

```bash
python backend/scripts/run_golden_benchmark.py \
  --repo-root . \
  --mode both \
  --repeat 1 \
  --host-label 'host description' \
  --output benchmarks/results/host.json
```

正式驗收將 `--repeat` 改為 `5`。腳本同時產生 JSON 與 Markdown，記錄 cold/warm、初步／完整 P50/P95、CPU、RSS、快取與黃金案例命中率。跨主機比較：

MacBook Air M4 已於 2026-07-05 完成 `--repeat 5`：原生 cold 初步／完整 P95 為 7.41／38.45 秒；正式 Docker 映像（10 vCPU、8GB）為 10.13／56.04 秒。兩者的初步區域與完整必抓召回皆為 100%。部署容量規劃應採較保守的 Docker 結果；OCI 最佳化版本仍須部署後以相同指令驗收。

```bash
python backend/scripts/compare_benchmark_results.py \
  benchmarks/results/mac.json benchmarks/results/oci.json \
  --output benchmarks/results/mac_vs_oci.md
```

---

## 安裝步驟

### 1. 確認 Docker 已啟動
```powershell
docker version
```
要看到 `Server: Docker Desktop` 區塊（非只有 Client）。若未啟動，開啟 Docker Desktop 等待其 ready。

### 2. 載入映像
收到的 zip 解壓後，在該資料夾執行：
```powershell
docker load -i pdf-check-backend_1.0.tar
docker load -i mineru-api_pipeline.tar
```
實際檔名依交付版本可能不同，重點是必須載入：

- `pdf-check-backend:latest` 或指定版號的 backend image
- `mineru-api:pipeline` MinerU image

看到 `Loaded image: ...` 即成功。若只載入 backend、沒有 `mineru-api:pipeline`，離線機會嘗試 build MinerU image，通常會因無法下載模型而失敗。

### 3. 啟動服務
```powershell
docker compose up -d
```
首次啟動約 10-30 秒。檢查是否正常：
```powershell
docker compose ps
docker compose logs -f backend-minerU
```
看到 `Uvicorn running on http://0.0.0.0:8000` 即 ready。

### 4. 開啟瀏覽器
<http://localhost:8001>

---

## 日常操作

| 動作 | 指令 |
|---|---|
| 啟動 | `docker compose up -d` |
| 停止 | `docker compose down` |
| 查看 log | `docker compose logs -f backend-minerU` |
| 重啟 | `docker compose restart backend-minerU` |
| 看容器狀態 | `docker compose ps` |

### 重新比對功能 (Recompare API)
當系統的比對引擎更新後，您可以對已經上傳過的任務進行「重新比對」，而無需重新上傳 PDF。這對大檔案特別方便：
```bash
# 觸發重新比對
curl -X POST http://localhost:8001/api/compare/recompare/{task_id}
```
*提示：前端介面若未來加入「重新比對」按鈕，也會呼叫此 API。*

### 表格、影像型 PDF 與召回層
現行比對引擎會合併多條證據路徑，而不是只靠 OCR：

- **文字 PDF**：PyMuPDF 字元座標 + MinerU / Docling 表格解析 + 像素補充驗證。
- **表格**：MinerU 提供中文表格內容，Docling 補 cell-level bbox；大量格子變動會聚合成整表變更，避免 UI 碎片化。
- **影像型 PDF**：預設保留 pixel / visual diff，讓 reviewer 看到實際變更區域。
- **OCR 召回層**：`ENABLE_IMAGE_TEXT_RECALL=false` 預設關閉；開啟後可用 `IMAGE_TEXT_RECALL_STRATEGY=alignment|heuristic|hybrid`，其中 `hybrid` 會整合兩路 OCR 候選並壓低碎片誤報。
- **PaddleOCR 實驗版**：`ENABLE_PADDLE_OCR_EXPERIMENT=false` 預設關閉；開啟後只寫入 `engine_stats.paddle_ocr` / `engine_warnings` 做 A/B，不會直接改正式差異清單。
- **大面積/複雜表格區域**：以視覺框與截圖為主，不強制把 OCR 亂碼塞進文字差異。

---

## 資料保存

所有上傳 PDF、比對結果、快照會存在 Docker 命名卷：
- `backend_runtime_minerU` — 上傳檔案、比對報告、封存 PDF、快照 PNG、SQLite
- `backend_hf_cache_minerU` — OCR / Docling 相關快取
- `mineru_model_cache_minerU` — MinerU 模型快取

留存功能支援案號：上傳時可填 `case_number`，存檔與下載檔名會帶案號前綴；封存去重鍵為 `old_hash + new_hash + case_number`，同一組 PDF 可依不同案號分開留存。

**資料位置**：Docker 管理，不在本機資料夾。若要備份：
```powershell
docker run --rm -v backend_runtime_minerU:/data -v ${PWD}:/backup alpine tar czf /backup/backend_runtime_backup.tgz -C /data .
```

若要**清空全部資料**（謹慎）：
```powershell
docker compose down -v
```

---

## 疑難排解

### 啟動後 http://localhost:8001 連不上
- 檢查 `docker compose ps`，status 應為 `running`
- 8001 port 被佔用：改 `docker-compose.yml` 中 `"8001:8000"` 為 `"8080:8000"`，改用 <http://localhost:8080>

### Windows 下看到「Hardware assisted virtualization」錯誤
BIOS 需開 VT-x/SVM。或改用 WSL2 後端的 Docker Desktop。

### 比對結果全空 / 顯示錯誤
查 log：`docker compose logs backend-minerU | tail -100`
最常見：上傳 PDF 檔壞掉、或 PDF 受密碼保護。

### 映像載入失敗 `invalid tar header`
tar 檔下載中斷。重傳一次完整檔案。

---

## 升級到新版

收到新版 zip 後：
```powershell
docker compose down
docker load -i pdf-check-backend_1.1.tar
# 編輯 docker-compose.yml，把 image 版本改為新版
docker compose up -d
```
資料卷不會被刪，過去比對紀錄保留。

---

## 離線部署（無網路環境）

本系統可完全離線運行，但需先在有網路的環境做以下準備：

> 建議直接用 `build-and-export.ps1` 打包（已自動匯出 backend + MinerU 兩個 image）。
> 以下為手動步驟，供需要客製時參考。

### 準備階段（需要網路）

```powershell
# 1. Build Docker images（backend + mineru-api 兩個）
docker compose build

# 2. 啟動並執行一次 PDF 比對（觸發 Docling 模型下載到 HF cache）
docker compose up -d
# 上傳任意 PDF 做一次比對，等比對完成後模型已快取

# 3. 匯出兩個 Docker image（缺 MinerU 離線機會嘗試 build 而失敗）
docker save pdf-check-backend:latest -o pdf-check-offline.tar
docker save mineru-api:pipeline      -o mineru-api_pipeline.tar

# 4. 匯出模型快取 volume
docker run --rm -v backend_hf_cache_minerU:/data -v ${PWD}:/backup alpine tar czf /backup/hf_cache_backup.tgz -C /data .
```

> MinerU pipeline 模型已在 build 時烤進 `mineru-api:pipeline` image（見 `mineru/Dockerfile`），
> 因此 `mineru-api_pipeline.tar` 已自帶模型，離線機不需再下載。

若要在離線環境測 PaddleOCR 實驗版，請另行準備含 PaddleOCR / PaddlePaddle / 模型快取的 backend image 或離線模型包。不要讓正式環境在 runtime 連外下載模型；建議用獨立 Docker profile 測試，確認資源用量與準確率後再決定是否納入正式 image。

### 離線環境部署

將以下檔案帶到離線環境：
- `pdf-check-offline.tar` — backend image
- `mineru-api_pipeline.tar` — MinerU image（含 pipeline 模型）
- `hf_cache_backup.tgz` — Docling 模型快取
- `docker-compose.yml` — 啟動設定

```powershell
# 1. 載入兩個 image
docker load -i pdf-check-offline.tar
docker load -i mineru-api_pipeline.tar

# 2. 啟動
docker compose up -d

# 3. 還原模型快取（僅首次需要）
docker run --rm -v backend_hf_cache_minerU:/data -v ${PWD}:/backup alpine sh -c "cd /data && tar xzf /backup/hf_cache_backup.tgz"
```

完成後即可在離線環境使用 `http://localhost:8001`。

---

## 硬體資源監控

系統內建資源監控，每次 PDF 比對任務會自動記錄 CPU、記憶體使用率和處理時間。

### 查看資源使用記錄

```
# 最近 50 筆比對任務的資源使用摘要
GET http://localhost:8001/api/system/resource-logs

# 單一任務的詳細監控資料（含每 2 秒的 CPU/RAM 取樣）
GET http://localhost:8001/api/system/resource-logs/{task_id}
```

### 回傳資料範例

```json
{
  "task_id": "abc-123",
  "elapsed_seconds": 31.2,
  "peak_memory_mb": 2450.3,
  "avg_cpu_percent": 185.0,
  "peak_cpu_percent": 340.0,
  "system_info": {
    "platform": "Linux-5.15.0-aarch64",
    "architecture": "aarch64",
    "cpu_count": 4,
    "total_memory_gb": 24.0
  }
}
```

### 平台規劃建議

| 規格 | 最低可用 | 建議 | 多人/多任務 |
|------|----------|------|-------------|
| CPU | 4 核心 | 8 核心 | 12+ 核心 |
| RAM | 16 GB | 24 到 32 GB | 48 到 64 GB |
| 磁碟 | 120 GB SSD | 512 GB SSD | 1 TB NVMe |
| 架構 | x86_64 / ARM64 均可 | x86_64 / ARM64 均可 | x86_64 優先，ARM64 可用 |

| 平台 | 建議 |
|------|------|
| macOS | Mac mini M4 24GB/512GB 是起點；M4 Pro 48GB/1TB 適合長期開發與回歸 |
| Windows 10/11 | 建議 8 核以上、32GB RAM、1TB NVMe，使用 WSL2 + Docker Desktop |
| Windows Server | 不建議直接用 Docker Desktop；請在 Hyper-V/VMware 建 Ubuntu VM，再於 VM 內部署 |
| Linux / OCI | 正式服務首選；8 vCPU/32GB/512GB 起，長期主力用 12+ vCPU/64GB/1TB |

> **ARM64 注意事項**：Docling 和 PyMuPDF 都支援 ARM64 (aarch64)。Apple Silicon 與 OCI Ampere A1 實測可跑，但 MinerU / OCR 仍是 CPU-heavy；首次 model download 或 image build 會較慢。若要跨架構打包，才需要明確使用 `--platform linux/arm64` 或 `linux/amd64`。
> **CPU Torch 注意事項**：正式 CPU 映像必須使用 PyTorch 官方 CPU wheel，版本應帶 `+cpu`。若映像內顯示 `+cu`，代表誤裝 CUDA wheel，不得部署至 OCI CPU 主機。
> **PaddleOCR 實驗版注意事項**：開啟後會多一次 PDF rasterize + OCR inference，CPU-only 環境會增加處理時間與記憶體峰值。第一階段建議 `PADDLE_OCR_MAX_PAGES=20`、`PADDLE_OCR_DPI=200`，並先在 8 vCPU / 32GB RAM 以上測試。

---

## 帳號管理

- 預設管理員帳號：`admin`
- 系統採固定本機管理員登入設定，不會產生 `/app/runtime/.initial_admin_password`，也不會在 log 或畫面顯示初始密碼資訊。
- 啟動時會確保 `admin` 帳號存在、啟用且具管理員權限。
- 若正式環境要改成非固定密碼，需調整後端 `ensure_default_admin()` 的啟動策略。
- 管理員可在 `/admin` 頁面新增/編輯/停用審核人員帳號
- 審核操作會自動記錄登入帳號的顯示名稱

---

## 聯絡

有問題回報時請附上：
- `docker compose logs backend-minerU | tail -200` 輸出
- 觸發問題的 PDF（若可）
- Docker 版本：`docker version`
- 硬體資源 log：`curl http://localhost:8001/api/system/resource-logs`
