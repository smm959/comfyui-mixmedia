"""Generate the MixMedia ComfyUI workflow: one project file with three independent stages.

  photostudio_mixmedia.json
    1. Персонаж  - 2-6 face photos -> character sheet 2x2
    2. Кадр      - sheet + outfit + location + pose + Studio -> one frame
    3. Докрутка  - finished frame -> same frame with the camera moved

Stages are not wired to each other. Only stages whose output nodes are unmuted run,
so one Queue Prompt runs exactly one stage (stage 2 by default).
"""
import json
import os
import uuid

TOP_NOTE = (
    "ФОТОСТУДИЯ\n"
    "1 — лист персонажа, 2 — кадр, 3 — докрутка камеры.\n"
    "Этапы не связаны: каждый запускается отдельно.\n\n"
    "Один Run запускает все этапы, у которых НЕ замьючены выходы\n"
    "(выход этапа = его SaveImage + Preview).\n"
    "Сейчас включён этап 2. Чтобы включить другой: выдели рамкой его\n"
    "SaveImage и Preview и нажми Ctrl+M; выключи лишнее так же.\n"
    "Замьюченные ноды серые и перечёркнуты."
)

STAGE1_NOTE = (
    "ЭТАП 1 — лист персонажа.\n"
    "Сейчас выключен (выходы замьючены).\n"
    "Включить: Ctrl+M по SaveImage и Preview.\n"
    "Порядок: 6 фото лица -> Batch -> Character.\n"
    "Цена ~$0.065, 4K, 2x2."
)

STAGE2_NOTE = (
    "ЭТАП 2 — кадр.\n"
    "Включён по умолчанию.\n"
    "Кидаешь: персонаж, одежда, локация.\n"
    "Поза — текстом прямо в Mixmedia Shot:\n"
    "«сидит на подоконнике, колени к груди».\n"
    "Пусто -> поза не упоминается вообще.\n"
    "Головной убор — MixMedia Ref, «(нет)» = из одежды.\n"
    "Камера, свет, объектив, объекты — в Studio.\n"
    "Цена ~$0.05, 2K."
)

STAGE3_NOTE = (
    "ЭТАП 3 — докрутка камеры.\n"
    "Сейчас выключен (выходы замьючены).\n"
    "Включить: Ctrl+M по SaveImage и Preview.\n"
    "Кидаешь готовый кадр из этапа 2.\n"
    "turn ±90, zoom ±50, высота ±30, объектив.\n"
    "Каждый запуск — новая генерация, ~$0.05."
)


def node(nid, ntype, pos, size, widgets, inputs=None, outputs=None, order=0,
         cnr="comfy-core", title=None, mode=0):
    n = {
        "id": nid,
        "type": ntype,
        "pos": pos,
        "size": size,
        "flags": {},
        "order": order,
        "mode": mode,
        "inputs": inputs or [],
        "outputs": outputs or [],
        "properties": {"Node name for S&R": ntype, "cnr_id": cnr},
        "widgets_values": widgets,
    }
    if title:
        n["title"] = title
    return n


def note(nid, pos, size, text, order):
    return node(nid, "Note", pos, size, [text], outputs=[], order=order, title="Инструкция")


def inp(name, typ, link=None, shape=None, widget=None):
    d = {"localized_name": name, "name": name, "type": typ}
    if shape:
        d["shape"] = shape
    if widget:
        d["widget"] = {"name": widget}
    d["link"] = link
    return d


def out(name, typ, links=None):
    return {"localized_name": name, "name": name, "type": typ, "links": links}


def loader(nid, pos, filename, title, link_out, order):
    return node(nid, "LoadImage", pos, [320, 380], [filename, "image"],
                outputs=[out("IMAGE", "IMAGE", [link_out]), out("MASK", "MASK")],
                order=order, title=title)


def shot_widgets(model="nano-banana-pro", seed=42, aspect="4:5", resolution="2K", fmt="png",
                 pose="", direction=""):
    return [model, seed, "randomize", aspect, resolution, fmt, pose, direction, "", 300]


def studio_widgets(text="", framing="auto", angle="auto", camera_height="auto", lens="auto",
                   light_setup="auto", light_temp="auto", light_contrast="auto", backdrop="auto",
                   props="", avoid="", direction=""):
    return [text, framing, angle, camera_height, lens, light_setup, light_temp, light_contrast,
            backdrop, props, avoid, direction]


def retake_widgets(turn=0.0, zoom=0.0, camera_height=0.0, lens="auto", text="",
                   model="nano-banana-pro", seed=42, aspect="auto", resolution="2K", fmt="png"):
    return [turn, zoom, camera_height, lens, text, model, seed, "randomize", aspect, resolution, fmt, "", 300]


def character_widgets(seed, look="", model="nano-banana-pro", aspect="1:1", resolution="4K"):
    return [model, seed, "randomize", aspect, resolution, "png", look, "", 300]


def shot_inputs(identity, outfit, location, headwear, direction):
    return [
        inp("identity", "IMAGE", identity),
        inp("outfit", "IMAGE", outfit, shape=7),
        inp("location", "IMAGE", location, shape=7),
        inp("headwear", "IMAGE", headwear, shape=7),
        inp("model", "COMBO", widget="model"),
        inp("seed", "INT", widget="seed"),
        inp("aspect_ratio", "COMBO", widget="aspect_ratio"),
        inp("resolution", "COMBO", widget="resolution"),
        inp("output_format", "COMBO", widget="output_format"),
        inp("pose", "STRING", shape=7, widget="pose"),
        inp("direction", "STRING", direction, shape=7, widget="direction"),
        inp("api_key", "STRING", shape=7, widget="api_key"),
        inp("timeout_sec", "INT", shape=7, widget="timeout_sec"),
    ]


def studio_inputs(direction):
    names = ["text", "framing", "angle", "camera_height", "lens", "light_setup", "light_temp",
             "light_contrast", "backdrop", "props", "avoid"]
    types = ["STRING", "COMBO", "COMBO", "COMBO", "COMBO", "COMBO", "COMBO", "COMBO", "COMBO",
             "STRING", "STRING"]
    return [inp(n, t, widget=n) for n, t in zip(names, types)] + [
        inp("direction", "STRING", direction, shape=7, widget="direction")]


def retake_inputs(image):
    names = ["turn", "zoom", "camera_height", "lens", "text", "model", "seed", "aspect_ratio",
             "resolution", "output_format"]
    types = ["FLOAT", "FLOAT", "FLOAT", "COMBO", "STRING", "COMBO", "INT", "COMBO", "COMBO", "COMBO"]
    return [inp("image", "IMAGE", image)] + [inp(n, t, widget=n) for n, t in zip(names, types)] + [
        inp("api_key", "STRING", shape=7, widget="api_key"),
        inp("timeout_sec", "INT", shape=7, widget="timeout_sec")]


class Graph:
    def __init__(self):
        self.nodes = []
        self.links = []
        self.groups = []
        self.link_id = 0

    def link(self, src, src_slot, dst, dst_slot, typ="IMAGE"):
        self.link_id += 1
        self.links.append([self.link_id, src, src_slot, dst, dst_slot, typ])
        return self.link_id

    def add(self, n):
        self.nodes.append(n)

    def group(self, title, x, y, w, h, color="#3f789e"):
        self.groups.append({"title": title, "bounding": [x, y, w, h], "color": color,
                            "font_size": 28, "flags": {}})

    def save(self, name):
        wf = {
            "id": str(uuid.uuid4()),
            "revision": 0,
            "last_node_id": max(n["id"] for n in self.nodes),
            "last_link_id": self.link_id,
            "nodes": self.nodes,
            "links": self.links,
            "groups": self.groups,
            "config": {},
            "extra": {"ds": {"scale": 0.4, "offset": [900, 100]}},
            "version": 0.4,
        }
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(wf, f, ensure_ascii=False, indent=2)
        print("wrote", path)


def build():
    g = Graph()
    order = 0

    g.add(note(300, [-120, -800], [980, 340], TOP_NOTE, order))
    order += 1

    # ---------------------------------------------------------------- 1. персонаж
    g.add(note(1, [1780, 1000], [420, 200], STAGE1_NOTE, order))
    order += 1

    slots = 6
    face_links = [g.link(i + 2, 0, 20, i) for i in range(slots)]
    ch_in = g.link(20, 0, 21, 0)
    ch_save = g.link(21, 0, 22, 0)
    ch_info = g.link(21, 1, 23, 0, "STRING")

    names = ["1. Лицо — фронт", "2. Лицо — три четверти", "3. Лицо — профиль",
             "4. Лицо — ещё", "5. Лицо — ещё", "6. Лицо — ещё"]
    for i in range(slots):
        g.add(loader(i + 2, [i * 340, 0], "character.png", names[i], face_links[i], order))
        order += 1

    g.add(node(20, "BatchImagesNode", [340, 440], [250, 200], [],
               inputs=[{"label": f"image{i}", "name": f"images.image{i}", "type": "IMAGE",
                        **({"shape": 7} if i else {}), "link": face_links[i]} for i in range(slots)],
               outputs=[out("IMAGE", "IMAGE", [ch_in])], order=order))
    order += 1
    g.add(node(21, "MixmediaCharacter", [700, 440], [420, 430], character_widgets(42),
               inputs=[inp("identity", "IMAGE", ch_in),
                       inp("model", "COMBO", widget="model"),
                       inp("seed", "INT", widget="seed"),
                       inp("aspect_ratio", "COMBO", widget="aspect_ratio"),
                       inp("resolution", "COMBO", widget="resolution"),
                       inp("output_format", "COMBO", widget="output_format"),
                       inp("look", "STRING", shape=7, widget="look"),
                       inp("api_key", "STRING", shape=7, widget="api_key"),
                       inp("timeout_sec", "INT", shape=7, widget="timeout_sec")],
               outputs=[out("image", "IMAGE", [ch_save]), out("info", "STRING", [ch_info])],
               order=order, cnr="comfyui-mixmedia"))
    order += 1
    g.add(node(22, "SaveImage", [1200, 440], [420, 460], ["character_ref"],
               inputs=[{"name": "images", "type": "IMAGE", "link": ch_save}], order=order, mode=2))
    order += 1
    g.add(node(23, "PreviewAny", [1200, 940], [420, 200], [],
               inputs=[{"name": "source", "type": "*", "link": ch_info}], order=order, mode=2,
               title="Промпт, который ушёл в API"))
    order += 1
    g.group("1. Персонаж — лист 2×2 (выключен)", -60, -80, 2320, 1260)

    # ---------------------------------------------------------------- 2. кадр
    Y = 1500
    g.add(note(101, [0, Y + 420], [460, 220], STAGE2_NOTE, order))
    order += 1

    shot_links = [g.link(102 + i, 0, 110, i) for i in range(4)]  # identity, outfit, location, headwear
    studio_dir = g.link(111, 0, 110, 10, "STRING")  # Studio.direction -> Shot.direction (slot 10)
    dir_in = g.link(112, 0, 111, 11, "STRING")      # Direction.direction -> Studio.direction (slot 11)
    shot_img = g.link(110, 0, 120, 0)
    shot_prompt = g.link(110, 2, 121, 0, "STRING")

    g.add(loader(102, [0, Y], "character.png", "1. Персонаж", shot_links[0], order)); order += 1
    g.add(loader(103, [340, Y], "outfit.png", "2. Одежда", shot_links[1], order)); order += 1
    g.add(loader(104, [680, Y], "location.png", "3. Локация", shot_links[2], order)); order += 1
    g.add(node(105, "MixmediaPick", [1020, Y], [320, 120], ["(нет)"],
               outputs=[out("image", "IMAGE", [shot_links[3]])],
               order=order, cnr="comfyui-mixmedia", title="4. Головной убор (нет = из одежды)"))
    order += 1

    g.add(node(110, "MixmediaShot", [1500, Y], [440, 680], shot_widgets(seed=42),
               inputs=shot_inputs(*shot_links, studio_dir),
               outputs=[out("image", "IMAGE", [shot_img]), out("info", "STRING"),
                        out("prompt", "STRING", [shot_prompt])],
               order=order, cnr="comfyui-mixmedia"))
    order += 1
    g.add(node(111, "MixmediaStudio", [1500, Y + 650], [440, 620], studio_widgets(),
               inputs=studio_inputs(dir_in),
               outputs=[out("direction", "STRING", [studio_dir])],
               order=order, cnr="comfyui-mixmedia"))
    order += 1
    g.add(node(112, "MixmediaDirection", [1500, Y + 1320], [440, 220], ["", 0.5, 0.5],
               inputs=[inp("text", "STRING", widget="text"),
                       inp("context_strength", "FLOAT", widget="context_strength"),
                       inp("detail_strength", "FLOAT", widget="detail_strength")],
               outputs=[out("direction", "STRING", [dir_in])],
               order=order, cnr="comfyui-mixmedia"))
    order += 1
    g.add(node(120, "SaveImage", [2050, Y], [420, 460], ["shot"],
               inputs=[{"name": "images", "type": "IMAGE", "link": shot_img}], order=order))
    order += 1
    g.add(node(121, "PreviewAny", [2050, Y + 500], [420, 240], [],
               inputs=[{"name": "source", "type": "*", "link": shot_prompt}], order=order,
               title="Промпт, который ушёл в API"))
    order += 1
    g.group("2. Кадр — включён", -60, 1400, 2700, 1650, "#8c6bb1")

    # ---------------------------------------------------------------- 3. докрутка
    Y = 3400
    g.add(note(201, [1500, Y], [460, 220], STAGE3_NOTE, order))
    order += 1

    keep_img = g.link(202, 0, 210, 0)
    keep_out = g.link(210, 0, 220, 0)
    keep_prompt = g.link(210, 2, 221, 0, "STRING")

    g.add(loader(202, [0, Y], "shot.png", "Кадр из этапа 2", keep_img, order))
    order += 1
    g.add(node(210, "MixmediaRetake", [420, Y], [460, 560], retake_widgets(seed=42),
               inputs=retake_inputs(keep_img),
               outputs=[out("image", "IMAGE", [keep_out]), out("info", "STRING"),
                        out("prompt", "STRING", [keep_prompt])],
               order=order, cnr="comfyui-mixmedia"))
    order += 1
    g.add(node(220, "SaveImage", [950, Y], [420, 460], ["retake"],
               inputs=[{"name": "images", "type": "IMAGE", "link": keep_out}], order=order, mode=2))
    order += 1
    g.add(node(221, "PreviewAny", [950, Y + 500], [420, 240], [],
               inputs=[{"name": "source", "type": "*", "link": keep_prompt}], order=order, mode=2,
               title="Промпт, который ушёл в API"))
    order += 1
    g.group("3. Докрутка камеры (выключен)", -60, 3300, 2100, 1000, "#88a")
    g.group("ФОТОСТУДИЯ", -160, -880, 2900, 5280, "#335")

    g.save("photostudio_mixmedia.json")


build()
