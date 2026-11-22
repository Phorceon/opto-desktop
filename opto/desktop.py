"""Wispr Flow-style floating top-of-screen desktop overlay for Operation Opto.

    uv run python -m opto.desktop

Features:
- Always-on-top frameless top-center pill bar that expands downward into the live 3D + Manim stage.
- One-click region snip (drag rectangle anywhere on screen), full-screen capture, or paste/drop image.
- Global hotkey Ctrl+Shift+O on Windows to summon and focus the bar from anywhere.
"""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from PIL import ImageGrab

from . import server

PILL_W = 760
PILL_H = 68
TOP_MARGIN = 12


def _run_snip_tool(out_path: str) -> int:
    """Fullscreen drag-to-snip selector (runs in its own process so Tk never clashes with WebView)."""
    import tkinter as tk
    from PIL import ImageTk

    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    shot = ImageGrab.grab(all_screens=False)
    sw, sh = shot.size

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{sw}x{sh}+0+0")
    root.attributes("-topmost", True)
    root.configure(cursor="crosshair", bg="black")

    dimmed = shot.point(lambda p: int(p * 0.55))
    bg_photo = ImageTk.PhotoImage(dimmed)

    canvas = tk.Canvas(root, width=sw, height=sh, highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, anchor="nw", image=bg_photo)
    canvas.create_text(
        sw // 2, 34,
        text="Drag to select a region for Opto  ·  Esc to cancel",
        fill="#cdeeff", font=("Segoe UI", 13, "bold"),
    )

    state: dict = {"x0": 0, "y0": 0, "rect": None, "box": None}

    def on_down(ev):
        state["x0"], state["y0"] = ev.x, ev.y
        if state["rect"] is not None:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(
            ev.x, ev.y, ev.x, ev.y, outline="#4fc3f7", width=2,
        )

    def on_drag(ev):
        if state["rect"] is not None:
            canvas.coords(state["rect"], state["x0"], state["y0"], ev.x, ev.y)

    def on_up(ev):
        x0, x1 = sorted((state["x0"], ev.x))
        y0, y1 = sorted((state["y0"], ev.y))
        if x1 - x0 >= 12 and y1 - y0 >= 12:
            state["box"] = (x0, y0, x1, y1)
        root.quit()

    def on_cancel(_ev=None):
        state["box"] = None
        root.quit()

    canvas.bind("<ButtonPress-1>", on_down)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_up)
    root.bind("<Escape>", on_cancel)
    root.focus_force()
    root.mainloop()
    root.destroy()

    if not state["box"]:
        return 1
    cropped = shot.crop(state["box"]).convert("RGB")
    cropped.save(out_path, format="JPEG", quality=92)
    return 0


def _pick_port(preferred: int = 8765) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(port: int) -> None:
    import uvicorn

    os.environ.setdefault("OPTO_BACKEND", "openclaw")
    config = uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 10.0
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)


def _register_windows_hotkey(on_trigger) -> None:
    """Register global Ctrl+Shift+O hotkey on Windows to summon/focus the top bar."""
    if os.name != "nt":
        return

    def _loop():
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        MOD_CONTROL = 0x0002
        MOD_SHIFT = 0x0004
        VK_O = 0x4F
        WM_HOTKEY = 0x0312
        hotkey_id = 1
        if not user32.RegisterHotKey(None, hotkey_id, MOD_CONTROL | MOD_SHIFT, VK_O):
            return
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY and msg.wParam == hotkey_id:
                    on_trigger()
        finally:
            user32.UnregisterHotKey(None, hotkey_id)

    threading.Thread(target=_loop, daemon=True).start()


class OverlayApi:
    def __init__(self, screen_w: int, screen_h: int):
        self._screen_w = screen_w
        self._screen_h = screen_h
        self._window = None

    def _center_x(self, width: int) -> int:
        return max(0, (self._screen_w - width) // 2)

    def collapse(self) -> dict:
        if self._window is not None:
            w = min(PILL_W, self._screen_w - 24)
            self._window.resize(w, PILL_H)
            self._window.move(self._center_x(w), TOP_MARGIN)
        return {"collapsed": True}

    def expand(self) -> dict:
        if self._window is not None:
            w = min(1260, self._screen_w - 48)
            h = min(780, self._screen_h - 72)
            self._window.resize(w, h)
            self._window.move(self._center_x(w), TOP_MARGIN)
        return {"collapsed": False}

    def capture_screen(self) -> dict:
        if self._window is not None:
            self._window.hide()
            time.sleep(0.18)
        try:
            shot = ImageGrab.grab(all_screens=False)
            buf = io.BytesIO()
            shot.convert("RGB").save(buf, format="JPEG", quality=90)
            image_id, _ = server._save_image_bytes(buf.getvalue())
            return {"image_id": image_id, "url": f"/out/uploads/{image_id}.jpg"}
        finally:
            if self._window is not None:
                self._window.show()

    def snip_screen(self) -> dict:
        if self._window is not None:
            self._window.hide()
            time.sleep(0.15)
        tmp = Path(tempfile.gettempdir()) / f"opto_snip_{os.getpid()}.jpg"
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "opto.desktop", "--snip", str(tmp)],
                cwd=str(server.ROOT),
                check=False,
            )
            if proc.returncode == 0 and tmp.is_file():
                image_id, _ = server._save_image_bytes(tmp.read_bytes())
                return {"image_id": image_id, "url": f"/out/uploads/{image_id}.jpg"}
            return {}
        finally:
            tmp.unlink(missing_ok=True)
            if self._window is not None:
                self._window.show()

    def close(self) -> None:
        if self._window is not None:
            self._window.destroy()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) >= 2 and args[0] == "--snip":
        return _run_snip_tool(args[1])

    import webview

    port = int(os.environ.get("OPTO_PORT", str(_pick_port(8765))))
    _start_server(port)

    screens = webview.screens
    screen_w = screens[0].width if screens else 1920
    screen_h = screens[0].height if screens else 1080
    pill_w = min(PILL_W, screen_w - 24)
    start_x = max(0, (screen_w - pill_w) // 2)

    api = OverlayApi(screen_w, screen_h)
    window = webview.create_window(
        "Opto",
        url=f"http://127.0.0.1:{port}/?overlay=1",
        js_api=api,
        width=pill_w,
        height=PILL_H,
        x=start_x,
        y=TOP_MARGIN,
        frameless=True,
        on_top=True,
        easy_drag=False,
        background_color="#0b0e13",
    )
    api._window = window

    def _summon():
        try:
            window.show()
            window.evaluate_js("window.__optoFocus && window.__optoFocus()")
        except Exception:
            pass

    _register_windows_hotkey(_summon)
    print(f"[opto] floating bar live at http://127.0.0.1:{port}/  (hotkey: Ctrl+Shift+O)", flush=True)
    webview.start(debug="--debug" in args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
