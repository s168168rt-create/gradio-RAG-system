"""RAG 文件問答 — FastAPI + Gradio（PWA / RWD 版）

啟動：
    本機   python app.py
    Render uvicorn app:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips "*"
"""
from __future__ import annotations

import csv
import os
import re
import tempfile
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import gradio as gr
from docx import Document
from docx.shared import Pt, RGBColor
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from rag_core import MODELS, RAG, SERVER_KEY, STRATEGIES, list_models

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
SESSION_TTL = int(os.getenv("SESSION_TTL_MIN", "180")) * 60  # session 文件閒置多久後釋放（分鐘）

rag = RAG()

# ═══════════════ Gradio 介面 ═══════════════
HEAD = """
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#10b981" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f172a" media="(prefers-color-scheme: dark)">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="RAG 問答">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="application-name" content="RAG 問答">
<link rel="icon" type="image/png" sizes="64x64" href="/pwa/icons/favicon-64.png">
<link rel="apple-touch-icon" href="/pwa/icons/apple-touch-icon.png">
<script src="/pwa/pwa.js" defer></script>
"""
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
THEME = gr.themes.Soft(primary_hue="emerald", neutral_hue="slate", radius_size="lg",
                       font=[gr.themes.GoogleFont("Noto Sans TC"), "sans-serif"])


def on_key(key, cur):
    """套用 / 驗證 Key；留空則使用伺服器預設 Key（若有設定）。回傳 (狀態, 模型下拉, Key state)。"""
    key = (key or "").strip()
    eff = key or SERVER_KEY
    if not eff:
        return "⚠ 尚未設定 Key（請輸入你的 Groq API Key）", gr.update(), key
    ms = list_models(eff)
    if not ms:
        return "✗ Key 無效或無法取得模型", gr.update(), key
    who = "你的 Key" if key else "伺服器預設 Key"
    pick = cur if cur in ms else (MODELS[0] if MODELS[0] in ms else ms[0])
    return f"✓ 使用{who} · {len(ms)} 個模型", gr.update(choices=ms, value=pick), key


def on_upload(f, old):
    if f is None:
        yield "⚠ 請選擇檔案", old
        return
    yield "⏳ 解析並建立索引中…（首次使用需載入嵌入模型，可能需數十秒）", old
    doc, msg = rag.load(f if isinstance(f, str) else f.name, old)
    yield msg, (doc or old)


def on_ask(q, history, records, doc, key, strategy, k, model):
    q = (q or "").strip()
    if not q:
        return "", history, gr.update(), records
    ans, src = rag.answer(doc, q, strategy, k, model, key)
    records = records + [{
        "時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "文件": doc.name if doc else "",
        "問題": q, "回答": re.sub(r"\n*<sub>.*?</sub>", "", ans, flags=re.S).strip(),
        "策略": STRATEGIES[strategy][0], "模型": model or MODELS[0],
        "參考片段": src.split("─" * 40, 1)[-1].strip()}]
    return "", history + [{"role": "user", "content": q}, {"role": "assistant", "content": ans}], src, records


# ── 匯出：Word / CSV ──
def _out_path(ext):
    d = tempfile.mkdtemp(prefix="rag_")  # 每次獨立目錄，多人同時匯出不會撞檔
    return os.path.join(d, f"RAG問答紀錄_{datetime.now():%Y%m%d_%H%M%S}.{ext}")


def export_csv(records):
    if not records:
        gr.Warning("目前沒有問答紀錄可匯出")
        return None
    path = _out_path("csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig：Excel 開啟中文不亂碼
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)
    return path


def _md_runs(par, text):  # 將 **粗體** 轉成 Word 粗體
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if part:
            par.add_run(part).bold = bool(i % 2)


def export_docx(records, with_src=True):
    if not records:
        gr.Warning("目前沒有問答紀錄可匯出")
        return None
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Microsoft JhengHei", Pt(11)
    st.element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "Microsoft JhengHei")
    doc.add_heading("RAG 文件問答紀錄", 0)
    meta = doc.add_paragraph(f"文件：{records[-1]['文件']}　·　匯出時間：{datetime.now():%Y-%m-%d %H:%M}　·　共 {len(records)} 題")
    meta.runs[0].font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
    for n, r in enumerate(records, 1):
        doc.add_heading(f"Q{n}．{r['問題']}", level=1)
        info = doc.add_paragraph(f"{r['時間']}　·　{r['策略']}　·　{r['模型']}")
        info.runs[0].font.size, info.runs[0].font.color.rgb = Pt(9), RGBColor(0x6B, 0x72, 0x80)
        for line in r["回答"].splitlines():
            line = line.rstrip()
            if not line.strip():
                continue
            if m := re.match(r"^\s*#{1,6}\s+(.*)", line):
                doc.add_heading(m.group(1).replace("**", ""), level=2)
                continue
            if m := re.match(r"^(\s*)[-*•]\s+(.*)", line):
                par = doc.add_paragraph(style="List Bullet 2" if len(m.group(1)) >= 2 else "List Bullet")
                _md_runs(par, m.group(2))
            elif m := re.match(r"^\s*\d+[.)]\s+(.*)", line):
                par = doc.add_paragraph(style="List Number")
                _md_runs(par, m.group(1))
            else:
                _md_runs(doc.add_paragraph(), line)
        if with_src and r["參考片段"]:
            h = doc.add_paragraph()
            run = h.add_run("參考片段")
            run.bold, run.font.size = True, Pt(9)
            for blk in r["參考片段"].split("\n\n"):
                p = doc.add_paragraph(blk.strip())
                p.paragraph_format.left_indent = Pt(12)
                for run in p.runs:
                    run.font.size, run.font.color.rgb = Pt(8.5), RGBColor(0x55, 0x5B, 0x66)
    path = _out_path("docx")
    doc.save(path)
    return path


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="RAG 文件問答", theme=THEME, css=CSS, head=HEAD, analytics_enabled=False) as demo:
        gr.HTML("<div id='hdr'><h1>📚 RAG 文件問答</h1>"
                "<p>上傳 PDF / DOCX，選擇檢索策略，直接提問 · Groq × ChromaDB</p></div>")
        with gr.Row(equal_height=False, elem_id="main"):
            with gr.Column(scale=1, min_width=300, elem_classes="side"):
                with gr.Accordion("🔑 Groq API Key", open=not SERVER_KEY):
                    key = gr.Textbox(type="password", show_label=False, placeholder="gsk_…（Enter 套用）" if not SERVER_KEY
                                     else "留空＝使用伺服器預設 Key；也可填入自己的 Key")
                    key_status = gr.Markdown("")
                model = gr.Dropdown(MODELS, value=MODELS[0], allow_custom_value=True, label="模型")
                file = gr.File(label="上傳文件", file_types=[".pdf", ".docx"], type="filepath", height=120)
                status = gr.Textbox(show_label=False, interactive=False, lines=2, placeholder="尚未載入文件")
                strategy = gr.Radio([(v[0], k) for k, v in STRATEGIES.items()], value="hybrid", label="檢索策略",
                                    elem_id="strategy")
                desc = gr.Markdown(f"<small>{STRATEGIES['hybrid'][1]}</small>")
                topk = gr.Slider(1, 10, 4, step=1, label="片段數量 Top-K")
            with gr.Column(scale=2, min_width=300, elem_id="chat-col"):
                chat = gr.Chatbot(type="messages", height="60vh", show_label=False, elem_id="chat",
                                  placeholder="**上傳文件後開始提問**<br>例如：這份文件的重點是什麼？")
                with gr.Row(elem_id="qrow"):
                    q = gr.Textbox(show_label=False, placeholder="輸入問題，Enter 送出", scale=6, container=False,
                                   autofocus=False, max_lines=4)
                    send = gr.Button("送出", variant="primary", scale=1, elem_id="send")
                with gr.Row(elem_id="tools"):
                    gr.Examples([["這份文件的重點是什麼？"], ["文件提到哪些規定或限制？"], ["有哪些風險或注意事項？"]], q, label=None)
                    clear = gr.Button("🗑 清除對話", size="sm", variant="secondary")
                with gr.Accordion("🔎 檢索到的片段", open=False):
                    src = gr.Textbox(show_label=False, lines=12, interactive=False)
                with gr.Row(elem_id="export-row"):
                    with_src = gr.Checkbox(True, label="Word 包含參考片段", scale=2)
                    btn_docx = gr.Button("📄 匯出 Word", size="sm", scale=1)
                    btn_csv = gr.Button("📊 匯出 CSV", size="sm", scale=1)
                out_file = gr.File(label="下載檔案", visible=False)

        # 每個瀏覽器 session 各自一份狀態：文件、Key、問答紀錄
        doc = gr.State(None, time_to_live=SESSION_TTL, delete_callback=rag.drop)
        api_key = gr.State("")
        records = gr.State([])

        demo.load(on_key, [key, model], [key_status, model, api_key])
        key.submit(on_key, [key, model], [key_status, model, api_key])
        key.blur(on_key, [key, model], [key_status, model, api_key])
        file.upload(on_upload, [file, doc], [status, doc])
        strategy.change(lambda s: f"<small>{STRATEGIES[s][1]}</small>", strategy, desc)
        for ev in (q.submit, send.click):
            ev(on_ask, [q, chat, records, doc, api_key, strategy, topk, model], [q, chat, src, records])
        clear.click(lambda: ([], "", [], gr.update(value=None, visible=False)), None, [chat, src, records, out_file])
        show = lambda p: gr.update(value=p, visible=bool(p))
        btn_docx.click(lambda r, w: show(export_docx(r, w)), [records, with_src], out_file)
        btn_csv.click(lambda r: show(export_csv(r)), records, out_file)
    # 嵌入為 CPU 密集：限制同時處理數，其餘排隊，避免記憶體暴衝
    return demo.queue(default_concurrency_limit=int(os.getenv("CONCURRENCY", "2")), max_size=40)


# ═══════════════ FastAPI：PWA 路由 + 掛載 Gradio ═══════════════
@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("WARMUP", "1") == "1":  # 背景預載嵌入模型：port 立即可用，首次上傳不必久等
        threading.Thread(target=rag.warmup, daemon=True).start()
    yield


api = FastAPI(title="RAG 文件問答", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@api.get("/healthz", include_in_schema=False)
def healthz():
    return JSONResponse({"status": "ok", "embedder_ready": rag.ready})


@api.get("/manifest.webmanifest", include_in_schema=False)
@api.get("/manifest.json", include_in_schema=False)  # Gradio 的頁面樣板固定有 <link rel="manifest" href="/manifest.json">，在此一併回應
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@api.get("/sw.js", include_in_schema=False)
def service_worker():  # 必須由根路徑提供，才能控制整個網站範圍
    return FileResponse(STATIC / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@api.get("/offline.html", include_in_schema=False)
def offline():
    return FileResponse(STATIC / "offline.html", media_type="text/html", headers={"Cache-Control": "no-cache"})


api.mount("/pwa", StaticFiles(directory=STATIC), name="pwa")  # 圖示、pwa.js

_user, _pass = os.getenv("APP_USERNAME", "admin"), os.getenv("APP_PASSWORD", "")
app = gr.mount_gradio_app(
    api, build_ui(), path="/",
    auth=(_user, _pass) if _pass else None,   # 設了 APP_PASSWORD 就要求登入（保護伺服器預設 Key）
    max_file_size=f"{int(os.getenv('MAX_UPLOAD_MB', '20'))}mb",
    ssr_mode=False,
    pwa=False,  # 關閉 Gradio 內建 PWA（會注入自己的 /manifest.json），改用我們的 manifest + Service Worker
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")))
