import json
from pathlib import Path

DEFAULT = {
    "refresh_interval": 30,
    "claude_dir": str(Path.home() / ".claude"),
    "opacity": 0.88,
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


def load():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            saved = json.load(f)
        merged = {**DEFAULT, **saved}
        merged["pricing"] = {**DEFAULT["pricing"], **saved.get("pricing", {})}
        return merged
    return dict(DEFAULT)


def save(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
