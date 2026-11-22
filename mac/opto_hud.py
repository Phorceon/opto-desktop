"""Opto HUD: one native, transparent, always-on-top window for the 3D + Manim view.

No browser, no tabs: the 3D model floats over the desktop next to a side panel.
The menu bar cube, mac/ask-opto.sh and Quick Actions drive it over a loopback port:
    POST http://127.0.0.1:8766/show  {"url": "http://127.0.0.1:8765/?q=..."}
    POST http://127.0.0.1:8766/hide
Esc or the panel's x hides it; the menu bar icon (cube) brings the prompt bar
back. Drag the panel header to move it; drag the model to orbit. Run from the repo root (its venv has pywebview), or install it
as a login item with mac/install.sh:
    uv run python mac/opto_hud.py
"""

import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.request
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import webview
from AppKit import (
    NSApp,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

PORT = int(os.environ.get("OPTO_HUD_PORT", "8766"))
OPTO = os.environ.get("OPTO_URL", "http://127.0.0.1:8765")
ESC_HIDES = (
    "document.addEventListener('keydown', e => {"
    " if (e.key === 'Escape') window.pywebview.api.hide(); });"
)


def with_hud(url: str) -> str:
    """Force ?hud=1 so the page uses the transparent side-panel layout."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.pop("clean", None)
    query["hud"] = "1"
    return urlunsplit(parts._replace(query=urlencode(query)))


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        OPTO + path, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


class Api:
    def hide(self) -> None:
        window.hide()

    close = hide

    def _grab(self, *flags: str) -> dict | None:
        """Hide the HUD, run macOS screencapture, upload, show the HUD again."""
        tmp = os.path.join(tempfile.gettempdir(), f"opto-hud-{os.getpid()}.png")
        window.hide()
        time.sleep(0.25)
        try:
            subprocess.run(["screencapture", "-x", *flags, tmp], check=False)
            if not os.path.exists(tmp):
                return None  # snip cancelled
            with open(tmp, "rb") as f:
                data = "data:image/png;base64," + b64encode(f.read()).decode()
            return post("/api/upload", {"image": data})
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
            window.show()

    def compact(self, height: int = 64) -> None:
        """Prompt-bar size: a slim bar near the top centre of the screen."""
        screen = webview.screens[0]
        w = min(680, screen.width - 40)
        window.resize(w, int(height))
        window.move((screen.width - w) // 2, 90)

    def expand(self) -> None:
        """Full size: 3D view + side panel."""
        place()

    def set_timer(self, text: str = "") -> None:
        """Elapsed time next to the menu bar cube while Kimi is working."""
        AppHelper.callAfter(MENU.item.button().setTitle_, f" {text}" if text else "")

    def capture_screen(self) -> dict | None:
        return self._grab()

    def snip_screen(self) -> dict | None:
        return self._grab("-i")  # native drag-to-select region


def open_bar(then_js: str = "") -> None:
    """Show the slim prompt bar, focused (a blank window gets the app first)."""
    if not (window.get_current_url() or "").startswith(OPTO):
        window.load_url(with_hud(OPTO + "/?mode=kimi"))
        time.sleep(0.6)
    window.evaluate_js("window.__optoCompact && window.__optoCompact();")
    API.compact()
    window.show()
    AppHelper.callAfter(NSApp.activateIgnoringOtherApps_, True)
    window.evaluate_js("window.__optoFocus && window.__optoFocus();" + then_js)


class MenuBar(NSObject):
    """The cube in the macOS status bar. Actions hop off the main thread
    because pywebview calls wait on it."""

    def setup(self):
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_("cube.transparent", "Opto")
        icon.setTemplate_(True)
        self.item.button().setImage_(icon)
        self.item.button().setImagePosition_(2)  # NSImageLeft: cube, then timer
        menu = NSMenu.alloc().init()
        for title, action, key in (
            ("Ask Opto…", "ask:", "o"),
            ("Ask About Screen…", "screen:", "s"),
            ("Hide", "hide:", "h"),
            (None, None, None),
            ("Quit Opto", "quit:", "q"),
        ):
            if title is None:
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
            entry.setTarget_(self)
            menu.addItem_(entry)
        self.item.setMenu_(menu)

    def ask_(self, _):
        threading.Thread(target=open_bar, daemon=True).start()

    def screen_(self, _):
        js = "document.getElementById('captureButton')?.click();"
        threading.Thread(target=open_bar, args=(js,), daemon=True).start()

    def hide_(self, _):
        threading.Thread(target=window.hide, daemon=True).start()

    def quit_(self, _):
        threading.Thread(target=window.destroy, daemon=True).start()


def menubar_setup() -> None:
    NSApp.setActivationPolicy_(1)  # accessory: menu bar only, no Dock icon
    MENU.setup()


MENU = MenuBar.alloc().init()


def place() -> None:
    """Full layout: a compact window in the top-right corner (~half the screen)."""
    screen = webview.screens[0]
    w = min(screen.width - 24, max(720, int(screen.width * 0.48)))
    h = min(screen.height - 60, max(480, int(screen.height * 0.56)))
    window.resize(w, h)
    window.move(screen.width - w - 12, 36)


class Control(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        size = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(size) or b"{}")
        if self.path == "/show" and body.get("url", "").startswith("http://127.0.0.1:"):
            window.load_url(with_hud(body["url"]))
            window.show()
        elif self.path == "/hide":
            window.hide()
        else:
            self.send_response(400)
            self.end_headers()
            return
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:  # health check
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_: object) -> None:
        pass


def ensure_opto_server() -> None:
    """Start opto.server on the OpenClaw backend (Kimi K3.1 only) if it is down."""
    try:
        urllib.request.urlopen(OPTO + "/api/scenes", timeout=1)
        return
    except OSError:
        pass
    kimi = "moonshotai-kimi-k3.1-pro-trial"
    env = {**os.environ, "OPTO_BACKEND": "openclaw", "OPTO_MODE": "kimi",
           "OPTO_MODEL": kimi, "OPTO_FAST_MODEL": kimi}
    env.pop("VIRTUAL_ENV", None)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(os.path.join(root, "out"), exist_ok=True)
    log = open(os.path.join(root, "out", "server.log"), "ab")  # noqa: SIM115
    subprocess.Popen(["uv", "run", "python", "-m", "opto.server"], cwd=root, env=env,
                     stdout=log, stderr=log, start_new_session=True)


def serve() -> None:
    AppHelper.callAfter(menubar_setup)
    ensure_opto_server()
    place()
    ThreadingHTTPServer(("127.0.0.1", PORT), Control).serve_forever()


API = Api()
window = webview.create_window(
    "Opto", "about:blank", js_api=API, frameless=True, easy_drag=False,
    on_top=True, hidden=True, transparent=True,
)
window.events.loaded += lambda: window.evaluate_js(ESC_HIDES)
webview.start(serve)
