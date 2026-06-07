import json
from pathlib import Path

DEFAULT = {
    "refresh_interval": 30,
    "claude_dir": str(Path.home() / ".claude"),
    "opacity": 0.88,
    "display_range": "today",       # "today" or "week" for main token display
    "week_start_day": 6,            # 0=Mon … 6=Sun (Sunday is typical US billing week)
    "daily_limit_usd": 0,           # 0 = not configured; set to e.g. 10 to see 44%
    "weekly_limit_usd": 0,          # 0 = not configured
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
