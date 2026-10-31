"""ComfyUI nodes for the MixMedia API (https://mixmedia.tech).

`nano-banana-pro` is Google Gemini 3 Pro Image (Nano Banana Pro),
`nano-banana-2` is Nano Banana 2.1, plus GPT Image / Seedream / Flux.

The API is asynchronous: POST /jobs/createTask, then poll /jobs/recordInfo and
download the result URL. Model input accepts only https links, so images coming
from ComfyUI are uploaded to MixMedia first (POST /files/upload).
"""

import json
import logging
import os
import time
from io import BytesIO
from pathlib import Path

import comfy.utils
import folder_paths
from comfy_execution.graph_utils import ExecutionBlocker
import numpy as np
import requests
import torch
from PIL import Image, ImageOps

from comfy_api.latest import ComfyExtension, io

log = logging.getLogger("mixmedia")

API_BASE = os.environ.get("MIXMEDIA_API_BASE", "https://mixmedia.tech/api/v1").rstrip("/")

MODELS = [
    "nano-banana-pro",
    "nano-banana-2",
    "nano-banana",
    "gpt-image-2.5",
    "seedream-pro",
    "seedream-flash",
    "flux-dev",
]
ASPECTS = [
    "auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9",
    "1:3", "3:1", "2:1", "1:2", "9:21", "1:4", "4:1", "1:8", "8:1",
]
RESOLUTIONS = ["0.5K", "1K", "1.5K", "2K", "4K"]
FORMATS = ["png", "jpg"]

# what each model actually accepts (docs.mixmedia.tech model pages)
MODEL_SPECS = {
    "nano-banana-pro": {
        "res": ["1K", "2K", "4K"],
        "aspects": ["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
        "refs": 8,
    },
    "nano-banana-2": {
        "res": ["0.5K", "1K", "2K", "4K"],
        "aspects": ["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9",
                    "1:4", "4:1", "1:8", "8:1"],
        "refs": 10,
    },
    "nano-banana": {
        "res": ["1K", "2K"],
        "aspects": ["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
        "refs": 10,
    },
    "gpt-image-2.5": {
        "res": ["1K", "2K", "4K"],
        "aspects": ["auto", "1:1", "1:3", "3:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5", "16:9", "9:16",
                    "2:1", "1:2", "21:9", "9:21"],
        "refs": 16,
    },
    "seedream-pro": {
        "res": ["1K", "1.5K", "2K"],
        "aspects": ["auto", "1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "2:1", "1:2", "21:9"],
        "refs": 10,
    },
    "seedream-flash": {
        "res": ["1K", "1.5K", "2K"],
        "aspects": ["auto", "1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "2:1", "1:2", "21:9"],
        "refs": 10,
    },
    "flux-dev": {
        "res": None,  # flux-dev has no resolution parameter
        "aspects": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9", "9:21", "4:5", "5:4"],
        "refs": 0,  # text-to-image only
    },
}


# --------------------------------------------------------------------------- key


def _key_files():
    here = Path(__file__).resolve()
    # .../comfyui/custom_nodes/comfyui-mixmedia/nodes.py
    for base in (here.parents[2], here.parents[3], Path.home()):
        yield base / ".mixmedia_key"
        yield base / "mixmedia_key.txt"


def resolve_api_key(explicit: str = "") -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    env = os.environ.get("MIXMEDIA_API_KEY", "").strip()
    if env:
        return env
    for path in _key_files():
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    raise RuntimeError(
        "MixMedia API key not found: put it into ~/.mixmedia_key (or .mixmedia_key next to the ComfyUI folder), "
        "set MIXMEDIA_API_KEY, or paste it into the api_key field."
    )


# --------------------------------------------------------------------------- http


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _check(resp: requests.Response) -> dict:
    try:
        body = resp.json()
    except ValueError:
        raise RuntimeError(f"MixMedia HTTP {resp.status_code}: {resp.text[:300]}") from None
    code = body.get("code", resp.status_code)
    if code != 200:
        msg = body.get("msg") or body.get("error") or "unknown error"
        raise RuntimeError(f"MixMedia {code}: {msg}")
    return body


def _retry_sleep(attempt: int) -> None:
    time.sleep(min(2 ** attempt, 15))


def _request(method: str, url: str, *, attempts: int = 6, **kwargs) -> requests.Response:
    """HTTP with retries. A dropped connection must never kill an already paid generation."""
    last = None
    for attempt in range(attempts):
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.RequestException as exc:
            last = exc
            log.warning("MixMedia network error (%s/%s): %s", attempt + 1, attempts, exc)
            _retry_sleep(attempt)
            continue
        if resp.status_code >= 500:
            last = RuntimeError(f"MixMedia HTTP {resp.status_code}: {resp.text[:200]}")
            log.warning("MixMedia server error (%s/%s): HTTP %s", attempt + 1, attempts, resp.status_code)
            _retry_sleep(attempt)
            continue
        return resp
    raise RuntimeError(f"MixMedia {method.upper()} {url} failed after {attempts} attempts: {last}")


def upload_image(data: bytes, mime: str, key: str) -> str:
    resp = _request(
        "POST",
        f"{API_BASE}/files/upload",
        headers=_headers(key),
        files={"file": ("ref.png", data, mime)},
        timeout=180,
    )
    return _check(resp)["data"]["url"]


def create_task(payload: dict, key: str) -> str:
    resp = _request("POST", f"{API_BASE}/jobs/createTask", headers=_headers(key), json=payload, timeout=180)
    data = _check(resp).get("data") or {}
    task_id = data.get("taskId") or data.get("task_id")
    if not task_id:
        raise RuntimeError(f"MixMedia returned no taskId: {data}")
    return task_id


def wait_task(task_id: str, key: str, timeout: float, on_tick=None) -> dict:
    deadline = time.time() + timeout
    errors = 0
    while time.time() < deadline:
        if on_tick is not None:
            on_tick()
        url = f"{API_BASE}/jobs/recordInfo"
        params = {"taskId": task_id}
        try:
            resp = requests.get(url, headers=_headers(key), params=params, timeout=60)
        except requests.RequestException as exc:
            resp, failure = None, exc
        else:
            failure = f"HTTP {resp.status_code}" if resp.status_code >= 500 else None
        if failure is not None:
            errors += 1
            log.warning("MixMedia polling hiccup #%s (%s) — retrying, the task is already paid", errors, failure)
            time.sleep(min(3 + errors, 15))
            continue
        errors = 0
        data = _check(resp).get("data") or {}
        state = str(data.get("state") or data.get("status") or "").lower()
        if state in ("success", "completed"):
            return data
        if state in ("fail", "failed"):
            raise RuntimeError(f"MixMedia task {task_id} failed: {data.get('failMsg') or data.get('error') or state}")
        time.sleep(4)
    raise TimeoutError(
        f"MixMedia task {task_id} did not answer within {int(timeout)}s. The task is already paid: "
        f"its result lives 24 hours, fetch it with tools/fetch_task.py {task_id} (or raise timeout_sec)."
    )


def get_balance(key: str) -> float:
    resp = _request("GET", f"{API_BASE}/user/balance", headers=_headers(key), timeout=60)
    return float(_check(resp)["data"]["balance"])


# --------------------------------------------------------------------------- helpers


def _tensor_to_png(tensor: torch.Tensor) -> bytes:
    arr = (tensor.detach().cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    if arr.ndim == 4:
        arr = arr[0]
    buf = BytesIO()
    Image.fromarray(arr, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def _url_to_tensor(url: str) -> torch.Tensor:
    resp = _request("GET", url, attempts=5, timeout=180)
    resp.raise_for_status()
    img = Image.open(BytesIO(resp.content)).convert("RGB")
    return torch.from_numpy(np.asarray(img).astype(np.float32) / 255.0)[None,]


def _result_urls(data: dict) -> list[str]:
    raw = data.get("resultJson") or {}
    if isinstance(raw, str):
        raw = json.loads(raw) if raw.strip() else {}
    urls = list(raw.get("resultUrls") or raw.get("result_urls") or [])
    if not urls and isinstance(raw.get("url"), str):
        urls = [raw["url"]]
    return urls


def _split_urls(text: str) -> list[str]:
    return [chunk.strip() for chunk in (text or "").replace(",", "\n").splitlines() if chunk.strip()]


def _k(value: str) -> float:
    return float(value.rstrip("Kk"))


def _ratio(value: str) -> float:
    try:
        w, h = value.split(":")
        return float(w) / float(h)
    except (ValueError, ZeroDivisionError):
        return 1.0  # "auto" and friends have no ratio


def _fit(model: str, resolution: str, aspect: str) -> tuple[str, str]:
    """Clamp resolution/aspect_ratio to what the selected model accepts."""
    spec = MODEL_SPECS.get(model)
    if spec is None:
        return resolution, aspect

    if spec["res"] is not None and resolution not in spec["res"]:
        fitted = min(spec["res"], key=lambda r: abs(_k(r) - _k(resolution)))
        log.warning("%s does not support resolution %s, using %s", model, resolution, fitted)
        resolution = fitted
    if aspect not in spec["aspects"]:
        candidates = [a for a in spec["aspects"] if a != "auto"]
        if aspect == "auto" or not candidates:
            fitted = "1:1" if "1:1" in spec["aspects"] else candidates[0]
        else:
            fitted = min(candidates, key=lambda a: abs(_ratio(a) - _ratio(aspect)))
        log.warning("%s does not support aspect_ratio %s, using %s", model, aspect, fitted)
        aspect = fitted
    return resolution, aspect


def _batch_len(images) -> int:
    if images is None:
        return 0
    return images.shape[0] if images.ndim == 4 else 1


def _take(images, count: int):
    if images is None or count <= 0:
        return None
    batch = images if images.ndim == 4 else images[None]
    return batch[:count]


def _trim_counts(counts: list[int], budget: int) -> list[int]:
    """Keep the request inside the model limit: extra identity photos go first,
    then headwear, location, outfit, and only then the last identity shots."""
    counts = list(counts)
    total = sum(counts)
    while total > budget and counts[0] > 2:
        counts[0] -= 1
        total -= 1
    for i in (3, 2, 1):
        while total > budget and counts[i] > 0:
            counts[i] -= 1
            total -= 1
    while total > budget and counts[0] > 0:
        counts[0] -= 1
        total -= 1
    return counts


def _upload_batch(images, key: str, urls: list[str]) -> int:
    """Upload a ComfyUI IMAGE batch, append links to `urls`, return how many were added."""
    if images is None:
        return 0
    batch = images if images.ndim == 4 else images[None]
    for i in range(batch.shape[0]):
        urls.append(upload_image(_tensor_to_png(batch[i]), "image/png", key))
    return batch.shape[0]


def _dump_prompt(prompt: str) -> None:
    """Keep every prompt next to the results: output/_prompts/<date-time>.txt."""
    try:
        folder = os.path.join(folder_paths.get_output_directory(), "_prompts")
        os.makedirs(folder, exist_ok=True)
        name = time.strftime("%Y%m%d-%H%M%S") + ".txt"
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(prompt + "\n")
    except Exception:  # never fail a paid generation because of the log file
        log.warning("could not save the prompt to output/_prompts", exc_info=True)


def _generate(model: str, prompt: str, urls: list[str], aspect: str, resolution: str,
              fmt: str, key: str, timeout: float) -> tuple[torch.Tensor, str]:
    limit = MODEL_SPECS.get(model, {}).get("refs", 8)
    if len(urls) > limit:
        raise ValueError(f"{model} accepts at most {limit} reference images, got {len(urls)}")

    resolution, aspect = _fit(model, resolution, aspect)
    payload = {"model": model, "input": {"prompt": prompt, "aspect_ratio": aspect, "output_format": fmt}}
    if MODEL_SPECS.get(model, {}).get("res") is not None:
        payload["input"]["resolution"] = resolution
    if urls:
        payload["input"]["image_input"] = urls

    _dump_prompt(prompt)

    pbar = comfy.utils.ProgressBar(100)
    pbar.update(5)
    task_id = create_task(payload, key)
    log.info("task %s: %s, %s, refs=%s", task_id, model, resolution, len(urls))
    pbar.update(10)
    try:
        data = wait_task(task_id, key, timeout, on_tick=lambda: pbar.update(min(pbar.current + 7, 90)))
        pbar.update(95)

        result = _result_urls(data)
        if not result:
            raise RuntimeError(f"MixMedia task {task_id} finished without result URLs: {data}")
        tensors = [_url_to_tensor(url) for url in result]
    except Exception:
        log.error("this task is already paid: taskId=%s — результат живёт 24 ч, забрать: "
                  "python tools/fetch_task.py %s", task_id, task_id)
        raise
    image = torch.cat(tensors, dim=0) if len(tensors) > 1 else tensors[0]
    pbar.update(100)

    cost = data.get("creditsConsumed", "?")
    try:
        balance = f"${get_balance(key):.4f}"
    except (requests.RequestException, RuntimeError, KeyError, TypeError, ValueError):
        balance = "?"
    info = f"taskId={task_id} model={model} resolution={resolution} refs={len(urls)} cost=${cost} balance={balance}"
    log.info("%s", info)
    return image, info


def _range(start: int, count: int) -> str:
    return f"image {start}" if count == 1 else f"images {start}-{start + count - 1}"


# --------------------------------------------------------------------------- prompts

FRAMINGS = ["auto", "wide", "full body", "three-quarter", "waist", "bust", "close-up", "detail"]
FRAMING_TEXT = {
    "wide": "wide framing, the model small inside the space",
    "full body": "full-body framing, head to toe, space above the head",
    "three-quarter": "three-quarter framing, down to the knees",
    "waist": "waist-up framing",
    "bust": "bust framing, head and shoulders",
    "close-up": "close-up of the face",
    "detail": "tight detail shot of the outfit",
}

ANGLES = ["auto", "front", "three-quarter left", "three-quarter right", "profile left", "profile right",
          "from behind", "from above"]
ANGLE_TEXT = {
    "front": "camera straight in front of the model",
    "three-quarter left": "camera three-quarter left of the model",
    "three-quarter right": "camera three-quarter right of the model",
    "profile left": "camera at the left profile of the model",
    "profile right": "camera at the right profile of the model",
    "from behind": "camera behind the model",
    "from above": "camera above the model, looking straight down",
}

CAMERA_HEIGHTS = ["auto", "floor level", "eye level", "above the head"]
HEIGHT_TEXT = {
    "floor level": "lens near the floor, looking up",
    "eye level": "lens at eye level",
    "above the head": "lens above the head, looking down",
}

LENSES = ["auto", "16mm", "24mm", "35mm", "50mm", "85mm", "135mm", "200mm", "100mm macro"]
LENS_TEXT = {
    "16mm": "16mm ultra-wide lens, strong perspective",
    "24mm": "24mm wide lens",
    "35mm": "35mm lens",
    "50mm": "50mm lens",
    "85mm": "85mm lens",
    "135mm": "135mm lens, compressed background",
    "200mm": "200mm telephoto, heavy background compression",
    "100mm macro": "100mm macro lens, extreme detail",
}

LIGHT_SETUPS = [
    "auto",
    "softbox at 45 degrees from camera left",
    "two softboxes, key and fill",
    "single hard light from camera right",
    "window light",
    "ring light on the lens axis",
    "backlit with a rim",
    "golden hour sun",
    "overcast daylight",
    "beauty dish overhead",
]
LIGHT_TEMPS = ["auto", "warm 3200K", "neutral 5600K", "cool 7500K"]
LIGHT_CONTRASTS = ["auto", "soft", "medium", "hard"]
BACKDROPS = ["auto", "grey cyclorama", "white cyclorama", "black seamless", "paper sweep",
             "no backdrop, use the location"]


def _slot_lines(counts) -> list:
    """Only the wiring: which attached photo is the person, the clothes, the place, the headwear."""
    clothes = "the clothes — dress the person in exactly these pieces"
    if len(counts) < 4 or not counts[3]:
        clothes += ", including the headwear if the photos show one"
    roles = (
        "the person — exact face, hair, body proportions",
        clothes,
        "the place — put the person inside this exact space and light",
        "the headwear — put exactly this piece on the person's head, "
        "same shape, colour and material, at the same angle",
    )
    lines, idx = [], 1
    for role, count in zip(roles, counts):
        if count:
            rng = f"image {idx}" if count == 1 else f"images {idx}-{idx + count - 1}"
            lines.append(f"{rng}: {role}")
            idx += count
    return lines


def shot_prompt(counts, pose_text, direction) -> str:
    blocks = []
    lines = _slot_lines(counts)
    if lines:
        blocks.append("Compose one new photo from these references:\n" + "\n".join(lines))
    if pose_text and pose_text.strip():
        blocks.append(f"POSE — {pose_text.strip()}")
    if direction and direction.strip():
        blocks.append(direction.strip())
    if not blocks:
        raise ValueError("nothing to send: hook a reference image, or fill MixMedia Studio / MixMedia Direction")
    return "\n\n".join(blocks)


def studio_prompt(text, framing, angle, camera_height, lens, light_setup, light_temp, light_contrast,
                  backdrop, props, avoid, direction="") -> str:
    blocks = []
    camera = [FRAMING_TEXT.get(framing), ANGLE_TEXT.get(angle), HEIGHT_TEXT.get(camera_height), LENS_TEXT.get(lens)]
    camera = [c for c in camera if c]
    if camera:
        blocks.append("CAMERA — " + ", ".join(camera) + ".")

    light = [x for x in (light_setup if light_setup != "auto" else "",
                         light_temp if light_temp != "auto" else "",
                         light_contrast if light_contrast != "auto" else "") if x]
    if light:
        blocks.append("LIGHT — " + ", ".join(light) + ".")

    set_parts = []
    if backdrop != "auto":
        set_parts.append(f"backdrop: {backdrop}")
    if props and props.strip():
        set_parts.append(f"add to the frame: {props.strip()}")
    if avoid and avoid.strip():
        set_parts.append(f"never show: {avoid.strip()}")
    if set_parts:
        blocks.append("SET — " + "; ".join(set_parts) + ".")

    if text and text.strip():
        blocks.append(f"BRIEF — {text.strip()}")
    if direction and direction.strip():
        blocks.append(direction.strip())
    return "\n\n".join(blocks)


def retake_prompt(turn, zoom, camera_height, lens, text) -> str:
    moves = []
    if abs(turn) >= 1:
        side = "left" if turn > 0 else "right"
        moves.append(f"orbit {abs(turn):.0f} degrees to the {side} around the model")
    if abs(zoom) >= 1:
        moves.append(f"dolly {abs(zoom):.0f}% {'closer to' if zoom > 0 else 'farther from'} the model")
    if abs(camera_height) >= 1:
        moves.append(f"{'raise' if camera_height > 0 else 'lower'} the camera {abs(camera_height):.0f} degrees")
    if lens != "auto":
        moves.append(f"change the lens to a {LENS_TEXT[lens]}")
    blocks = [
        "Same photo: same person, same clothes, same pose, same light. Change only the camera — "
        + ("; ".join(moves) if moves else "keep the framing as it is") + "."
    ]
    if text and text.strip():
        blocks.append(f"ALSO — {text.strip()}")
    return "\n\n".join(blocks)


def character_prompt(identity: int, look: str) -> str:
    blocks = [
        "Character turnaround sheet: ONE single image, a clean 2x2 grid of four panels, no text, no labels, "
        "no borders between panels.",
        "Panels: top-left front view, top-right three-quarter view, bottom-left profile view, "
        "bottom-right full-body front view.",
        "The same person in all four panels: identical face, hairstyle, hair colour, skin tone, body proportions "
        f"and clothing. Keep the identity of the person in {_range(1, identity)}: bone structure, eye shape and "
        "spacing, nose, lips, jawline, ears, skin tone and texture, hairstyle, hairline and facial hair. "
        "Do not beautify, slim, age or stylize the face.",
        "Neutral relaxed expression, arms down, plain light-grey seamless background in every panel, even soft "
        "studio light from camera left, 85mm, sharp focus on the eyes, natural skin texture with pores, "
        "photorealistic, no AI gloss, no watermark.",
        "This sheet will be reused as the identity reference for a photoshoot, so all four views must show the "
        "same recognizable person with a fully visible, evenly lit face.",
    ]
    if look.strip():
        blocks.append(f"LOOK — {look.strip()}")
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- nodes


class MixmediaImage(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MixmediaImage",
            display_name="MixMedia Image",
            category="api/mixmedia",
            description="Nano Banana Pro / 2.1 / GPT Image / Seedream / Flux через MixMedia API",
            not_idempotent=True,
            inputs=[
                io.String.Input(
                    "prompt",
                    multiline=True,
                    default="",
                    tooltip="Что сгенерировать или что изменить на референсах",
                ),
                io.Combo.Input("model", options=MODELS, default="nano-banana-pro"),
                io.Int.Input(
                    "seed",
                    default=0,
                    min=0,
                    max=0xFFFFFFFFFFFFFFFF,
                    control_after_generate=True,
                    tooltip="MixMedia не принимает seed: значение только сбрасывает кэш ComfyUI, "
                    "чтобы каждый запуск был новым кадром",
                ),
                io.Combo.Input("aspect_ratio", options=ASPECTS, default="4:5"),
                io.Combo.Input("resolution", options=RESOLUTIONS, default="2K"),
                io.Combo.Input("output_format", options=FORMATS, default="png"),
                io.Image.Input("images", optional=True, tooltip="Референсы из ComfyUI"),
                io.String.Input(
                    "reference_urls",
                    multiline=True,
                    default="",
                    optional=True,
                    tooltip="Готовые https-ссылки на фото, по одной в строке (вместо images)",
                ),
                io.String.Input(
                    "api_key",
                    default="",
                    optional=True,
                    tooltip="Оставь пустым: ключ берётся из ~/.mixmedia_key или MIXMEDIA_API_KEY",
                ),
                io.Int.Input("timeout_sec", default=900, min=30, max=1800, optional=True, advanced=True),
            ],
            outputs=[
                io.Image.Output("image"),
                io.String.Output("info"),
            ],
        )

    @classmethod
    def execute(cls, prompt, model, seed, aspect_ratio, resolution, output_format,
                images=None, reference_urls="", api_key="", timeout_sec=300):
        if not prompt or not prompt.strip():
            raise ValueError("prompt is empty")
        if api_key.strip():
            log.warning("api_key is set in the node, so it will be saved into the workflow JSON. "
                        "Leave it empty: the key is read from .mixmedia_key")

        key = resolve_api_key(api_key)
        urls = _split_urls(reference_urls)
        _upload_batch(images, key, urls)
        image, info = _generate(model, prompt.strip(), urls, aspect_ratio, resolution,
                                output_format, key, float(timeout_sec))
        return io.NodeOutput(image, info)


class MixmediaShot(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MixmediaShot",
            display_name="MixMedia Shot",
            category="api/mixmedia",
            description="Один кадр: референсы + бриф из MixMedia Studio, без встроенного промпта",
            not_idempotent=True,
            inputs=[
                io.Image.Input("identity", tooltip="Персонаж: character sheet или 1-6 фото лица"),
                io.Boolean.Input(
                    "run",
                    default=True,
                    label_on="ЭТАП ВКЛЮЧЁН",
                    label_off="этап выключен",
                    tooltip="Выключенный этап не выполняется и не тратит деньги",
                ),
                io.Combo.Input("model", options=MODELS, default="nano-banana-pro"),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF, control_after_generate=True,
                             tooltip="MixMedia seed не принимает; в ноде только сбрасывает кэш ComfyUI"),
                io.Combo.Input("aspect_ratio", options=ASPECTS, default="4:5"),
                io.Combo.Input("resolution", options=RESOLUTIONS, default="2K"),
                io.Combo.Input("output_format", options=FORMATS, default="png"),
                io.String.Input("pose", multiline=True, default="",
                                tooltip="Поза словами: «сидит на полу, колени к груди». Пусто — не упоминать"),
                io.Image.Input("outfit", optional=True, tooltip="Одежда, 1-4 фото (лучше на человеке, не flat-lay)"),
                io.Image.Input("location", optional=True, tooltip="Локация, 1 фото"),
                io.Image.Input("headwear", optional=True,
                               tooltip="Головной убор, 1 фото. Пусто — берётся с фото одежды"),
                io.String.Input("direction", multiline=True, default="", optional=True,
                                tooltip="Выход MixMedia Studio: камера, свет, объекты, бриф"),
                io.String.Input("api_key", default="", optional=True,
                                tooltip="Оставь пустым: ключ берётся из .mixmedia_key"),
                io.Int.Input("timeout_sec", default=900, min=30, max=1800, optional=True, advanced=True),
            ],
            outputs=[
                io.Image.Output("image"),
                io.String.Output("info"),
                io.String.Output("prompt"),
            ],
        )

    @classmethod
    def execute(cls, identity, run, model, seed, aspect_ratio, resolution, output_format,
                outfit=None, location=None, headwear=None, pose="", direction="",
                api_key="", timeout_sec=300):
        if not run:
            log.warning("MixMedia Shot выключен (run = этап выключен) — этап пропущен, денег не тратит, ошибки нет")
            return io.NodeOutput(ExecutionBlocker(None))
        if api_key.strip():
            log.warning("api_key is set in the node, so it will be saved into the workflow JSON. "
                        "Leave it empty: the key is read from .mixmedia_key")

        key = resolve_api_key(api_key)

        counts = [_batch_len(identity), _batch_len(outfit), _batch_len(location), _batch_len(headwear)]
        budget = MODEL_SPECS.get(model, {}).get("refs", 8)
        fitted = _trim_counts(counts, budget)
        if fitted != counts:
            log.warning("%s accepts %s reference images, dropping extras: %s -> %s",
                        model, budget, counts, fitted)
        identity, outfit, location, headwear = (
            _take(identity, fitted[0]), _take(outfit, fitted[1]),
            _take(location, fitted[2]), _take(headwear, fitted[3]),
        )

        urls: list[str] = []
        _upload_batch(identity, key, urls)
        _upload_batch(outfit, key, urls)
        _upload_batch(location, key, urls)
        _upload_batch(headwear, key, urls)

        prompt = shot_prompt(fitted, pose, direction)
        log.info("shot prompt:\n%s", prompt)
        image, info = _generate(model, prompt, urls, aspect_ratio, resolution,
                                output_format, key, float(timeout_sec))
        return io.NodeOutput(image, info, prompt)


class MixmediaStudio(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MixmediaStudio",
            display_name="MixMedia Studio",
            category="api/mixmedia",
            description="Камера, свет, объектив, фон и объекты: собирает бриф для MixMedia Shot",
            inputs=[
                io.String.Input("text", multiline=True, default="",
                                tooltip="Свободный бриф: настроение, стиль, что важно в кадре"),
                io.Combo.Input("framing", options=FRAMINGS, default="auto",
                               tooltip="Крупность плана"),
                io.Combo.Input("angle", options=ANGLES, default="auto",
                               tooltip="Откуда снимает камера"),
                io.Combo.Input("camera_height", options=CAMERA_HEIGHTS, default="auto",
                               tooltip="Высота камеры относительно модели"),
                io.Combo.Input("lens", options=LENSES, default="auto",
                               tooltip="Объектив и перспектива"),
                io.Combo.Input("light_setup", options=LIGHT_SETUPS, default="auto",
                               tooltip="Схема света"),
                io.Combo.Input("light_temp", options=LIGHT_TEMPS, default="auto",
                               tooltip="Цветовая температура"),
                io.Combo.Input("light_contrast", options=LIGHT_CONTRASTS, default="auto",
                               tooltip="Жёсткость светотени"),
                io.Combo.Input("backdrop", options=BACKDROPS, default="auto",
                               tooltip="Фон. С локацией не дружит — выбирай что-то одно"),
                io.String.Input("props", multiline=True, default="",
                                tooltip="Что добавить в кадр: стул, цветы, дым, машина"),
                io.String.Input("avoid", multiline=True, default="",
                                tooltip="Чего в кадре быть не должно"),
                io.String.Input("direction", multiline=True, default="", optional=True,
                                tooltip="Выход MixMedia Direction: текст + два слайдера"),
            ],
            outputs=[
                io.String.Output("direction"),
            ],
        )

    @classmethod
    def execute(cls, text, framing, angle, camera_height, lens, light_setup, light_temp,
                light_contrast, backdrop, props, avoid, direction=""):
        return io.NodeOutput(studio_prompt(text, framing, angle, camera_height, lens, light_setup,
                                           light_temp, light_contrast, backdrop, props, avoid, direction))


class MixmediaRetake(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MixmediaRetake",
            display_name="MixMedia Retake",
            category="api/mixmedia",
            description="Докрутить камеру готового кадра: поворот, зум, высота, объектив",
            not_idempotent=True,
            inputs=[
                io.Image.Input("image", tooltip="Кадр, который докручиваем"),
                io.Boolean.Input(
                    "run",
                    default=True,
                    label_on="ЭТАП ВКЛЮЧЁН",
                    label_off="этап выключен",
                    tooltip="Выключенный этап не выполняется и не тратит деньги",
                ),
                io.Float.Input("turn", default=0.0, min=-90.0, max=90.0, step=5.0,
                               tooltip="Поворот камеры вокруг модели: + влево, − вправо, в градусах"),
                io.Float.Input("zoom", default=0.0, min=-50.0, max=50.0, step=5.0,
                               tooltip="+ ближе, − дальше, в процентах"),
                io.Float.Input("camera_height", default=0.0, min=-30.0, max=30.0, step=5.0,
                               tooltip="+ поднять камеру, − опустить, в градусах"),
                io.Combo.Input("lens", options=LENSES, default="auto",
                               tooltip="Сменить оптику на этом же кадре"),
                io.String.Input("text", multiline=True, default="",
                                tooltip="Любая правка: свет, выражение, детали"),
                io.Combo.Input("model", options=MODELS, default="nano-banana-pro"),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF, control_after_generate=True,
                             tooltip="Только сбрасывает кэш ComfyUI"),
                io.Combo.Input("aspect_ratio", options=ASPECTS, default="auto"),
                io.Combo.Input("resolution", options=RESOLUTIONS, default="2K"),
                io.Combo.Input("output_format", options=FORMATS, default="png"),
                io.String.Input("api_key", default="", optional=True,
                                tooltip="Оставь пустым: ключ берётся из .mixmedia_key"),
                io.Int.Input("timeout_sec", default=900, min=30, max=1800, optional=True, advanced=True),
            ],
            outputs=[
                io.Image.Output("image"),
                io.String.Output("info"),
                io.String.Output("prompt"),
            ],
        )

    @classmethod
    def execute(cls, image, run, turn, zoom, camera_height, lens, text, model, seed, aspect_ratio,
                resolution, output_format, api_key="", timeout_sec=300):
        if not run:
            log.warning("MixMedia Retake выключен (run = этап выключен) — этап пропущен, денег не тратит, ошибки нет")
            return io.NodeOutput(ExecutionBlocker(None))
        if api_key.strip():
            log.warning("api_key is set in the node, so it will be saved into the workflow JSON. "
                        "Leave it empty: the key is read from .mixmedia_key")

        key = resolve_api_key(api_key)
        urls: list[str] = []
        if not _upload_batch(image, key, urls):
            raise ValueError("image is required")

        prompt = retake_prompt(turn, zoom, camera_height, lens, text)
        log.info("retake prompt:\n%s", prompt)
        image, info = _generate(model, prompt, urls, aspect_ratio, resolution,
                                output_format, key, float(timeout_sec))
        return io.NodeOutput(image, info, prompt)


NO_REF = "(нет)"


def _input_files() -> list:
    try:
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        files = folder_paths.filter_files_content_types(files, ["image"])
    except Exception:  # pragma: no cover - input folder may be missing
        files = []
    return [NO_REF] + sorted(files)


class MixmediaPick(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MixmediaPick",
            display_name="MixMedia Ref (пусто = нет)",
            category="api/mixmedia",
            description="Референс из папки input: «(нет)» значит картинки нет и вход остаётся пустым",
            inputs=[
                io.Combo.Input(
                    "file",
                    options=_input_files(),
                    default=NO_REF,
                    upload=io.UploadType.image,
                    image_folder=io.FolderType.input,
                    tooltip="Файл из input или «(нет)». Загрузить новый — кнопкой на виджете",
                ),
            ],
            outputs=[
                io.Image.Output("image"),
            ],
        )

    @classmethod
    def execute(cls, file):
        if not file or file == NO_REF:
            log.info("no reference picked, sending an empty image")
            return io.NodeOutput(torch.zeros((0, 64, 64, 3), dtype=torch.float32))

        path = folder_paths.get_annotated_filepath(file)
        img = ImageOps.exif_transpose(Image.open(path))
        if img.mode == "I":
            img = img.point(lambda i: i * (1 / 255))
        arr = np.asarray(img.convert("RGB")).astype(np.float32) / 255.0
        return io.NodeOutput(torch.from_numpy(arr)[None,])


class MixmediaCharacter(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MixmediaCharacter",
            display_name="MixMedia Character Reference",
            category="api/mixmedia",
            description="Собирает чистый портрет-референс личности из 2-4 фото — его потом кидай в identity",
            not_idempotent=True,
            inputs=[
                io.Image.Input("identity", tooltip="2-4 фото лица: фронт, три четверти, профиль"),
                io.Boolean.Input(
                    "run",
                    default=True,
                    label_on="ЭТАП ВКЛЮЧЁН",
                    label_off="этап выключен",
                    tooltip="Выключенный этап не выполняется и не тратит деньги",
                ),
                io.String.Input(
                    "look",
                    multiline=True,
                    default="",
                    optional=True,
                    tooltip="Описание внешности: причёска, борода, телосложение и т.п.",
                ),
                io.Combo.Input("model", options=MODELS, default="nano-banana-pro"),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF, control_after_generate=True,
                             tooltip="Только сбрасывает кэш ComfyUI"),
                io.Combo.Input("aspect_ratio", options=ASPECTS, default="4:5"),
                io.Combo.Input("resolution", options=RESOLUTIONS, default="2K"),
                io.Combo.Input("output_format", options=FORMATS, default="png"),
                io.String.Input("api_key", default="", optional=True,
                                tooltip="Оставь пустым: ключ берётся из .mixmedia_key"),
                io.Int.Input("timeout_sec", default=900, min=30, max=1800, optional=True, advanced=True),
            ],
            outputs=[
                io.Image.Output("image"),
                io.String.Output("info"),
            ],
        )

    @classmethod
    def execute(cls, identity, run, look, model, seed, aspect_ratio, resolution, output_format,
                api_key="", timeout_sec=300):
        if not run:
            log.warning("MixMedia Character выключен (run = этап выключен) — этап пропущен, денег не тратит, ошибки нет")
            return io.NodeOutput(ExecutionBlocker(None))
        if api_key.strip():
            log.warning("api_key is set in the node, so it will be saved into the workflow JSON. "
                        "Leave it empty: the key is read from .mixmedia_key")

        key = resolve_api_key(api_key)
        urls: list[str] = []
        n_identity = _upload_batch(identity, key, urls)
        if not n_identity:
            raise ValueError("identity photos are required")

        prompt = character_prompt(n_identity, look or "")
        image, info = _generate(model, prompt, urls, aspect_ratio, resolution,
                                output_format, key, float(timeout_sec))
        return io.NodeOutput(image, info)


DIRECTION_HEADER = "DIRECTION — {text}"

DETAIL_BANDS = (
    (0.34, "LOW DETAIL EMPHASIS — keep surfaces and accessories plain, follow the references and do not invent "
           "micro-details."),
    (0.67, "MEDIUM DETAIL EMPHASIS — render the details described in the brief, but nothing beyond the references."),
    (1.01, "HIGH DETAIL EMPHASIS — every described detail must be rendered precisely: fabric weave, stitching, "
           "hardware, prints, jewellery, makeup, individual hair strands."),
)

CONTEXT_BANDS = (
    (0.34, "LOW CONTEXT EMPHASIS — the location reference defines the scene, the brief only sets the mood."),
    (0.67, "MEDIUM CONTEXT EMPHASIS — keep the brief and the references in balance."),
    (1.01, "HIGH CONTEXT EMPHASIS — the brief defines the scene and mood; take only identity and wardrobe "
           "from the references."),
)


def _band(value: float, bands) -> str:
    for limit, text in bands:
        if value < limit:
            return text
    return bands[-1][1]


class MixmediaDirection(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MixmediaDirection",
            display_name="MixMedia Direction",
            category="api/mixmedia",
            description="Текст-бриф + две ручки: насколько бриф задаёт контекст и насколько — детали",
            inputs=[
                io.String.Input("text", multiline=True, default="",
                                tooltip="Свободный бриф: настроение, стиль, что важно в кадре"),
                io.Float.Input("context_strength", default=0.5, min=0.0, max=1.0, step=0.05,
                               tooltip="0 — сцену задают референсы локации/позы, 1 — сцену задаёт бриф"),
                io.Float.Input("detail_strength", default=0.5, min=0.0, max=1.0, step=0.05,
                               tooltip="0 — детали берутся с референсов, 1 — детали берутся из брифа"),
            ],
            outputs=[
                io.String.Output("direction"),
            ],
        )

    @classmethod
    def execute(cls, text, context_strength=0.5, detail_strength=0.5):
        if not text or not text.strip():
            return io.NodeOutput("")
        block = "\n".join([
            DIRECTION_HEADER.format(text=text.strip()),
            _band(context_strength, CONTEXT_BANDS),
            _band(detail_strength, DETAIL_BANDS),
        ])
        return io.NodeOutput(block)


class MixmediaBalance(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MixmediaBalance",
            display_name="MixMedia Balance",
            category="api/mixmedia",
            description="Текущий баланс MixMedia в долларах",
            is_output_node=True,
            not_idempotent=True,
            inputs=[
                io.String.Input("api_key", default="", optional=True),
            ],
            outputs=[
                io.Float.Output("balance_usd"),
                io.String.Output("text"),
            ],
        )

    @classmethod
    def execute(cls, api_key=""):
        balance = get_balance(resolve_api_key(api_key))
        text = f"MixMedia balance: ${balance:.4f}"
        log.info("%s", text)
        return io.NodeOutput(balance, text)


class MixmediaExtension(ComfyExtension):
    async def get_node_list(self):
        return [MixmediaImage, MixmediaShot, MixmediaStudio, MixmediaRetake, MixmediaPick,
                MixmediaCharacter, MixmediaDirection, MixmediaBalance]


async def comfy_entrypoint() -> MixmediaExtension:
    return MixmediaExtension()
