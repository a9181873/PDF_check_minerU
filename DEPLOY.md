# PDF 比對系統 - 部署指南

保險 DM 雙版本 PDF 比對工具（FastAPI 後端 + React 前端）。

---

## 系統需求

- **Windows 10/11、macOS 或 Linux**
- **Docker Desktop**（Windows/Mac 需手動安裝，Linux 可用 `docker` + `docker compose` plugin）
  - Docker 官方下載：<https://www.docker.com/products/docker-desktop/>
  - 安裝完首次啟動後，需等 whale icon 從「Starting」轉為「Running」
- **硬碟空間**：建議 80 GB 以上（MinerU 模型、PDF 上傳、封存與快照會持續累積）
- **RAM**：單人/輕量測試 16 GB 起；3 人同時操作建議 24 GB 以上

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
```
看到 `Loaded image: pdf-check-backend:1.0` 即成功（約 30 秒 - 2 分鐘）。

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

### 表格與大面積版面變更處理
最新版的比對引擎（Phase 4）會自動偵測差異區塊大小。
- **純文字/小區塊**：透過 OCR 與原生文字層進行比對，過濾字型抗鋸齒雜訊。
- **大面積/表格（>8000px²）**：直接判定為「表格/版面變更」，會產生高解析度 (2x) 的截圖供雙邊對照，不再強制進行 OCR（避免表格結構產生亂碼）。

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

### 準備階段（需要網路）

```powershell
# 1. Build Docker image
docker compose build

# 2. 啟動並執行一次 PDF 比對（觸發 Docling 模型下載到 HF cache）
docker compose up -d
# 上傳任意 PDF 做一次比對，等比對完成後模型已快取

# 3. 匯出 Docker image
docker save pdf-check-backend:latest -o pdf-check-offline.tar

# 4. 匯出模型快取 volume
docker run --rm -v backend_hf_cache_minerU:/data -v ${PWD}:/backup alpine tar czf /backup/hf_cache_backup.tgz -C /data .
```

### 離線環境部署

將以下檔案帶到離線環境：
- `pdf-check-offline.tar` — Docker image
- `hf_cache_backup.tgz` — Docling 模型快取
- `docker-compose.yml` — 啟動設定

```powershell
# 1. 載入 image
docker load -i pdf-check-offline.tar

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

### OCI ARM / 筆電規劃建議

| 規格 | 最低可用 | 建議 | 多人/多任務 |
|------|----------|------|-------------|
| CPU | 2 核心 | 4 核心 | 8+ 核心 |
| RAM | 16 GB | 24 GB | 32+ GB |
| 磁碟 | 20 GB SSD | 40 GB SSD | 100 GB SSD |
| 架構 | x86_64 / ARM64 均可 | — | — |

> **ARM64 注意事項**：Docling 和 PyMuPDF 都支援 ARM64 (aarch64)。Docker build 時需使用 `--platform linux/arm64`。OCI Ampere A1 (ARM) 實測可正常運行，但首次 model download 較慢。

---

## 帳號管理

- 預設管理員帳號: `admin` / `admin123`
- **首次登入後請立即修改密碼**
- 管理員可在 `/admin` 頁面新增/編輯/停用審核人員帳號
- 審核操作會自動記錄登入帳號的顯示名稱

---

## 聯絡

有問題回報時請附上：
- `docker compose logs backend-minerU | tail -200` 輸出
- 觸發問題的 PDF（若可）
- Docker 版本：`docker version`
- 硬體資源 log：`curl http://localhost:8001/api/system/resource-logs`
