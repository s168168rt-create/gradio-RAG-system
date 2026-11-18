"""產生 PWA 圖示（需要 Pillow）：python scripts/make_icons.py"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "static" / "icons"
SS = 4  # 超取樣倍率，邊緣更平滑


def gradient(size):
    img = Image.new("RGB", (size, size))
    px = img.load()
    c0, c1 = (52, 211, 153), (4, 120, 87)  # emerald-400 → emerald-700
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(c0, c1))
    return img


def draw_icon(size, scale, rounded):
    """scale：內容佔畫面比例（maskable 需留安全區，約 0.62）。"""
    n = size * SS
    bg = gradient(n).convert("RGBA")
    if rounded:
        mask = Image.new("L", (n, n), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, n - 1, n - 1), radius=int(n * 0.22), fill=255)
        bg.putalpha(mask)
    d = ImageDraw.Draw(bg)
    u = n * scale / 100  # 以 100 為單位的座標系
    ox = oy = n * (1 - scale) / 2
    P = lambda x, y: (ox + x * u, oy + y * u)
    # 文件本體（右上角摺角）
    fold = 22
    doc = [P(12, 4), P(78 - fold, 4), P(78, 4 + fold), P(78, 92), P(12, 92)]
    d.polygon(doc, fill=(255, 255, 255, 255))
    d.polygon([P(78 - fold, 4), P(78, 4 + fold), P(78 - fold, 4 + fold)], fill=(209, 250, 229, 255))
    for i, w in enumerate((46, 46, 30)):
        y = 40 + i * 14
        d.rounded_rectangle((*P(24, y), *P(24 + w, y + 6)), radius=u * 3, fill=(5, 150, 105, 255))
    # 放大鏡（代表檢索）
    d.ellipse((*P(52, 54), *P(88, 90)), fill=(16, 185, 129, 255), outline=(255, 255, 255, 255), width=int(u * 5))
    d.line((*P(80, 82), *P(95, 97)), fill=(255, 255, 255, 255), width=int(u * 7))
    return bg.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    draw_icon(192, 0.74, True).save(OUT / "icon-192.png")
    draw_icon(512, 0.74, True).save(OUT / "icon-512.png")
    draw_icon(512, 0.58, False).save(OUT / "maskable-512.png")   # 全版面背景 + 安全區內容
    draw_icon(180, 0.66, False).convert("RGB").save(OUT / "apple-touch-icon.png")
    draw_icon(64, 0.80, True).save(OUT / "favicon-64.png")
    print("icons →", OUT)


if __name__ == "__main__":
    main()
