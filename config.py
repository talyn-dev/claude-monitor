import json
from pathlib import Path

DEFAULT = {
    "refresh_interval": 30,
    "claude_dir": str(Path.home() / ".claude"),
    # Optional short name shown in the tray tooltip / overlay title, so multiple
    # instances (e.g. one per claude.ai account) are distinguishable. Blank = none.
    "label": "",
    # Skip the local JSONL cost scan entirely. Use when you only want the live
    # claude.ai usage % — avoids a slow per-refresh scan of a large
    # ~/.claude/projects history (the $ cost estimate is then omitted).
    "skip_local_scan": False,
    "opacity": 0.88,
    "width_scale": 0.5,             # overlay width as a fraction of its natural width
    "overlay_visible": False,       # floating overlay hidden by default; tray is primary
    "display_range": "today",       # "today" or "week"
    "week_start_day": 6,            # 0=Mon … 6=Sun
    "window_hours": 5,              # rolling usage window (Claude Code resets every 5h)
    "window_limit_usd": 0,          # 0 = not configured; only used if claude_session is empty
    "weekly_limit_usd": 0,          # 0 = not configured; only used if claude_session is empty
    # Paste your claude.ai sessionKey cookie here for real % from the API.
    # Leave blank to auto-read from Chrome (works when Chrome is closed).
    "claude_session": "",
    # Set this to your Admin API key (sk-ant-admin...) from
    # console.anthropic.com/settings/admin-keys
    # Requires an organization account. Leave blank to use local JSONL files.
    "admin_api_key": "",
    "pricing": {
        "claude-opus-4-8":  {"input": 5.0,  "output": 25.0, "cache_write": 6.25, "cache_read": 0.50},
        "claude-opus-4-7":  {"input": 5.0,  "output": 25.0, "cache_write": 6.25, "cache_read": 0.50},
        "claude-opus-4-6":  {"input": 5.0,  "output": 25.0, "cache_write": 6.25, "cache_read": 0.50},
        "claude-sonnet-4-6":{"input": 3.0,  "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
        "claude-haiku-4-5": {"input": 1.0,  "output": 5.0,  "cache_write": 1.25, "cache_read": 0.10},
        "default":          {"input": 3.0,  "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    },
}

CONFIG_PATH = Path(__file__).parent / "config.json"

# Path of the config file in use for this process. Set by load(path=...) so a
# later save() (e.g. when the overlay toggles) writes back to the same file —
# important when running multiple instances via `--config`.
_active_path = CONFIG_PATH


def load(path=None):
    global _active_path
    _active_path = Path(path) if path else CONFIG_PATH
    if _active_path.exists():
        with open(_active_path) as f:
            saved = json.load(f)
        merged = {**DEFAULT, **saved}
        merged["pricing"] = {**DEFAULT["pricing"], **saved.get("pricing", {})}
        return merged
    return dict(DEFAULT)


def save(cfg, path=None):
    target = Path(path) if path else _active_path
    with open(target, "w") as f:
        json.dump(cfg, f, indent=2)
