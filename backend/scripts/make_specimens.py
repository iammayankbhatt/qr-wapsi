"""Generate fictional specimen ID images for the demo (Pillow only).

Run:  python scripts/make_specimens.py     (from backend/)
Outputs backend/demo_assets/{pan_sharp,pan_blurry,ovd_sharp,signboard_sample}.jpg

Everything here is invented: no government names, emblems or logos, and a large
"SPECIMEN — DEMO ONLY" watermark across each card.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "demo_assets"
W, H = 1000, 630
NAME = "RAMESH SHARMA"
PAN_NUMBER = "ABCPS1234K"  # fictional, matches ^[A-Z]{5}[0-9]{4}[A-Z]$
WATERMARK = "SPECIMEN — DEMO ONLY"

FONT_DIRS = ["C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu", "/Library/Fonts", "/System/Library/Fonts/Supplemental"]


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf", "Arial.ttf"]
    for d in FONT_DIRS:
        for n in names:
            if (Path(d) / n).exists():
                return ImageFont.truetype(str(Path(d) / n), size)
    return ImageFont.load_default(size)


def background(tint: tuple[int, int, int], seed: int) -> Image.Image:
    """Pale tinted card with fine wavy lines and speckle, so a sharp photo has real texture."""
    img = Image.new("RGB", (W, H), tint)
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    for k in range(0, H, 14):
        pts = [(x, k + 6 * math.sin(x / 38 + k / 11)) for x in range(0, W + 1, 8)]
        d.line(pts, fill=tuple(max(c - 14, 0) for c in tint), width=1)
    for _ in range(6000):
        x, y = rnd.randrange(W), rnd.randrange(H)
        v = rnd.randrange(-18, 8)
        d.point((x, y), fill=tuple(min(max(c + v, 0), 255) for c in tint))
    return img


def draw_photo_and_signature(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    d.rectangle([x, y, x + 230, y + 290], outline=(60, 60, 80), width=3, fill=(205, 210, 220))
    d.ellipse([x + 80, y + 55, x + 150, y + 125], fill=(130, 135, 150))  # head
    d.pieslice([x + 35, y + 140, x + 195, y + 330], 180, 360, fill=(130, 135, 150))  # shoulders
    d.text((x, y + 305), "Signature", font=font(20), fill=(70, 70, 90))
    sig = [(x + 5 + i * 9, y + 355 + 12 * math.sin(i * 0.9) * (1 - i / 30)) for i in range(26)]
    d.line(sig, fill=(25, 35, 120), width=3)


def pan_card() -> Image.Image:
    img = background((226, 236, 247), seed=1)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 92], fill=(30, 58, 120))
    d.text((40, 24), "PERMANENT ACCOUNT NUMBER CARD", font=font(40, True), fill="white")
    d.text((40, 100), "FICTIONAL DEMO CARD — NOT A REAL DOCUMENT", font=font(22), fill=(150, 40, 40))
    draw_photo_and_signature(d, 700, 150)
    rows = [("Name", NAME), ("Father's Name", "SURESH SHARMA"), ("Date of Birth", "01/01/1980"),
            ("Permanent Account Number", PAN_NUMBER)]
    y = 160
    for label, value in rows:
        d.text((40, y), label, font=font(24), fill=(70, 70, 95))
        big = label.startswith("Permanent")
        d.text((40, y + 30), value, font=font(54 if big else 38, True), fill=(10, 15, 40))
        y += 105 if big else 90
    return img


def ovd_card() -> Image.Image:
    img = background((240, 233, 218), seed=2)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 92], fill=(110, 70, 30))
    d.text((40, 24), "IDENTITY CARD", font=font(44, True), fill="white")
    d.text((40, 100), "FICTIONAL DEMO CARD — NOT A REAL DOCUMENT", font=font(22), fill=(150, 40, 40))
    draw_photo_and_signature(d, 700, 150)
    rows = [("Name", NAME), ("Date of Birth", "01/01/1980"), ("ID Number", "DEMO-0000-1234-5678"),
            ("Address", "Sector 62, Noida (fictional)")]
    y = 160
    for label, value in rows:
        d.text((40, y), label, font=font(24), fill=(80, 70, 55))
        d.text((40, y + 30), value, font=font(38, True), fill=(30, 20, 10))
        y += 100
    return img


def signboard() -> Image.Image:
    """Fictional shop front: a painted signboard over a shutter, as a field employee would photograph it."""
    img = Image.new("RGB", (W, H), (176, 170, 160))
    d = ImageDraw.Draw(img)
    rnd = random.Random(3)
    for y in range(300, H, 18):  # rolling shutter
        d.rectangle([80, y, W - 80, y + 12], fill=(150, 152, 158))
    d.rectangle([60, 60, W - 60, 280], fill=(196, 32, 38), outline=(120, 15, 20), width=8)
    d.text((W // 2, 140), "SHARMA KIRANA STORE", font=font(70, True), fill=(255, 236, 160), anchor="mm")
    d.text((W // 2, 220), "General Provisions  ·  Sector 62, Noida", font=font(34), fill="white", anchor="mm")
    for _ in range(4000):
        x, y = rnd.randrange(W), rnd.randrange(H)
        d.point((x, y), fill=(rnd.randrange(90, 200),) * 3)
    return img


def watermark(img: Image.Image) -> Image.Image:
    """Large semi-transparent diagonal text, repeated so no crop can remove it."""
    layer = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font(64, True)
    for oy in (-210, 0, 210):  # centred rows, rotated about the card centre
        d.text((W, H + oy), WATERMARK, font=f, fill=(200, 30, 30, 105), anchor="mm")
    layer = layer.rotate(28, resample=Image.BICUBIC)
    left, top = (layer.width - W) // 2, (layer.height - H) // 2
    layer = layer.crop((left, top, left + W, top + H))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def laplacian_variance(img: Image.Image) -> float:
    import numpy as np
    g = np.asarray(img.convert("L"), dtype=float)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pan = watermark(pan_card())
    pan.save(OUT_DIR / "pan_sharp.jpg", quality=93)
    pan.filter(ImageFilter.GaussianBlur(radius=7)).save(OUT_DIR / "pan_blurry.jpg", quality=93)
    watermark(ovd_card()).save(OUT_DIR / "ovd_sharp.jpg", quality=93)
    watermark(signboard()).save(OUT_DIR / "signboard_sample.jpg", quality=90)
    for name in ("pan_sharp", "pan_blurry", "ovd_sharp", "signboard_sample"):
        p = OUT_DIR / f"{name}.jpg"
        print(f"{p.name:16s} {p.stat().st_size // 1024:4d} KB   laplacian variance {laplacian_variance(Image.open(p)):9.1f}")


if __name__ == "__main__":
    main()
