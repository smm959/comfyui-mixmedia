# ComfyUI + MixMedia: a photo studio in nodes

Custom ComfyUI nodes for the [MixMedia API](https://mixmedia.tech) (`nano-banana-pro`, `nano-banana-2`,
`gpt-image-2.5`, `seedream`, `flux`) plus a ready-made photoshoot workflow:

**character sheet → shot (outfit, location, headwear, pose) → camera retake.**

The prompt is not one hardcoded wall of text: it is assembled from what you set with the widgets, every
block is visible in the log and in `output/_prompts/<date>.txt`, and nothing personal lives in the code.

<p align="center"><img src="assets/icon.png" width="140" alt="ComfyUI MixMedia"></p>

> Русская версия: [README.md](README.md)

The full manual lives in [README-ru.md](README-ru.md) (Russian): install, stages, the START button,
prices, troubleshooting, recovering a paid task, and building the app.

## Nodes

| Node | What it does |
|---|---|
| **MixMedia Character** | 2–6 face photos → one 2×2 character sheet (front, three-quarter, profile, full body) |
| **MixMedia Shot** | one frame: person + outfit + location + headwear + pose as text. Has no prompt of its own |
| **MixMedia Studio** | camera, light, lens, backdrop, props → the text brief for Shot |
| **MixMedia Retake** | move the camera of a finished frame: turn, zoom, height, lens |
| **MixMedia Ref** | a reference from `input` or `(none)` — an empty input does not break the run |
| **MixMedia Direction** | free brief + two sliders: context strength and detail strength |
| **MixMedia Image** | plain generation/editing: prompt + any references |
| **MixMedia Balance** | shows the account balance |

## How the prompt is built

`MixMedia Shot` only describes the role of each attached image; everything else comes from the other nodes:

```
Compose one new photo from these references:
image 1: the person — exact face, hair, body proportions
image 2: the clothes — dress the person in exactly these pieces, including the headwear if the photos show one
image 3: the place — put the person inside this exact space and light

POSE — sitting on a windowsill, knees to the chest

CAMERA — full-body framing, head to toe, camera three-quarter left of the model, lens at eye level, 85mm lens.
LIGHT — softbox at 45 degrees from camera left, neutral 5600K, soft.
SET — backdrop: grey cyclorama; add to the frame: a wooden stool; never show: text, logos.
BRIEF — calm expression, sharp eyes
```

* references are numbered automatically, roles get real numbers;
* `MixMedia Studio` adds only the values that are not `auto`;
* `pose` is free text: empty → no `POSE` block at all;
* `MixMedia Ref` set to `(none)` simply sends no image (a plain `LoadImage` cannot be left empty — it errors);
* the final prompt is exposed as the node's third output `prompt`, written to the log and to
  `output/_prompts/<date>.txt`.

## Install

1. Copy `custom_nodes/comfyui-mixmedia` into `<ComfyUI>/custom_nodes/`.
2. Put the MixMedia key into `~/.mixmedia_key` (one line, `chmod 600`). Keep the `api_key` widget empty,
   otherwise the key ends up in the workflow JSON.
3. Restart ComfyUI: the nodes appear under `api/mixmedia`.
4. Copy `workflows/photostudio_mixmedia.json` into `<ComfyUI>/user/default/workflows/`.

## The studio workflow

One JSON with three independent stages on a single canvas:

| Stage | What it does | Output |
|---|---|---|
| 1. Character | 6 face photos → 2×2 sheet | `character_ref` |
| 2. Shot | person + outfit + location + headwear + pose + Studio | `shot` |
| 3. Retake | shot + turn/zoom/height/lens | `retake` |

Each stage has a **"▶ START"** button at the bottom of its node: it turns that stage on, turns the other
two off and queues right away, so exactly one stage runs. The manual way is the **`run`** switch on the
node (`Mixmedia Character` / `Mixmedia Shot` / `Mixmedia Retake`). A disabled stage does not execute and
costs nothing: its `SaveImage` is skipped silently, with no red Error Report (the log gets a "switched off"
line). Stage 1 is enabled by default. Outputs are never muted, so ComfyUI never complains about
"no output nodes".

## Models and prices

| Model | Resolutions | References | 1K | 2K | 4K |
|---|---|---|---|---|---|
| `nano-banana-pro` | 1K, 2K, 4K | 8 | $0.05 | $0.05 | $0.065 |
| `nano-banana-2` | 0.5K, 1K, 2K, 4K | 10 | $0.025 | $0.035 | $0.04 |
| `nano-banana` | 1K, 2K | 10 | $0.03 | $0.03 | — |
| `gpt-image-2.5` | 1K, 2K, 4K | 16 | $0.04 | $0.04 | $0.06 |
| `seedream-pro` / `flash` | 1K, 1.5K, 2K | 10 | $0.05 / $0.025 | $0.095 / $0.025 | — |
| `flux-dev` | — | 0 | $0.033 | — | — |

Unsupported resolutions or aspect ratios are clamped to the closest supported one (e.g. `9:21` → `9:16`)
with a warning in the console instead of a failed task.

## Checks

```bash
.venv/bin/python tools/test_prompts.py                 # prompts and execute() without API calls
python3 tools/validate_workflow.py workflows/photostudio_mixmedia.json   # against /object_info
node tools/e2e/check-workflows.js workflows/photostudio_mixmedia.json    # loads in the real frontend
node tools/e2e/check-link.js workflows/photostudio_mixmedia.json         # links and widget values
node tools/e2e/check-run.js workflows/photostudio_mixmedia.json          # which stages a Run would queue
node tools/e2e/slots.js                                                  # input and widget order
```

The validator and the e2e scripts expect a running ComfyUI at `http://127.0.0.1:8188`.

## Windows

There is no prebuilt `.exe`: a torch venv can only be built on Windows itself. Instead there is an
installer script [`windows/install.ps1`](windows/install.ps1): it clones ComfyUI, creates the venv,
installs torch and the requirements, copies nodes and the workflow, writes the key and creates a desktop
shortcut that starts the server and opens the UI in its own window (Chrome `--app`), like on macOS.

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

A ready-to-run archive is attached to the [release](https://github.com/smm959/comfyui-mixmedia/releases/tag/v1.0).

> **Help wanted:** the installer has never been run on a real Windows machine. If you can test it, please
> report in [issue #1](https://github.com/smm959/comfyui-mixmedia/issues/1) — it takes ~10 minutes.

## macOS app

`tools/make_installer.sh` builds a self-contained app (ComfyUI + venv + nodes inside the bundle) and a DMG
with the usual drag-to-Applications window:

* the window is its own (`desktop/ComfyUIApp.m`: ObjC + WKWebView, ~80 KB), not a browser tab: no address
  bar or Chrome menu, with ⌘R / ⌘± and normal copy-paste; the window size and position are remembered;
* the server is started through launchd (`local.mixmedia.comfyui`) and keeps running after the window closes;
* on first launch the key is copied to `~/.mixmedia_key`, it is never packaged into the installer;
* file dialogs are native: "Open workflow", image upload and `MixmediaPick` use `NSOpenPanel`, and JS
  `alert` / `confirm` / `prompt` are sheets — WKWebView shows nothing unless the delegate implements them;
* on launch the studio workflow (`photostudio_mixmedia`) opens with the camera view saved in the file;
* window build: `clang` (needs an accepted Xcode license) for `desktop/ComfyUIApp.m`; fallbacks are
  `pyobjc-framework-WebKit` from `desktop/requirements.txt`, then Chrome `--app`;
* requires `dmgbuild` (`pip install dmgbuild`).

## Limitations

* MixMedia does not accept a `seed` — the `seed` widget only resets the ComfyUI cache;
* `Cancel` in the UI does not cancel an already created and paid task;
* results on the MixMedia side live for 24 hours, the nodes download them immediately;
* the nodes survive a flaky network: uploads and polling are retried (polling runs until `timeout_sec`,
  900 s by default); if it still fails, fetch the paid image by hand: `python tools/fetch_task.py <taskId>`;
* Nano Banana Pro accepts at most 8 references per request, extra identity photos are dropped with a warning.
