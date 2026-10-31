"""Server-side validation of a UI workflow without executing it (no API money spent).

    node tools/e2e/dump-api.js photostudio_mixmedia.json > /tmp/prompt.json
    .venv/bin/python tools/validate_api.py /tmp/prompt.json
"""
import asyncio
import json
import os
import sys
from pathlib import Path

COMFY = Path(os.environ.get("COMFYUI_DIR", Path(__file__).resolve().parents[1] / "comfyui")).resolve()
sys.path.insert(0, str(COMFY))

import execution  # noqa: E402
import nodes  # noqa: E402,F401  (registers node classes)


def main(path):
    prompt = json.load(open(path))
    ok, error, outputs, node_errors = asyncio.run(execution.validate_prompt("offline", prompt, None))
    print(f"{path}: valid={ok} outputs={outputs}")
    if error:
        print("  error:", json.dumps(error, ensure_ascii=False)[:500])
    for nid, err in node_errors.items():
        print(f"  node {nid}: {json.dumps(err, ensure_ascii=False)[:500]}")
    return ok


if __name__ == "__main__":
    asyncio.run(nodes.init_extra_nodes())
    ok = all(main(p) for p in sys.argv[1:])
    sys.exit(0 if ok else 1)
