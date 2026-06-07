import threading
import tkinter as tk

BG      = "#0d1117"
ACCENT  = "#58a6ff"
TEXT    = "#e6edf3"
DIM     = "#8b949e"
GREEN   = "#3fb950"
YELLOW  = "#d29922"
RED     = "#f85149"
DIVIDER = "#21262d"


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


class Overlay:
    def __init__(self, fetcher, config):
        self.fetcher = fetcher
        self.config = config
        self._drag_x = 0
        self._drag_y = 0

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
        self.root.bind("<B1-Motion>", self._drag_motion)
        self.root.bind("<Button-3>", self._show_menu)

        fetcher.add_callback(self._on_data)
        fetcher.start()

    def _build_ui(self):
        # Header
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(header, text="◆ Claude Monitor", bg=BG, fg=ACCENT,
                 font=("Consolas", 10, "bold")).pack(side="left")
        self.lbl_time = tk.Label(header, text="loading…", bg=BG, fg=DIM,
                                  font=("Consolas", 8))
        self.lbl_time.pack(side="right")

        tk.Frame(self.root, bg=DIVIDER, height=1).pack(fill="x", padx=6)

        # Stats grid
        grid = tk.Frame(self.root, bg=BG)
        grid.pack(fill="x", padx=10, pady=6)

        self.lbl_cost    = self._row(grid, "Cost",     "$0.00",  GREEN)
        self.lbl_input   = self._row(grid, "Input",    "0",      TEXT)
        self.lbl_output  = self._row(grid, "Output",   "0",      TEXT)
        self.lbl_cache_r = self._row(grid, "Cache↗",  "0",      DIM)
        self.lbl_cache_w = self._row(grid, "Cache↙",  "0",      DIM)

        tk.Frame(self.root, bg=DIVIDER, height=1).pack(fill="x", padx=6)

        # Footer
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=10, pady=(3, 7))
        self.lbl_sessions = tk.Label(footer, text="—", bg=BG, fg=DIM,
                                      font=("Consolas", 8))
        self.lbl_sessions.pack(side="left")
        self.lbl_range = tk.Label(footer, text="today", bg=BG, fg=DIM,
                                   font=("Consolas", 8))
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
        today_only = self.config.get("today_only", True)
        menu.add_command(
            label="Show all time" if today_only else "Show today only",
            command=self._toggle_range,
        )
        menu.add_separator()
        menu.add_command(label="Quit", command=self.root.quit)
        menu.tk_popup(e.x_root, e.y_root)

    def _force_refresh(self):
        threading.Thread(target=self.fetcher.refresh, daemon=True).start()

    def _toggle_range(self):
        self.config["today_only"] = not self.config.get("today_only", True)
        self.lbl_range.config(text="today" if self.config["today_only"] else "all time")
        self._force_refresh()

    def _on_data(self, data):
        self.root.after(0, self._update_ui, data)

    def _update_ui(self, data):
        cost    = data.get("total_cost", 0)
        inp     = data.get("input_tokens", 0)
        out     = data.get("output_tokens", 0)
        cache_r = data.get("cache_read_tokens", 0)
        cache_w = data.get("cache_creation_tokens", 0)
        sessions = data.get("session_count", 0)
        msgs    = data.get("message_count", 0)
        updated = data.get("last_updated", "—")

        self.lbl_cost.config(text=f"${cost:.4f}", fg=_cost_color(cost))
        self.lbl_input.config(text=_fmt(inp))
        self.lbl_output.config(text=_fmt(out))
        self.lbl_cache_r.config(text=_fmt(cache_r))
        self.lbl_cache_w.config(text=_fmt(cache_w))
        self.lbl_sessions.config(text=f"{sessions} sess · {msgs} msgs")
        self.lbl_time.config(text=updated)

    def run(self):
        self.root.mainloop()
