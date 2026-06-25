import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone

from fetcher import fmt_countdown, seconds_until_window_rolls, _parse_ts

BG      = "#0d1117"
ACCENT  = "#58a6ff"
DIM     = "#8b949e"
GREEN   = "#3fb950"
YELLOW  = "#d29922"
RED     = "#f85149"
DIVIDER = "#21262d"


def _pct_color(pct):
    if pct < 0.70:
        return GREEN
    if pct < 0.90:
        return YELLOW
    return RED


def _cost_color(cost):
    if cost < 1.0:
        return GREEN
    if cost < 5.0:
        return YELLOW
    return RED


def window_reset_secs(data, config):
    """Seconds until the rolling window resets.

    Prefers the API's resets_at, falls back to oldest_ts math.
    Returns None when the window is fresh / unknown.
    """
    now_epoch = datetime.now(timezone.utc).timestamp()
    win_resets_at = data.get("window_resets_at")
    if win_resets_at:
        resets_epoch = _parse_ts(win_resets_at)
        return max(0, int((resets_epoch or now_epoch) - now_epoch))
    oldest = data.get("window_oldest_ts")
    if oldest:
        return seconds_until_window_rolls(oldest, config.get("window_hours", 5))
    return None


class _Bar:
    def __init__(self, parent, height=4):
        self._c = tk.Canvas(parent, height=height, bg=BG, highlightthickness=0)
        self._c.pack(fill="x", padx=6, pady=(1, 3))
        self._pct   = 0.0
        self._color = DIVIDER
        self._c.bind("<Configure>", lambda _e: self._draw())

    def update(self, pct, color):
        self._pct   = max(0.0, min(1.0, pct))
        self._color = color
        self._draw()

    def _draw(self):
        w, h = self._c.winfo_width(), self._c.winfo_height()
        if w <= 1:
            return
        self._c.delete("all")
        self._c.create_rectangle(0, 0, w, h, fill=DIVIDER, outline="")
        fw = int(w * self._pct)
        if fw > 0:
            self._c.create_rectangle(0, 0, fw, h, fill=self._color, outline="")


class Overlay:
    def __init__(self, fetcher, config):
        self.fetcher   = fetcher
        self.config    = config
        self._drag_x   = self._drag_y = 0
        self._last_data: dict = {}
        self.on_quit   = None   # optional hook (e.g. stop tray) run before quitting

        self.root = tk.Tk()
        self.root.title(config.get("label", "").strip() or "Claude Monitor")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", config.get("opacity", 0.88))
        self.root.configure(bg=BG)
        self.root.minsize(100, 10)

        self._build_ui()
        self._position_top_right()
        self.root.bind("<ButtonPress-1>", self._drag_start)
        self.root.bind("<B1-Motion>",     self._drag_motion)
        self.root.bind("<Button-3>",      self._show_menu)

        self._visible = bool(config.get("overlay_visible", False))
        if not self._visible:
            self.root.withdraw()

        fetcher.add_callback(self._on_data)
        fetcher.start()
        self._tick()

    # ── Visibility ──────────────────────────────────────────────────────────────

    def is_visible(self):
        return self._visible

    def show(self):
        self._visible = True
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self._position_top_right()

    def hide(self):
        self._visible = False
        self.root.withdraw()

    def toggle(self):
        self.hide() if self._visible else self.show()

    def request_quit(self):
        """Thread-safe quit entry point (e.g. from the tray)."""
        self.root.after(0, self._quit)

    def _quit(self):
        if self.on_quit:
            try:
                self.on_quit()
            except Exception:
                pass
        self.root.quit()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        wh = self.config.get("window_hours", 5)

        # Rolling window block
        _, self.lbl_win_cost, self.lbl_win_pct, self.lbl_win_reset = \
            self._bar_block(f"{wh}h window")
        self.bar_win = _Bar(self.root)

        # Footer
        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill="x", padx=6, pady=(1, 3))
        self.lbl_updated = tk.Label(foot, text="—", bg=BG, fg=DIM, font=("Consolas", 6))
        self.lbl_updated.pack(side="left")

    def _bar_block(self, label):
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill="x", padx=6, pady=(4, 0))

        tk.Label(row, text=label, bg=BG, fg=DIM,
                 font=("Consolas", 7)).pack(side="left")

        lbl_pct = tk.Label(row, text="", bg=BG, fg=DIM,
                           font=("Consolas", 7, "bold"))
        lbl_pct.pack(side="left", padx=(3, 0))

        lbl_reset = tk.Label(row, text="", bg=BG, fg=DIM, font=("Consolas", 6))
        lbl_reset.pack(side="right")

        lbl_cost = tk.Label(row, text="$0.00", bg=BG, fg=GREEN,
                            font=("Consolas", 7, "bold"))
        lbl_cost.pack(side="right", padx=(0, 4))

        return row, lbl_cost, lbl_pct, lbl_reset

    # ── Position / drag ───────────────────────────────────────────────────────

    def _position_top_right(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        scale = self.config.get("width_scale", 0.5)
        nat_w = self.root.winfo_reqwidth()
        nat_h = self.root.winfo_reqheight()
        w = max(self.root.minsize()[0], int(nat_w * scale))
        self.root.geometry(f"{w}x{nat_h}+{sw - w - 20}+20")

    def _drag_start(self, e):
        self._drag_x, self._drag_y = e.x, e.y

    def _drag_motion(self, e):
        import ctypes
        x = self.root.winfo_x() + e.x - self._drag_x
        y = self.root.winfo_y() + e.y - self._drag_y
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        # Virtual desktop spans all monitors
        vx = ctypes.windll.user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        vy = ctypes.windll.user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
        vw = ctypes.windll.user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        vh = ctypes.windll.user32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
        snap = 20
        if x - vx < snap:                 x = vx
        elif (vx + vw) - (x + w) < snap:  x = vx + vw - w
        if y - vy < snap:                 y = vy
        elif (vy + vh) - (y + h) < snap:  y = vy + vh - h
        self.root.geometry(f"+{x}+{y}")

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _show_menu(self, e):
        m = tk.Menu(self.root, tearoff=0, bg="#161b22", fg="#e6edf3",
                    activebackground=DIVIDER, font=("Consolas", 9))
        m.add_command(label="Refresh now", command=self._force_refresh)
        m.add_command(label="Restart", command=self._restart)
        m.add_separator()
        m.add_command(label="Quit", command=self._quit)
        m.tk_popup(e.x_root, e.y_root)

    def _restart(self):
        subprocess.Popen([sys.executable] + sys.argv)
        self.root.quit()

    def _force_refresh(self):
        threading.Thread(target=self.fetcher.refresh, daemon=True).start()

    # ── Data updates ──────────────────────────────────────────────────────────

    def _on_data(self, data):
        self.root.after(0, self._update_ui, data)

    def _update_ui(self, data):
        self._last_data = data

        win_cost  = data.get("window", {}).get("total_cost", 0)

        # Use real percentages from claude.ai API if available
        win_pct_api  = data.get("window_pct")   # e.g. 74.0 or None

        self._refresh_block(self.lbl_win_cost,  self.lbl_win_pct,  self.bar_win,
                            win_cost,  win_pct_api,
                            self.config.get("window_limit_usd", 0))
        self.lbl_updated.config(text=data.get("last_updated", "—"))

    def _refresh_block(self, lbl_cost, lbl_pct, bar, cost, api_pct, limit):
        if self.config.get("skip_local_scan"):
            lbl_cost.config(text="")
        else:
            lbl_cost.config(text=f"${cost:.2f}", fg=_cost_color(cost))
        if api_pct is not None:
            pct   = api_pct / 100.0
            color = _pct_color(pct)
            lbl_pct.config(text=f"{api_pct:.0f}%", fg=color)
            bar.update(pct, color)
        elif limit and limit > 0:
            pct   = cost / limit
            color = _pct_color(pct)
            lbl_pct.config(text=f"{pct * 100:.1f}%", fg=color)
            bar.update(pct, color)
        else:
            lbl_pct.config(text="", fg=DIM)
            bar.update(0, DIVIDER)

    # ── Live countdowns ───────────────────────────────────────────────────────

    def _tick(self):
        secs = window_reset_secs(self._last_data, self.config)
        if secs is None:
            self.lbl_win_reset.config(text="↺ fresh")
        else:
            self.lbl_win_reset.config(text=f"↺ {fmt_countdown(secs)}")

        self.root.after(1000, self._tick)

    def run(self):
        self.root.mainloop()
