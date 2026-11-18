# 📚 RAG 文件問答（PWA / RWD 版）

上傳 PDF / DOCX，選擇檢索策略後直接對文件提問。
**Gradio + FastAPI + ChromaDB + Groq**，可安裝成手機 / 桌面 App（PWA），並針對手機、平板、桌機做了響應式版面（RWD）。

## 功能

- 8 種檢索策略：混合（RRF）、語意、關鍵字（字元 n-gram）、LLM 重排、多查詢、壓縮、父子文檔、HyDE
- 回答附 `[片段n]` 引用，可展開檢視檢索到的原文片段
- 問答紀錄匯出 Word / CSV
- **多使用者隔離**：每個瀏覽器 session 各自的文件與問答紀錄，互不覆蓋，閒置後自動釋放
- **API Key 安全**：伺服器 Key 只存在後端環境變數，不會送到瀏覽器；使用者也可填自己的 Key
- **PWA**：Web App Manifest、Service Worker、離線提示頁、安裝按鈕（iOS 有加入主畫面提示）
- **RWD**：桌機雙欄 → 平板 → 手機單欄；觸控目標 ≥ 44px、輸入列黏底、支援瀏海安全區與橫放

## 專案結構

```
app.py              FastAPI + Gradio 介面；提供 manifest / sw.js / 離線頁 / 健康檢查
rag_core.py         RAG 核心（載入、切塊、檢索、生成），與 UI 無關
static/             PWA 資產：manifest、sw.js、offline.html、pwa.js、style.css（RWD）、icons/
scripts/            make_icons.py（重製圖示）、download_model.py（建置時預載模型）
tests/              煙霧測試（不需網路與模型）
render.yaml         Render Blueprint
requirements.txt    執行期相依
```

## 本機執行

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export GROQ_API_KEY=gsk_xxx        # 選填；不設則在網頁上填 Key
python app.py                       # → http://localhost:7860
```

> PWA 的 Service Worker 需要 HTTPS，`localhost` 例外，所以本機也能測試安裝。
> 首次啟動會下載嵌入模型（約 470 MB）。

測試：`pip install -r requirements-dev.txt && python -m pytest -q`

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `GROQ_API_KEY` | （空） | 伺服器預設 Key。使用者留空時使用 |
| `APP_PASSWORD` | （空） | **有設才啟用登入**。有放 `GROQ_API_KEY` 的公開網站強烈建議設定 |
| `APP_USERNAME` | `admin` | 登入帳號 |
| `EMBED_MODEL` | `intfloat/multilingual-e5-small` | 可換 `intfloat/multilingual-e5-base`、`BAAI/bge-m3`（更吃記憶體） |
| `MAX_UPLOAD_MB` | `20` | 上傳大小上限 |
| `MAX_CHUNKS` | `4000` | 單檔片段數上限（保護記憶體與 CPU） |
| `SESSION_TTL_MIN` | `180` | 文件在 session 閒置多久後釋放（分鐘） |
| `CONCURRENCY` | `2` | 同時處理的請求數，其餘排隊 |
| `PORT` | `7860` | Render 會自動帶入 |

## 上傳到 GitHub

```bash
cd rag-pwa
git init && git add . && git commit -m "RAG PWA"
git branch -M main
git remote add origin https://github.com/<你的帳號>/<repo名稱>.git
git push -u origin main
```
`.gitignore` 已排除 `.env`、模型快取與暫存檔，**不要把 API Key 寫進程式碼或提交 `.env`**。

## 部署到 Render

### 方式一：Blueprint（推薦）
1. Render Dashboard → **New → Blueprint** → 選你的 GitHub repo，Render 會讀取 `render.yaml`
2. 依提示填入 `GROQ_API_KEY`（選填）與 `APP_PASSWORD`（建議）
3. 等待建置完成，開啟 `https://<服務名>.onrender.com`

### 方式二：手動建立 Web Service
| 欄位 | 值 |
|---|---|
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt && python scripts/download_model.py` |
| Start Command | `uvicorn app:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips "*"` |
| Health Check Path | `/healthz` |
| Environment | `PYTHON_VERSION=3.11.11`、`HF_HOME=/opt/render/project/src/.hf_cache`、`TOKENIZERS_PARALLELISM=false` 及上表變數 |

### ⚠️ 選哪個方案？（重點）
Render 各方案的記憶體：Free 512 MB、Starter 512 MB、**Standard 2 GB**。
torch + 多語言嵌入模型載入後遠超 512 MB，所以 **`render.yaml` 預設用 Standard（US$25／月）**；Free / Starter 很可能在載入模型時被 OOM 終止。
想免費的話，可考慮 Hugging Face Spaces（免費方案記憶體較大），本專案的 Gradio 部分可直接沿用。

其他注意：
- 檔案系統是暫存的，重新部署或重啟後向量庫清空（本專案為記憶體模式，使用者重新上傳即可）
- Free 方案閒置 15 分鐘會休眠，喚醒後首次請求較慢
- 嵌入模型在建置階段預先下載，執行期會在背景暖機，因此服務啟動後數十秒內第一次上傳可能稍慢

## 安裝成 App（PWA）

| 平台 | 方式 |
|---|---|
| Android / Chrome、桌面 Chrome / Edge | 畫面右下角的「📲 安裝 App」，或瀏覽器網址列的安裝圖示 |
| iPhone / iPad（Safari） | 分享 → **加入主畫面**（首次造訪會跳出提示） |

離線時開啟會顯示離線頁；**問答本身需要連線**（檢索在伺服器、生成用 Groq）。
Service Worker 只快取前端靜態檔（`/assets/`、`/pwa/`），**不會快取頁面與 API**，所以不會有舊版畫面或回答卡住的問題。
更新前端資源後，把 `static/sw.js` 的 `VERSION` 改一下即可讓使用者換新快取。

可用 Chrome DevTools → Lighthouse / Application → Manifest 驗證 PWA 狀態。

## 常見問題

- **部署後 Key 驗證失敗**：Key 需為 Groq 的 `gsk_` 開頭；預設模型清單可能與你的帳號不同，Key 驗證成功後會自動換成實際可用的模型清單。
- **掃描檔 PDF**：沒有文字層，需先 OCR。
- **要換 UI 語言文字**（例如上傳區的 “Drop File Here”）：目前沿用 Gradio 內建英文，可用 `gr.I18n` 客製。
- **Gradio 6**：本專案鎖定 Gradio 5（`requirements.txt`），升級需把 `css` / `theme` / `head` 移到 `launch()` / `mount_gradio_app()`。
