"""Draw the app icon (1024px PNG) for the desktop bundle."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
BG_TOP = (43, 50, 64)
BG_BOTTOM = (14, 18, 24)
BODY = (242, 244, 248)
DARK = (16, 20, 26)
LENS = (86, 148, 255)
LENS_DEEP = (26, 82, 170)


def rounded(size, radius, fill=None):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=fill)
    return img


def main(out: Path):
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)) + (255,)
        gd.line([(0, y), (S, y)], fill=color)
    mask = rounded(S, 232, (255, 255, 255, 255))
    base.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(base)
    # camera body
    d.rounded_rectangle([176, 340, 848, 780], radius=64, fill=BODY)
    # viewfinder bump
    d.rounded_rectangle([392, 268, 632, 352], radius=34, fill=BODY)
    # lens
    cx, cy = 512, 566
    d.ellipse([cx - 168, cy - 168, cx + 168, cy + 168], fill=DARK)
    d.ellipse([cx - 132, cy - 132, cx + 132, cy + 132], fill=LENS)
    d.ellipse([cx - 132, cy - 20, cx + 132, cy + 132], fill=LENS_DEEP)
    d.ellipse([cx - 96, cy - 96, cx + 96, cy + 96], fill=DARK)
    d.ellipse([cx - 62, cy - 62, cx + 34, cy + 34], fill=(120, 178, 255, 210))
    # flash
    d.rounded_rectangle([716, 388, 792, 412], radius=12, fill=(255, 216, 120))
    base.save(out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
