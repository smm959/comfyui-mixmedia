#!/usr/bin/env python3
"""Окно ComfyUI MixMedia: нативный WKWebView вместо вкладки браузера.

Лаунчер приложения уже поднял сервер, поэтому здесь только окно:
    .venv/bin/python desktop/mixmedia_window.py http://127.0.0.1:8188 [icon.icns]

MIXMEDIA_SELFTEST=1 — проверка: окно, ресайз, снимок экрана в /tmp/mixmedia-selftest.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import objc
from AppKit import (
    NSApplication,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSScreen,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSObject, NSURL, NSURLRequest, NSUserDefaults
from WebKit import WKWebView, WKWebViewConfiguration

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8188"
ICON = sys.argv[2] if len(sys.argv) > 2 else ""
SELFTEST = os.environ.get("MIXMEDIA_SELFTEST") == "1"
LOG = Path.home() / "Library/Logs/ComfyUI Mix Media.log"
SELFTEST_DIR = Path("/tmp/mixmedia-selftest")

WAITING_PAGE = """<!doctype html><meta charset="utf-8">
<body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#202020;color:#e6e6e6;font:15px -apple-system,Helvetica">
<div style="text-align:center">
  <div style="font-size:19px;margin-bottom:10px">ComfyUI MixMedia</div>
  <div style="opacity:.65">поднимаю сервер…</div>
</div></body>"""

FAILED_PAGE = """<!doctype html><meta charset="utf-8">
<body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#202020;color:#e6e6e6;font:15px -apple-system,Helvetica">
<div style="text-align:center;max-width:520px;line-height:1.5">
  <div style="font-size:19px;margin-bottom:10px">Сервер не поднялся</div>
  <div style="opacity:.65">Лог: %s</div>
</div></body>""" % LOG

MEASURE_JS = ("JSON.stringify({inner:[window.innerWidth,window.innerHeight],"
              "canvas:window.app&&window.app.canvas?[window.app.canvas.canvas.width,"
              "window.app.canvas.canvas.height]:null,"
              "nodes:window.app&&window.app.graph?window.app.graph._nodes.length:null})")


def server_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except Exception:
        return False


class Window(NSObject):
    @objc.python_method
    def setup(self, url: str, icon: str):
        self.url = url
        self.loaded = False
        self.deadline = time.time() + 180
        self.measurements = {}

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        if icon and Path(icon).is_file():
            image = NSImage.alloc().initWithContentsOfFile_(icon)
            if image is not None:
                app.setApplicationIconImage_(image)
        app.setDelegate_(self)
        self.app = app
        self.menu()
        self.build()

    # ---------------------------------------------------------------- меню
    @objc.python_method
    def menu(self):
        bar = NSMenu.alloc().init()
        app_item = NSMenuItem.alloc().init()
        app_item.setTitle_("ComfyUI MixMedia")
        bar.addItem_(app_item)
        self.app.setMainMenu_(bar)

        main = NSMenu.alloc().init()
        app_item.setSubmenu_(main)
        main.addItemWithTitle_action_keyEquivalent_("О программе ComfyUI MixMedia",
                                                    "orderFrontStandardAboutPanel:", "")
        main.addItem_(NSMenuItem.separatorItem())
        main.addItemWithTitle_action_keyEquivalent_("Завершить", "terminate:", "q")

        edit = NSMenu.alloc().init()
        edit_item = NSMenuItem.alloc().init()
        edit_item.setTitle_("Правка")
        bar.addItem_(edit_item)
        edit_item.setSubmenu_(edit)
        for title, selector, key in [
            ("Отменить", "undo:", "z"),
            ("Повторить", "redo:", "Z"),
            (None, None, None),
            ("Вырезать", "cut:", "x"),
            ("Копировать", "copy:", "c"),
            ("Вставить", "paste:", "v"),
            ("Выбрать всё", "selectAll:", "a"),
        ]:
            if title is None:
                edit.addItem_(NSMenuItem.separatorItem())
            else:
                edit.addItemWithTitle_action_keyEquivalent_(title, selector, key)

        view = NSMenu.alloc().init()
        view_item = NSMenuItem.alloc().init()
        view_item.setTitle_("Вид")
        bar.addItem_(view_item)
        view_item.setSubmenu_(view)
        view.addItemWithTitle_action_keyEquivalent_("Обновить", "reloadPage:", "r")
        view.addItem_(NSMenuItem.separatorItem())
        view.addItemWithTitle_action_keyEquivalent_("Крупнее", "zoomIn:", "+")
        view.addItemWithTitle_action_keyEquivalent_("Мельче", "zoomOut:", "-")
        view.addItemWithTitle_action_keyEquivalent_("Обычный размер", "zoomReset:", "0")

        win = NSMenu.alloc().init()
        win_item = NSMenuItem.alloc().init()
        win_item.setTitle_("Окно")
        bar.addItem_(win_item)
        win_item.setSubmenu_(win)
        win.addItemWithTitle_action_keyEquivalent_("Свернуть", "performMiniaturize:", "m")
        win.addItemWithTitle_action_keyEquivalent_("Вписать окно", "performZoom:", "")
        win.addItem_(NSMenuItem.separatorItem())
        win.addItemWithTitle_action_keyEquivalent_("Собрать все окна", "arrangeInFront:", "")

    # ---------------------------------------------------------------- окно
    @objc.python_method
    def saved_frame(self):
        saved = NSUserDefaults.standardUserDefaults().objectForKey_("mixmediaWindowFrame")
        screen = NSScreen.mainScreen().frame()
        max_w, max_h = screen.size.width, screen.size.height
        if saved is not None:
            try:
                left, bottom, width, height = (float(x) for x in saved)
                if width >= 900 and height >= 600:
                    return NSMakeRect(left, bottom, min(width, max_w), min(height, max_h))
            except Exception:
                pass
        return NSMakeRect(60, 60, min(1440, max_w - 80), min(900, max_h - 80))

    @objc.python_method
    def build(self):
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            self.saved_frame(), style, NSBackingStoreBuffered, False)
        self.window.setTitle_("ComfyUI MixMedia")
        self.window.setMinSize_((900, 600))
        self.window.setReleasedWhenClosed_(False)
        self.window.setDelegate_(self)

        config = WKWebViewConfiguration.alloc().init()
        self.web = WKWebView.alloc().initWithFrame_configuration_(
            self.window.contentLayoutRect(), config)
        self.web.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.web.setNavigationDelegate_(self)
        self.web.setUIDelegate_(self)
        try:
            self.web.setInspectable_(True)
        except Exception:
            pass

        self.window.setContentView_(self.web)
        self.window.makeKeyAndOrderFront_(None)
        self.app.activateIgnoringOtherApps_(True)

        self.web.loadHTMLString_baseURL_(WAITING_PAGE, None)
        threading.Thread(target=self.wait_for_server, daemon=True).start()

    @objc.python_method
    def wait_for_server(self):
        while time.time() < self.deadline:
            if server_up(self.url):
                self.performSelectorOnMainThread_withObject_waitUntilDone_("loadNow:", None, False)
                return
            time.sleep(0.4)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("showFailure:", None, False)

    def loadNow_(self, sender):
        self.web.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(self.url)))
        self.loaded = True

    def showFailure_(self, sender):
        self.web.loadHTMLString_baseURL_(FAILED_PAGE, None)

    # ---------------------------------------------------------------- делегаты
    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return True

    def windowWillClose_(self, note):
        frame = self.window.frame()
        defaults = NSUserDefaults.standardUserDefaults()
        defaults.setObject_forKey_(
            [frame.origin.x, frame.origin.y, frame.size.width, frame.size.height],
            "mixmediaWindowFrame")
        defaults.synchronize()
        self.app.terminate_(None)

    def windowDidResize_(self, note):
        self.web.setFrame_(self.window.contentLayoutRect())

    def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(
            self, webview, config, action, features):
        target = action.request().URL()
        if target is not None:
            subprocess.Popen(["/usr/bin/open", target.absoluteString()])
        return None

    def webView_decidePolicyForNavigationAction_decisionHandler_(self, webview, action, handler):
        target = action.request().URL()
        scheme = (target.scheme() or "").lower() if target is not None else ""
        host = (target.host() or "") if target is not None else ""
        if scheme in ("http", "https") and host not in ("127.0.0.1", "localhost"):
            subprocess.Popen(["/usr/bin/open", target.absoluteString()])
            handler(0)
            return
        handler(1)

    def reloadPage_(self, sender):
        self.web.reload()

    def zoomIn_(self, sender):
        self.web.setPageZoom_(min(self.web.pageZoom() * 1.1, 3.0))

    def zoomOut_(self, sender):
        self.web.setPageZoom_(max(self.web.pageZoom() / 1.1, 0.4))

    def zoomReset_(self, sender):
        self.web.setPageZoom_(1.0)

    # ---------------------------------------------------------------- самопроверка
    @objc.python_method
    def selftest(self):
        SELFTEST_DIR.mkdir(parents=True, exist_ok=True)
        for _ in range(90):
            if self.loaded:
                break
            time.sleep(1)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("measureBefore:", None, True)
        time.sleep(1.0)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("shrinkWindow:", None, True)
        time.sleep(2.5)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("measureSmall:", None, True)
        time.sleep(1.0)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("growWindow:", None, True)
        time.sleep(2.5)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("measureBig:", None, True)
        time.sleep(1.0)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("snapshot:", None, True)
        (SELFTEST_DIR / "result.json").write_text(
            json.dumps(self.measurements, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(self.measurements, ensure_ascii=False))
        self.performSelectorOnMainThread_withObject_waitUntilDone_("terminate:", None, True)

    @objc.python_method
    def eval_js(self, tag):
        event = threading.Event()
        box = {}

        def done(value, error):
            box["value"] = str(value)
            box["error"] = str(error) if error else None
            event.set()

        self.web.evaluateJavaScript_completionHandler_(MEASURE_JS, done)
        event.wait(20)
        self.measurements[tag] = box

    def measureBefore_(self, sender):
        self.eval_js("before")

    def shrinkWindow_(self, sender):
        self.window.setFrame_display_(NSMakeRect(80, 80, 1100, 720), True)

    def measureSmall_(self, sender):
        self.eval_js("after_small")

    def growWindow_(self, sender):
        self.window.setFrame_display_(NSMakeRect(80, 80, 1500, 950), True)

    def measureBig_(self, sender):
        self.eval_js("after_big")

    def snapshot_(self, sender):
        event = threading.Event()

        def done(image, error):
            if image is not None:
                rep = NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
                data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
                if data is not None:
                    data.writeToFile_atomically_(str(SELFTEST_DIR / "window.png"), True)
            event.set()

        self.web.takeSnapshotWithConfiguration_completionHandler_(None, done)
        event.wait(20)

    def terminate_(self, sender):
        self.app.terminate_(None)

    # ----------------------------------------------------------------
    @objc.python_method
    def run(self):
        if SELFTEST:
            threading.Thread(target=self.selftest, daemon=True).start()
        self.app.run()


if __name__ == "__main__":
    window = Window.alloc().init()
    window.setup(URL, ICON)
    window.run()
