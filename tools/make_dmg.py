"""Build the styled DMG installer: app on the left, Applications on the right."""
import subprocess
import sys
from pathlib import Path

import dmgbuild
from PIL import Image, ImageDraw, ImageFont

W, H = 660, 420
BG_TOP = (32, 38, 50)
BG_BOTTOM = (12, 15, 21)

FONTS = [
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def font(size):
    for path in FONTS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def background(out: Path) -> None:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        draw.line([(0, y), (W, y)],
                  fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)))

    title = font(30)
    sub = font(15)
    small = font(12)

    text = "ComfyUI MixMedia"
    tw = draw.textlength(text, font=title)
    draw.text(((W - tw) / 2, 44), text, font=title, fill=(246, 248, 252))
    text = "перетащи приложение в Applications"
    tw = draw.textlength(text, font=sub)
    draw.text(((W - tw) / 2, 88), text, font=sub, fill=(150, 160, 178))

    # arrow between the two icons
    y0, x0, x1 = 210, 265, 395
    draw.line([(x0, y0), (x1 - 16, y0)], fill=(86, 148, 255), width=4)
    draw.polygon([(x1, y0), (x1 - 20, y0 - 11), (x1 - 20, y0 + 11)], fill=(86, 148, 255))

    text = "фотостудия · nano banana pro · mixmedia api"
    tw = draw.textlength(text, font=small)
    draw.text(((W - tw) / 2, H - 34), text, font=small, fill=(96, 106, 124))
    img.save(out)


def main(app: str, dmg: str) -> None:
    app_path = Path(app).resolve()
    dmg_path = Path(dmg).resolve()
    bg = Path(dmg_path).parent / "dmg_background.png"
    background(bg)

    # hdiutil sizing: byte sum misses HFS+ per-file overhead on tens of thousands of
    # venv files, so ask for the payload size plus slack and let dmgbuild shrink it back.
    used_kb = int(subprocess.check_output(["du", "-sk", str(app_path)]).split()[0])
    size = f"{used_kb // 1024 + 2048}M"

    settings = {
        "size": size,
        "files": [str(app_path)],
        "symlinks": {"Applications": "/Applications"},
        "icon_locations": {
            app_path.name: (182, 210),
            "Applications": (478, 210),
        },
        "background": str(bg),
        "window_rect": ((120, 120), (W, H)),
        "default_view": "icon-view",
        "icon_size": 128,
        "text_size": 14,
        "label_pos": "bottom",
        "show_status_bar": False,
        "show_tab_view": False,
        "show_toolbar": False,
        "show_pathbar": False,
        "show_sidebar": False,
        "no_internet_enabled": True,
    }
    dmg_path.unlink(missing_ok=True)
    dmgbuild.build_dmg(str(dmg_path), "ComfyUI MixMedia", settings=settings)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
