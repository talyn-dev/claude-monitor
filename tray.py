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


def _render(pct, prefix="", alert=False):
    """Draw '[prefix]NN' as large as possible over a thin color-coded progress bar.

    `prefix` is an optional one-letter tag (e.g. "N"/"S") so multiple instances
    are distinguishable at a glance in the tray without hovering.

    `alert` adds a red stripe along the top — used when the icon is showing the
    weekly "All models" % (instead of the 5h %) because it crossed its threshold,
    so the number is unmistakably the weekly one and not a high 5h reading.
    """
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = _color(pct) + (255,)

    pad = 2
    bar_h = max(6, ICON_SIZE // 11)         # thin strip at the bottom
    top_h = bar_h if alert else 0           # matching alert stripe at the top
    text_region = ICON_SIZE - bar_h - top_h - pad

    # ── label letter + percentage number — auto-fit to fill the icon ──
    text = prefix + ("—" if pct is None else str(int(round(pct))))
    font, bbox = _fit_font(d, text, ICON_SIZE - 2 * pad, text_region)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (ICON_SIZE - tw) / 2 - bbox[0]
    ty = top_h + (text_region - th) / 2 - bbox[1]
    d.text((tx, ty), text, font=font, fill=color)

    # ── alert stripe (top) — only when showing the weekly number ──
    if alert:
        d.rounded_rectangle([pad, 1, ICON_SIZE - pad, top_h], radius=3,
                            fill=RED + (255,))

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
        self._last_state = None   # (displayed_pct, alert) — re-render only on change
        self._weekly_alert = config.get("weekly_alert_pct", 80)

        label = config.get("label", "").strip()
        self._label = label
        self._prefix = label[:1].upper()   # one-letter tag drawn on the icon
        self.icon = pystray.Icon(
            f"claude_monitor_{label}" if label else "claude_monitor",
            icon=_render(None, self._prefix),
            title=f"{label} — loading…" if label else "Claude Monitor — loading…",
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
        shown, alert = self._icon_value(data)
        state = (shown, alert)
        if state != self._last_state:
            self._last_state = state
            self.icon.icon = _render(shown, self._prefix, alert)
        self._update_tooltip()

    def _icon_value(self, data):
        """Which % the icon shows: the weekly 'All models' number when it's over
        the alert threshold (so end-of-week rationing is visible), else the 5h."""
        win = data.get("window_pct")
        wk = data.get("weekly_pct")
        if wk is not None and wk > self._weekly_alert:
            return wk, True
        return win, False

    def _update_tooltip(self):
        pct = self._last_data.get("window_pct")
        wk_pct = self._last_data.get("weekly_pct")
        secs = window_reset_secs(self._last_data, self.config)
        alert = wk_pct is not None and wk_pct > self._weekly_alert
        parts = []
        if self._label:
            parts.append(self._label)
        w5 = "5h —%" if pct is None else f"5h {pct:.0f}%"
        w7 = None if wk_pct is None else f"7d {wk_pct:.0f}%"
        if alert:
            # weekly is what's on the icon and what matters — lead with it
            parts.append(f"⚠ {w7}")
            parts.append(w5)
        else:
            parts.append(w5)
            if w7:
                parts.append(w7)
        if not self.config.get("skip_local_scan"):
            cost = self._last_data.get("window", {}).get("total_cost", 0)
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
