"""建置階段預先下載嵌入模型，執行期不必再連 Hugging Face。"""
import os
from sentence_transformers import SentenceTransformer

name = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")
SentenceTransformer(name, device="cpu")
print("✓ 已下載", name)
