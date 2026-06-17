"""System-tray icon for Claude Monitor.

Renders the live 5h-window usage percentage as the tray icon itself
(color-coded), with a hover tooltip showing cost + reset countdown.
Right-click menu toggles the floating overlay, refreshes, restarts, or quits.

Runs the pystray icon on a detached thread; all overlay/tkinter calls are
marshalled back to the main thread via ``overlay.root.after``.
"""

import subprocess
import sys
import threading

import pystray
from PIL import Image, ImageDraw, ImageFont

import config as cfg_module
from fetcher import fmt_countdown
from overlay import window_reset_secs

# RGB versions of the overlay's threshold colors
GREEN  = (63, 185, 80)
YELLOW = (210, 153, 34)
RED    = (248, 81, 73)
DIM    = (139, 148, 158)

ICON_SIZE = 128


def _color(pct):
    if pct is None:
        return DIM
    if pct < 70:
        return GREEN
    if pct < 90:
        return YELLOW
    return RED


def _load_font(size):
    for name in ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


TRACK = (48, 54, 61, 255)   # progress-bar background


def _fit_font(d, text, max_w, max_h):
    """Largest font for which `text` fits within max_w x max_h."""
    size = max_h
    while size > 8:
        font = _load_font(size)
        bbox = d.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_w and (bbox[3] - bbox[1]) <= max_h:
            return font, bbox
        size -= 2
    font = _load_font(8)
    return font, d.textbbox((0, 0), text, font=font)


def _render(pct):
    """Draw 'NN%' as large as possible over a thin color-coded progress bar."""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = _color(pct) + (255,)

    pad = 2
    bar_h = max(6, ICON_SIZE // 11)         # thin strip at the bottom
    text_region = ICON_SIZE - bar_h - pad

    # ── percentage number — auto-fit to fill the icon ──
    text = "—" if pct is None else str(int(round(pct)))
    font, bbox = _fit_font(d, text, ICON_SIZE - 2 * pad, text_region)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (ICON_SIZE - tw) / 2 - bbox[0]
    ty = (text_region - th) / 2 - bbox[1]
    d.text((tx, ty), text, font=font, fill=color)

    # ── progress bar (bottom) ──
    bx0, bx1 = pad, ICON_SIZE - pad
    by0, by1 = ICON_SIZE - bar_h, ICON_SIZE - 1
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=3, fill=TRACK)
    frac = 0.0 if pct is None else max(0.0, min(1.0, pct / 100.0))
    fw = int(round((bx1 - bx0 - 2) * frac))
    if fw > 0:
        d.rectangle([bx0 + 1, by0 + 2, bx0 + 1 + fw, by1 - 2], fill=color)
    return img


class TrayIcon:
    def __init__(self, fetcher, config, overlay):
        self.fetcher = fetcher
        self.config = config
        self.overlay = overlay
        self._last_data = {}
        self._last_pct = None

        self.icon = pystray.Icon(
            "claude_monitor",
            icon=_render(None),
            title="Claude Monitor — loading…",
            menu=self._build_menu(),
        )
        fetcher.add_callback(self._on_data)

    # ── Menu ────────────────────────────────────────────────────────────────────

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(
                "Show overlay",
                self._toggle_overlay,
                checked=lambda _i: self.overlay.is_visible(),
            ),
            pystray.MenuItem("Refresh now", self._refresh),
            pystray.MenuItem("Restart", self._restart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _toggle_overlay(self, _icon, _item):
        self.overlay.root.after(0, self._do_toggle_overlay)

    def _do_toggle_overlay(self):
        self.overlay.toggle()
        self.config["overlay_visible"] = self.overlay.is_visible()
        try:
            cfg_module.save(self.config)
        except Exception:
            pass
        self.icon.update_menu()

    def _refresh(self, _icon=None, _item=None):
        threading.Thread(target=self.fetcher.refresh, daemon=True).start()

    def _restart(self, _icon=None, _item=None):
        subprocess.Popen([sys.executable] + sys.argv)
        self._quit()

    def _quit(self, _icon=None, _item=None):
        self.icon.stop()
        self.overlay.request_quit()

    # ── Data / tooltip ───────────────────────────────────────────────────────────

    def _on_data(self, data):
        self._last_data = data
        pct = data.get("window_pct")
        if pct != self._last_pct:
            self._last_pct = pct
            self.icon.icon = _render(pct)
        self._update_tooltip()

    def _update_tooltip(self):
        pct = self._last_data.get("window_pct")
        cost = self._last_data.get("window", {}).get("total_cost", 0)
        secs = window_reset_secs(self._last_data, self.config)
        parts = ["5h"]
        parts.append("—%" if pct is None else f"{pct:.0f}%")
        parts.append(f"${cost:.2f}")
        parts.append("↺ fresh" if secs is None else f"↺ {fmt_countdown(secs)}")
        self.icon.title = " · ".join(parts)

    # ── Lifecycle ────────────────────────────────────────────────────────────────

    def _tick_tooltip(self):
        """Refresh the countdown in the tooltip once a second."""
        self._update_tooltip()
        self.overlay.root.after(1000, self._tick_tooltip)

    def start(self):
        self.icon.run_detached()
        # ensure the icon populates even if the fetcher's first refresh
        # fired before this callback was registered
        self._refresh()
        # drive the tooltip countdown off the tkinter main loop
        self.overlay.root.after(1000, self._tick_tooltip)
