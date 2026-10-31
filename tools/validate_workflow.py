"""Sanity-check a ComfyUI UI workflow against a running server's /object_info."""
import json
import sys
import urllib.request

SERVER = "http://127.0.0.1:8188"


def main(path):
    wf = json.load(open(path))
    info = json.load(urllib.request.urlopen(SERVER + "/object_info", timeout=60))
    nodes = {n["id"]: n for n in wf["nodes"]}
    problems = []

    for n in wf["nodes"]:
        t = n["type"]
        if t in ("Note", "MarkdownNote", "Reroute", "PrimitiveNode"):
            continue  # frontend-only, never in /object_info
        if t not in info:
            problems.append(f"node {n['id']}: unknown type {t}")
            continue
        spec = info[t]
        req = list(spec["input"].get("required", {}).keys())
        opt = list(spec["input"].get("optional", {}).keys())
        connected = {i["name"] for i in n.get("inputs", []) if i.get("link") is not None}
        # widget inputs = required/optional inputs that are widget types
        widget_types = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}

        def kind_of(name):
            d = spec["input"].get("required", {}).get(name) or spec["input"].get("optional", {}).get(name)
            if not d:
                return None, False
            k = d[0]
            if isinstance(k, list):
                k = "COMBO"
            cacg = isinstance(d[1], dict) and bool(d[1].get("control_after_generate"))
            return (k if k in widget_types else None), cacg

        expected, extra = 0, 0
        for name in req + opt:
            if name in connected:
                continue
            k, cacg = kind_of(name)
            if k is None:
                continue
            expected += 1
            extra += 1 if (k == "INT" and cacg) else 0
        got = len(n.get("widgets_values", []))
        if got < expected:
            problems.append(f"node {n['id']} ({t}): widgets_values={got}, expected {expected}{'/' + str(expected + extra) if extra else ''}")

        for i, inp in enumerate(n.get("inputs", [])):
            base = inp["name"].split(".")[0]
            if inp.get("link") is not None and inp["name"] not in req + opt and base not in req + opt:
                problems.append(f"node {n['id']}: input '{inp['name']}' not in schema")

    # links: [id, src_node, src_slot, dst_node, dst_slot, type]
    for lid, src, sslot, dst, dslot, _typ in wf["links"]:
        if src not in nodes or dst not in nodes:
            problems.append(f"link {lid}: dangling node id")
            continue
        if sslot >= len(nodes[src].get("outputs", [])):
            problems.append(f"link {lid}: bad source slot")
        if dslot >= len(nodes[dst].get("inputs", [])):
            problems.append(f"link {lid}: bad target slot")

    print(f"{path}: {len(wf['nodes'])} nodes, {len(wf['links'])} links -> "
          + ("OK" if not problems else "PROBLEMS"))
    for p in problems:
        print("  -", p)
    return not problems


if __name__ == "__main__":
    ok = all(main(p) for p in sys.argv[1:])
    sys.exit(0 if ok else 1)
