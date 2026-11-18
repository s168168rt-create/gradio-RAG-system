"""煙霧測試：不需網路、不需下載嵌入模型（以假嵌入取代）。
執行：python -m pytest -q   或   python tests/test_smoke.py
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

os.environ["WARMUP"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from docx import Document
from fastapi.testclient import TestClient

import rag_core
from app import app, rag, export_csv, export_docx, on_ask, on_key, on_upload


class FakeEmbedder:
    """字元 bigram 雜湊成 256 維向量，足以讓語意檢索流程可跑通。"""
    max_seq_length = 512

    def encode(self, texts, **_):
        out = np.zeros((len(texts), 256))
        for r, t in enumerate(texts):
            t = t.replace("query: ", "").replace("passage: ", "")
            for a, b in zip(t, t[1:]):
                out[r, int(hashlib.md5((a + b).encode()).hexdigest(), 16) % 256] += 1
        n = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(n == 0, 1, n)


rag._embedder = FakeEmbedder()


def make_docx(path):
    d = Document()
    d.add_heading("退貨規定", 1)
    d.add_paragraph("消費者於收到商品後七日內得申請退貨，商品須保持全新未拆封。")
    d.add_paragraph("退款將於收到退貨後十個工作天內匯入原付款帳戶。")
    d.add_heading("保固條款", 1)
    d.add_paragraph("本產品提供一年保固，人為損壞不在保固範圍內。")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "項目", "期限"
    t.cell(1, 0).text, t.cell(1, 1).text = "退貨", "七日"
    d.save(path)


def test_pwa_routes_and_head():
    with TestClient(app) as c:
        assert c.get("/healthz").json()["status"] == "ok"
        m = c.get("/manifest.webmanifest")
        assert m.status_code == 200 and "manifest+json" in m.headers["content-type"]
        assert m.json()["display"] == "standalone" and len(m.json()["icons"]) >= 3
        assert c.get("/manifest.json").json() == m.json()  # Gradio 樣板內建的連結也要拿到同一份 manifest
        sw = c.get("/sw.js")
        assert sw.status_code == 200 and sw.headers["service-worker-allowed"] == "/"
        assert "javascript" in sw.headers["content-type"]
        assert c.get("/offline.html").status_code == 200
        for p in ("pwa.js", "icons/icon-192.png", "icons/icon-512.png", "icons/maskable-512.png", "icons/apple-touch-icon.png"):
            assert c.get(f"/pwa/{p}").status_code == 200, p
        html = c.get("/").text
        for needle in ('rel="manifest"', "/pwa/pwa.js", "apple-touch-icon", "theme-color"):
            assert needle in html, needle


def test_docx_load_and_strategies():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "規定.docx")
        make_docx(p)
        doc, msg = rag.load(p)
        assert doc and msg.startswith("✓"), msg
        assert any("表格" in l for l in doc.labels) and any(l == "保固條款" for l in doc.labels)
        llm = rag_core.LLM("", None)  # 無 Key：LLM 策略應優雅退回
        for s in rag_core.STRATEGIES:
            hits = rag.retrieve(doc, "退貨期限幾天", s, 3, llm)
            assert hits, s
        top = rag.retrieve(doc, "退貨期限", "tfidf", 1, llm)[0][1]
        assert "退貨" in top
        # 第二份文件載入後，舊文件的向量被清除；不同 session 的資料互不干擾
        doc2, _ = rag.load(p, old=doc)
        assert rag.col.get(where={"sid": doc.sid})["ids"] == []
        assert rag.col.get(where={"sid": doc2.sid})["ids"]
        rag.drop(doc2)
        assert rag.col.get(where={"sid": doc2.sid})["ids"] == []


def test_two_sessions_isolated():
    with tempfile.TemporaryDirectory() as td:
        a, b = os.path.join(td, "a.docx"), os.path.join(td, "b.docx")
        make_docx(a)
        d = Document(); d.add_paragraph("火星殖民計畫預計於二〇四〇年啟動。"); d.save(b)
        da, _ = rag.load(a)
        db, _ = rag.load(b)
        llm = rag_core.LLM("", None)
        assert all("火星" not in t for _, t in rag.retrieve(da, "火星殖民", "semantic", 5, llm))
        assert all("退貨" not in t for _, t in rag.retrieve(db, "退貨", "semantic", 5, llm))
        rag.drop(da); rag.drop(db)


def test_bad_files():
    with tempfile.TemporaryDirectory() as td:
        t = os.path.join(td, "x.txt"); Path(t).write_text("hi")
        assert rag.load(t)[0] is None
        from pypdf import PdfWriter
        pdf = os.path.join(td, "blank.pdf")
        w = PdfWriter(); w.add_blank_page(200, 200); w.write(pdf)
        doc, msg = rag.load(pdf)
        assert doc is None and "OCR" in msg


class _Msg:  # 假的 Groq 回應
    def __init__(self, text): self.message = type("M", (), {"content": text})()


def test_answer_with_fake_groq(monkeypatch=None):
    calls = []

    class FakeGroq:
        def __init__(self, api_key): self.chat = self; self.completions = self
        def create(self, **kw):
            calls.append(kw)
            last = kw["messages"][-1]["content"]
            if "相關度" in last: txt = "[2]: 9\n[1]: 3"
            else: txt = "- 七日內可退貨 [片段1]"
            return type("R", (), {"choices": [_Msg(txt)]})()

    orig, rag_core.Groq = rag_core.Groq, FakeGroq
    try:
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "規定.docx"); make_docx(p)
            doc, _ = rag.load(p)
            ans, src = rag.answer(doc, "退貨期限？", "rerank", 2, "openai/gpt-oss-20b", "gsk_fake")
            assert "七日內可退貨" in ans and "片段1" in src
            assert any(k.get("reasoning_effort") == "low" for k in calls)  # gpt-oss 參數有帶上
            assert "尚未設定" in rag.answer(doc, "x", "hybrid", 2, None, "")[0] if not rag_core.SERVER_KEY else True
            # UI handler + 匯出
            _, hist, _, recs = on_ask("退貨期限？", [], [], doc, "gsk_fake", "hybrid", 3, "openai/gpt-oss-20b")
            assert hist[-1]["role"] == "assistant" and recs[0]["文件"] == "規定.docx"
            for f in (export_csv(recs), export_docx(recs, True)):
                assert f and os.path.getsize(f) > 0
            assert rag.answer(None, "x", "hybrid", 2, None, "")[0].startswith("請先上傳")
            rag.drop(doc)
    finally:
        rag_core.Groq = orig


def test_upload_generator_and_key_handler():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "規定.docx"); make_docx(p)
        outs = list(on_upload(p, None))
        assert outs[0][0].startswith("⏳") and outs[-1][1] is not None
        rag.drop(outs[-1][1])
    st, _, k = on_key("", None)
    assert k == "" and ("尚未設定" in st or "伺服器預設" in st or "無效" in st)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("✓", n)
