"""Offline check of the MixMedia node code: prompt building + execute() wiring, no API calls."""
import importlib.util
import os
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
COMFYUI = Path(os.environ.get("COMFYUI_DIR", ROOT / "comfyui")).resolve()
sys.path.insert(0, str(COMFYUI))

NODES = ROOT / "custom_nodes/comfyui-mixmedia/nodes.py"
if not NODES.exists():  # when the tools live next to a real ComfyUI checkout
    NODES = COMFYUI / "custom_nodes/comfyui-mixmedia/nodes.py"

spec = importlib.util.spec_from_file_location("mixmedia_nodes", NODES)
mm = importlib.util.module_from_spec(spec)
sys.modules["mixmedia_nodes"] = mm
spec.loader.exec_module(mm)

calls = []


def fake_upload_batch(images, key, urls):
    if images is None:
        return 0
    urls.extend(f"https://fake/{i}.png" for i in range(images.shape[0]))
    return images.shape[0]


def fake_generate(model, prompt, urls, aspect, resolution, fmt, key, timeout):
    calls.append({"prompt": prompt, "refs": len(urls), "model": model, "res": resolution})
    return torch.zeros((1, 8, 8, 3)), "fake"


mm._upload_batch = fake_upload_batch
mm._generate = fake_generate
mm.resolve_api_key = lambda explicit="": "fake"

img = torch.zeros((1, 8, 8, 3))

# 1. shot: refs only, no pose text
out = mm.MixmediaShot.execute(img, "nano-banana-pro", 7, "4:5", "2K", "png")
print("--- shot, refs only")
print(out[2])

# 2. shot: refs + own pose text + studio brief
studio = mm.MixmediaStudio.execute(
    "", "full body", "three-quarter left", "eye level", "85mm",
    "softbox at 45 degrees from camera left", "neutral 5600K", "soft",
    "grey cyclorama", "a wooden stool", "text, logos", "")
print("\n--- studio block")
print(studio[0])

out = mm.MixmediaShot.execute(img, "nano-banana-pro", 7, "4:5", "2K", "png",
                              outfit=img, location=img, pose="сидит на подоконнике, колени к груди",
                              direction=studio[0])
print("\n--- shot prompt with pose text + studio")
print(out[2])

# 3. shot: separate headwear ref, no pose
out = mm.MixmediaShot.execute(img, "nano-banana-pro", 7, "4:5", "2K", "png",
                              outfit=img, headwear=img)
print("\n--- shot prompt with headwear ref")
print(out[2])

# 4. picker "(нет)" -> empty batch, no crash
picked = mm.MixmediaPick.execute("(нет)")
print("\n--- picker none -> tensor", tuple(picked[0].shape))
out = mm.MixmediaShot.execute(img, "nano-banana-pro", 5, "4:5", "2K", "png",
                              outfit=img, headwear=picked[0])
print(out[2])

# 5. retake
out = mm.MixmediaRetake.execute(img, 20, 15, -10, "135mm", "a bit more shadow on the face",
                                "nano-banana-pro", 1, "auto", "2K", "png")
print("\n--- retake prompt")
print(out[2])

print("\n--- calls:", [(c["model"], c["refs"], c["res"]) for c in calls])
