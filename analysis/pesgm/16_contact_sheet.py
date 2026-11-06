"""Item 16 - contact sheet of every PNG figure in figs/ with its file name.

Writes figs/contact_sheet.png (skips the full-page dashboard capture).
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FIGS = Path(__file__).resolve().parent / "figs"
CELL_W, CELL_H, LABEL_H, COLS = 700, 620, 44, 4


def main():
    files = sorted(p for p in FIGS.glob("*.png") if p.stem not in ("contact_sheet", "_dashboard_full"))
    rows = -(-len(files) // COLS)
    sheet = Image.new("RGB", (COLS * CELL_W, rows * (CELL_H + LABEL_H)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
    for i, p in enumerate(files):
        im = Image.open(p).convert("RGB")
        im.thumbnail((CELL_W - 24, CELL_H - 16))
        x = (i % COLS) * CELL_W
        y = (i // COLS) * (CELL_H + LABEL_H)
        sheet.paste(im, (x + (CELL_W - im.width) // 2, y + 8 + (CELL_H - 16 - im.height) // 2))
        draw.rectangle([x + 4, y + 4, x + CELL_W - 4, y + CELL_H + LABEL_H - 4], outline="#c8c6c0", width=2)
        draw.text((x + 14, y + CELL_H + 4), p.name, fill="#0b0b0b", font=font)
    sheet.save(FIGS / "contact_sheet.png")
    print(f"wrote figs/contact_sheet.png with {len(files)} figures ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()
