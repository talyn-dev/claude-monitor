import threading
import tkinter as tk
from fetcher import fmt_countdown, seconds_until_daily_reset, seconds_until_weekly_reset

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


class _Bar:
    def __init__(self, parent, height=8):
        self._c = tk.Canvas(parent, height=height, bg=BG, highlightthickness=0)
        self._c.pack(fill="x", padx=12, pady=(2, 6))
        self._pct = 0.0
        self._color = DIVIDER
        self._c.bind("<Configure>", lambda _e: self._draw())

    def update(self, pct, color):
        self._pct = max(0.0, min(1.0, pct))
        self._color = color
        self._draw()

    def _draw(self):
        w, h = self._c.winfo_width(), self._c.winfo_height()
        if w <= 1:
            return
        self._c.delete("all")
        self._c.create_rectangle(0, 0, w, h, fill=DIVIDER, outline="", tags="bg")
        fw = int(w * self._pct)
        if fw > 0:
            self._c.create_rectangle(0, 0, fw, h, fill=self._color, outline="")


class Overlay:
    def __init__(self, fetcher, config):
        self.fetcher = fetcher
        self.config = config
        self._drag_x = self._drag_y = 0
        self._last_data = {}

        self.root = tk.Tk()
        self.root.title("Claude Monitor")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", config.get("opacity", 0.88))
        self.root.configure(bg=BG)
        self.root.minsize(200, 10)

        self._build_ui()
        self._position_top_right()
        self.root.bind("<ButtonPress-1>", self._drag_start)
        self.root.bind("<B1-Motion>",     self._drag_motion)
        self.root.bind("<Button-3>",      self._show_menu)

        fetcher.add_callback(self._on_data)
        fetcher.start()
        self._tick()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Daily block
        self._daily_row, self.lbl_daily_cost, self.lbl_daily_pct, self.lbl_daily_reset = \
            self._bar_block("Daily")
        self.bar_daily = _Bar(self.root)

        tk.Frame(self.root, bg=DIVIDER, height=1).pack(fill="x", padx=8)

        # Weekly block
        self._week_row, self.lbl_week_cost, self.lbl_week_pct, self.lbl_week_reset = \
            self._bar_block("Weekly")
        self.bar_week = _Bar(self.root)

        # Footer
        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill="x", padx=12, pady=(2, 6))
        self.lbl_updated = tk.Label(foot, text="—", bg=BG, fg=DIM, font=("Consolas", 8))
        self.lbl_updated.pack(side="left")

    def _bar_block(self, label):
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill="x", padx=12, pady=(8, 0))

        tk.Label(row, text=label, bg=BG, fg=DIM,
                 font=("Consolas", 9)).pack(side="left")

        lbl_pct = tk.Label(row, text="", bg=BG, fg=DIM,
                           font=("Consolas", 9, "bold"))
        lbl_pct.pack(side="left", padx=(6, 0))

        lbl_reset = tk.Label(row, text="", bg=BG, fg=DIM, font=("Consolas", 8))
        lbl_reset.pack(side="right")

        lbl_cost = tk.Label(row, text="$0.00", bg=BG, fg=GREEN,
                            font=("Consolas", 9, "bold"))
        lbl_cost.pack(side="right", padx=(0, 8))

        return row, lbl_cost, lbl_pct, lbl_reset

    # ── Position / drag ───────────────────────────────────────────────────────

    def _position_top_right(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        w  = self.root.winfo_reqwidth()
        self.root.geometry(f"+{sw - w - 20}+20")

    def _drag_start(self, e):
        self._drag_x, self._drag_y = e.x, e.y

    def _drag_motion(self, e):
        x = self.root.winfo_x() + e.x - self._drag_x
        y = self.root.winfo_y() + e.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _show_menu(self, e):
        m = tk.Menu(self.root, tearoff=0, bg="#161b22", fg="#e6edf3",
                    activebackground=DIVIDER, font=("Consolas", 9))
        m.add_command(label="Refresh now", command=self._force_refresh)
        m.add_separator()
        m.add_command(label="Quit", command=self.root.quit)
        m.tk_popup(e.x_root, e.y_root)

    def _force_refresh(self):
        threading.Thread(target=self.fetcher.refresh, daemon=True).start()

    # ── Data updates ──────────────────────────────────────────────────────────

    def _on_data(self, data):
        self.root.after(0, self._update_ui, data)

    def _update_ui(self, data):
        self._last_data = data
        daily_cost  = data.get("today", {}).get("total_cost", 0)
        weekly_cost = data.get("week",  {}).get("total_cost", 0)
        d_limit = self.config.get("daily_limit_usd",  0)
        w_limit = self.config.get("weekly_limit_usd", 0)
        updated = data.get("last_updated", "—")

        self._refresh_block(
            self.lbl_daily_cost, self.lbl_daily_pct, self.bar_daily,
            daily_cost, d_limit,
        )
        self._refresh_block(
            self.lbl_week_cost, self.lbl_week_pct, self.bar_week,
            weekly_cost, w_limit,
        )
        self.lbl_updated.config(text=updated)

    def _refresh_block(self, lbl_cost, lbl_pct, bar, cost, limit):
        lbl_cost.config(text=f"${cost:.2f}", fg=_cost_color(cost))
        if limit and limit > 0:
            pct   = cost / limit
            color = _pct_color(pct)
            lbl_pct.config(text=f"{pct * 100:.1f}%", fg=color)
            bar.update(pct, color)
        else:
            lbl_pct.config(text="", fg=DIM)
            bar.update(0, DIVIDER)

    # ── Live countdown ────────────────────────────────────────────────────────

    def _tick(self):
        wsd = self.config.get("week_start_day", 6)
        self.lbl_daily_reset.config(text=f"↺ {fmt_countdown(seconds_until_daily_reset())}")
        self.lbl_week_reset.config(text=f"↺ {fmt_countdown(seconds_until_weekly_reset(wsd))}")
        self.root.after(1000, self._tick)

    def run(self):
        self.root.mainloop()
