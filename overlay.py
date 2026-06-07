import threading
import tkinter as tk
from fetcher import fmt_countdown, seconds_until_daily_reset, seconds_until_weekly_reset

BG      = "#0d1117"
ACCENT  = "#58a6ff"
TEXT    = "#e6edf3"
DIM     = "#8b949e"
GREEN   = "#3fb950"
YELLOW  = "#d29922"
RED     = "#f85149"
DIVIDER = "#21262d"
BAR_BG  = "#21262d"


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


def _fmt(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


class _ProgressBar:
    """Thin canvas-based horizontal bar that can be updated via set_pct()."""

    def __init__(self, parent, height=5):
        self._canvas = tk.Canvas(parent, height=height, bg=BG, highlightthickness=0)
        self._canvas.pack(fill="x", padx=10, pady=(1, 3))
        self._bar_id = None
        self._color = GREEN
        self._canvas.bind("<Configure>", self._on_resize)
        self._pct = 0.0

    def set_pct(self, pct, color):
        self._pct = max(0.0, min(1.0, pct))
        self._color = color
        self._draw()

    def _on_resize(self, _event):
        self._draw()

    def _draw(self):
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w <= 1:
            return
        self._canvas.delete("all")
        self._canvas.create_rectangle(0, 0, w, h, fill=BAR_BG, outline="")
        fill_w = int(w * self._pct)
        if fill_w > 0:
            self._canvas.create_rectangle(0, 0, fill_w, h, fill=self._color, outline="")


class Overlay:
    def __init__(self, fetcher, config):
        self.fetcher = fetcher
        self.config = config
        self._drag_x = 0
        self._drag_y = 0
        self._last_data = {}

        self.root = tk.Tk()
        self.root.title("Claude Monitor")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", config.get("opacity", 0.88))
        self.root.configure(bg=BG)
        self.root.minsize(220, 10)

        self._build_ui()
        self._position_top_right()

        self.root.bind("<ButtonPress-1>", self._drag_start)
        self.root.bind("<B1-Motion>", self._drag_motion)
        self.root.bind("<Button-3>", self._show_menu)

        fetcher.add_callback(self._on_data)
        fetcher.start()

        self._tick_countdowns()

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(header, text="◆ Claude Monitor", bg=BG, fg=ACCENT,
                 font=("Consolas", 10, "bold")).pack(side="left")
        self.lbl_time = tk.Label(header, text="loading…", bg=BG, fg=DIM,
                                  font=("Consolas", 8))
        self.lbl_time.pack(side="right")

        tk.Frame(self.root, bg=DIVIDER, height=1).pack(fill="x", padx=6)

        # ── Token stats ──────────────────────────────────────────────────────
        grid = tk.Frame(self.root, bg=BG)
        grid.pack(fill="x", padx=10, pady=6)
        self.lbl_cost    = self._row(grid, "Cost",    "$0.00", GREEN)
        self.lbl_input   = self._row(grid, "Input",   "0",     TEXT)
        self.lbl_output  = self._row(grid, "Output",  "0",     TEXT)
        self.lbl_cache_r = self._row(grid, "Cache↗", "0",     DIM)
        self.lbl_cache_w = self._row(grid, "Cache↙", "0",     DIM)

        tk.Frame(self.root, bg=DIVIDER, height=1).pack(fill="x", padx=6)

        # ── Usage % section ─────────────────────────────────────────────────
        usage = tk.Frame(self.root, bg=BG)
        usage.pack(fill="x", pady=(6, 2))

        # Daily row
        daily_row = tk.Frame(usage, bg=BG)
        daily_row.pack(fill="x", padx=10)
        tk.Label(daily_row, text="Daily", bg=BG, fg=DIM,
                 font=("Consolas", 9)).pack(side="left")
        self.lbl_daily_pct = tk.Label(daily_row, text="—", bg=BG, fg=DIM,
                                       font=("Consolas", 9, "bold"))
        self.lbl_daily_pct.pack(side="left", padx=(6, 0))
        self.lbl_daily_reset = tk.Label(daily_row, text="", bg=BG, fg=DIM,
                                         font=("Consolas", 8))
        self.lbl_daily_reset.pack(side="right")
        self.bar_daily = _ProgressBar(usage)

        # Weekly row
        week_row = tk.Frame(usage, bg=BG)
        week_row.pack(fill="x", padx=10, pady=(4, 0))
        tk.Label(week_row, text="Weekly", bg=BG, fg=DIM,
                 font=("Consolas", 9)).pack(side="left")
        self.lbl_week_pct = tk.Label(week_row, text="—", bg=BG, fg=DIM,
                                      font=("Consolas", 9, "bold"))
        self.lbl_week_pct.pack(side="left", padx=(6, 0))
        self.lbl_week_reset = tk.Label(week_row, text="", bg=BG, fg=DIM,
                                        font=("Consolas", 8))
        self.lbl_week_reset.pack(side="right")
        self.bar_week = _ProgressBar(usage)

        tk.Frame(self.root, bg=DIVIDER, height=1).pack(fill="x", padx=6, pady=(4, 0))

        # ── Footer ──────────────────────────────────────────────────────────
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=10, pady=(3, 7))
        self.lbl_sessions = tk.Label(footer, text="—", bg=BG, fg=DIM,
                                      font=("Consolas", 8))
        self.lbl_sessions.pack(side="left")
        self.lbl_range = tk.Label(footer,
                                   text=config_range_label(self.config),
                                   bg=BG, fg=DIM, font=("Consolas", 8))
        self.lbl_range.pack(side="right")

    def _row(self, parent, label, value, color):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=f"{label:<9}", bg=BG, fg=DIM,
                 font=("Consolas", 9)).pack(side="left")
        lbl = tk.Label(row, text=value, bg=BG, fg=color,
                       font=("Consolas", 10, "bold"))
        lbl.pack(side="right")
        return lbl

    def _position_top_right(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        w = self.root.winfo_reqwidth()
        self.root.geometry(f"+{sw - w - 20}+20")

    def _drag_start(self, e):
        self._drag_x = e.x
        self._drag_y = e.y

    def _drag_motion(self, e):
        x = self.root.winfo_x() + e.x - self._drag_x
        y = self.root.winfo_y() + e.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _show_menu(self, e):
        menu = tk.Menu(self.root, tearoff=0, bg="#161b22", fg=TEXT,
                       activebackground=DIVIDER, font=("Consolas", 9))
        menu.add_command(label="Refresh now", command=self._force_refresh)
        menu.add_separator()
        is_today = self.config.get("display_range", "today") == "today"
        menu.add_command(
            label="Show this week's tokens" if is_today else "Show today's tokens",
            command=self._toggle_range,
        )
        menu.add_separator()
        menu.add_command(label="Quit", command=self.root.quit)
        menu.tk_popup(e.x_root, e.y_root)

    def _force_refresh(self):
        threading.Thread(target=self.fetcher.refresh, daemon=True).start()

    def _toggle_range(self):
        current = self.config.get("display_range", "today")
        self.config["display_range"] = "week" if current == "today" else "today"
        self.lbl_range.config(text=config_range_label(self.config))
        if self._last_data:
            self._update_ui(self._last_data)

    def _on_data(self, data):
        self.root.after(0, self._update_ui, data)

    def _update_ui(self, data):
        self._last_data = data
        display_range = self.config.get("display_range", "today")
        d = data.get(display_range, data.get("today", {}))

        cost    = d.get("total_cost", 0)
        inp     = d.get("input_tokens", 0)
        out     = d.get("output_tokens", 0)
        cache_r = d.get("cache_read_tokens", 0)
        cache_w = d.get("cache_creation_tokens", 0)
        sessions = d.get("session_count", 0)
        msgs    = d.get("message_count", 0)
        updated = data.get("last_updated", "—")

        self.lbl_cost.config(text=f"${cost:.4f}", fg=_cost_color(cost))
        self.lbl_input.config(text=_fmt(inp))
        self.lbl_output.config(text=_fmt(out))
        self.lbl_cache_r.config(text=_fmt(cache_r))
        self.lbl_cache_w.config(text=_fmt(cache_w))
        self.lbl_sessions.config(text=f"{sessions} sess · {msgs} msgs")
        self.lbl_time.config(text=updated)

        # Usage bars
        daily_cost  = data.get("today", {}).get("total_cost", 0)
        weekly_cost = data.get("week",  {}).get("total_cost", 0)
        d_limit = self.config.get("daily_limit_usd", 0)
        w_limit = self.config.get("weekly_limit_usd", 0)

        self._update_bar(
            self.bar_daily, self.lbl_daily_pct, daily_cost, d_limit
        )
        self._update_bar(
            self.bar_week, self.lbl_week_pct, weekly_cost, w_limit
        )

    def _update_bar(self, bar, lbl, cost, limit):
        if limit and limit > 0:
            pct = cost / limit
            color = _pct_color(pct)
            lbl.config(text=f"{pct * 100:.1f}%", fg=color)
            bar.set_pct(pct, color)
        else:
            lbl.config(text="—", fg=DIM)
            bar.set_pct(0, BAR_BG)

    def _tick_countdowns(self):
        week_start_day = self.config.get("week_start_day", 6)
        d_secs = seconds_until_daily_reset()
        w_secs = seconds_until_weekly_reset(week_start_day)
        self.lbl_daily_reset.config(text=f"↺ {fmt_countdown(d_secs)}")
        self.lbl_week_reset.config(text=f"↺ {fmt_countdown(w_secs)}")
        self.root.after(1000, self._tick_countdowns)

    def run(self):
        self.root.mainloop()


def config_range_label(config):
    return "today" if config.get("display_range", "today") == "today" else "this week"
