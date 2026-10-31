#!/usr/bin/env python3
"""Забрать результат уже оплаченной задачи MixMedia по её taskId (живёт 24 часа).

    python tools/fetch_task.py task_nano-banana-pro_17934676749245876e3
    python tools/fetch_task.py <taskId> --out ~/Downloads

Нужен, когда нода упала после создания задачи (обрыв сети, timeout, закрытый ноут):
деньги уже списаны, картинка лежит на сервере, и её можно скачать руками.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import requests

API_BASE = "https://mixmedia.tech/api/v1"


def find_key() -> str:
    env = os.environ.get("MIXMEDIA_API_KEY", "").strip()
    if env:
        return env
    here = Path(__file__).resolve()
    for base in [Path.cwd(), *Path.cwd().parents, here.parent, *here.parents, Path.home()]:
        path = base / ".mixmedia_key"
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    raise SystemExit("ключ не найден: положи его в ~/.mixmedia_key или задай MIXMEDIA_API_KEY")


def record(task_id: str, key: str, attempts: int, pause: float) -> dict:
    headers = {"Authorization": f"Bearer {key}"}
    for i in range(attempts):
        try:
            resp = requests.get(f"{API_BASE}/jobs/recordInfo", headers=headers,
                                params={"taskId": task_id}, timeout=60)
        except requests.RequestException as exc:
            print(f"  сеть: {exc} — повтор {i + 1}/{attempts}")
            time.sleep(pause)
            continue
        if resp.status_code >= 500:
            print(f"  сервер HTTP {resp.status_code} — повтор {i + 1}/{attempts}")
            time.sleep(pause)
            continue
        body = resp.json()
        code = body.get("code", resp.status_code)
        if code != 200:
            raise SystemExit(f"MixMedia {code}: {body.get('msg') or body.get('error')}")
        data = body.get("data") or {}
        state = str(data.get("state") or data.get("status") or "").lower()
        print(f"  {task_id}: {state or '?'}")
        if state in ("success", "completed"):
            return data
        if state in ("fail", "failed"):
            raise SystemExit(f"задача упала: {data.get('failMsg') or data.get('error') or state}")
        time.sleep(pause)
    raise SystemExit("не дождался результата, попробуй ещё раз позже (задача живёт 24 ч)")


def result_urls(data: dict) -> list:
    raw = data.get("resultJson") or {}
    if isinstance(raw, str):
        import json
        raw = json.loads(raw) if raw.strip() else {}
    urls = list(raw.get("resultUrls") or raw.get("result_urls") or [])
    if not urls and isinstance(raw.get("url"), str):
        urls = [raw["url"]]
    return urls


def main() -> int:
    ap = argparse.ArgumentParser(description="Скачать результат оплаченной задачи MixMedia")
    ap.add_argument("task_id")
    ap.add_argument("--out", default="", help="куда складывать (по умолчанию output/ или ./recovered)")
    ap.add_argument("--attempts", type=int, default=60)
    ap.add_argument("--pause", type=float, default=5.0)
    args = ap.parse_args()

    key = find_key()
    data = record(args.task_id, key, args.attempts, args.pause)
    urls = result_urls(data)
    if not urls:
        raise SystemExit(f"в задаче нет resultUrls: {data}")

    out = Path(args.out) if args.out else (Path("output") if Path("output").is_dir() else Path("recovered"))
    out.mkdir(parents=True, exist_ok=True)

    for i, url in enumerate(urls, 1):
        ext = os.path.splitext(url.split("?")[0])[1] or ".png"
        name = f"{args.task_id}_{i}{ext}" if len(urls) > 1 else f"{args.task_id}{ext}"
        target = out / name
        for attempt in range(4):
            try:
                resp = requests.get(url, timeout=180)
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt == 3:
                    raise SystemExit(f"не скачалось {url}: {exc}")
                print(f"  скачивание: {exc} — повтор")
                time.sleep(3)
        target.write_bytes(resp.content)
        print(f"сохранил {target}")

    cost = data.get("creditsConsumed", "?")
    print(f"готово: {len(urls)} файл(ов), cost=${cost}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
