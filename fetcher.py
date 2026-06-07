import json
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _match_pricing(pricing, model):
    for key, prices in pricing.items():
        if key != "default" and model.startswith(key):
            return prices
    return pricing["default"]


def _empty_totals():
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "total_cost": 0.0,
        "message_count": 0,
        "session_count": 0,
        "by_model": {},
    }


def seconds_until_daily_reset():
    now = datetime.now(timezone.utc)
    tomorrow = now.date() + timedelta(days=1)
    reset = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc)
    return max(0, int((reset - now).total_seconds()))


def seconds_until_weekly_reset(week_start_day=6):
    now = datetime.now(timezone.utc)
    today_wd = now.weekday()  # Mon=0, Sun=6
    days_until = (week_start_day - today_wd) % 7
    if days_until == 0:
        days_until = 7
    reset_date = now.date() + timedelta(days=days_until)
    reset = datetime(reset_date.year, reset_date.month, reset_date.day, tzinfo=timezone.utc)
    return max(0, int((reset - now).total_seconds()))


def fmt_countdown(seconds):
    if seconds <= 0:
        return "now"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d > 0:
        return f"{d}d {h}h {m}m"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


class UsageFetcher:
    def __init__(self, config):
        self.config = config
        self._data = {}
        self._lock = threading.Lock()
        self._callbacks = []
        self._stop = threading.Event()

    def add_callback(self, fn):
        self._callbacks.append(fn)

    def get_data(self):
        with self._lock:
            return dict(self._data)

    def _notify(self, data):
        for cb in self._callbacks:
            try:
                cb(data)
            except Exception:
                pass

    def _scan(self):
        claude_dir = Path(self.config["claude_dir"])
        projects_dir = claude_dir / "projects"
        if not projects_dir.exists():
            return {"today": _empty_totals(), "week": _empty_totals()}

        today = date.today()
        today_str = today.isoformat()

        week_start_day = self.config.get("week_start_day", 6)
        days_since_start = (today.weekday() - week_start_day) % 7
        week_start = today - timedelta(days=days_since_start)
        week_start_str = week_start.isoformat()

        today_totals = _empty_totals()
        week_totals = _empty_totals()
        today_sessions = set()
        week_sessions = set()

        for jsonl_file in projects_dir.rglob("*.jsonl"):
            try:
                self._parse_file(
                    jsonl_file, today_str, week_start_str,
                    today_totals, week_totals, today_sessions, week_sessions,
                )
            except Exception:
                pass

        today_totals["session_count"] = len(today_sessions)
        week_totals["session_count"] = len(week_sessions)
        return {"today": today_totals, "week": week_totals}

    def _parse_file(self, path, today_str, week_start_str,
                    today_totals, week_totals, today_sessions, week_sessions):
        pricing = self.config["pricing"]

        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if record.get("type") != "assistant":
                    continue

                msg = record.get("message", {})
                usage = msg.get("usage")
                if not usage:
                    continue

                timestamp = record.get("timestamp", "")
                date_str = timestamp[:10]  # "YYYY-MM-DD"

                in_week = date_str >= week_start_str
                in_today = date_str == today_str

                if not in_week:
                    continue

                session_id = record.get("sessionId", str(path))
                week_sessions.add(session_id)
                if in_today:
                    today_sessions.add(session_id)

                model = msg.get("model", "")
                prices = pricing.get(model) or _match_pricing(pricing, model)

                inp = usage.get("input_tokens", 0)
                out = usage.get("output_tokens", 0)
                cache_w = usage.get("cache_creation_input_tokens", 0)
                cache_r = usage.get("cache_read_input_tokens", 0)

                cost = (
                    (inp / 1_000_000) * prices["input"]
                    + (out / 1_000_000) * prices["output"]
                    + (cache_w / 1_000_000) * prices["cache_write"]
                    + (cache_r / 1_000_000) * prices["cache_read"]
                )

                def _add(totals, sessions_set, session_id):
                    totals["input_tokens"] += inp
                    totals["output_tokens"] += out
                    totals["cache_creation_tokens"] += cache_w
                    totals["cache_read_tokens"] += cache_r
                    totals["total_cost"] += cost
                    totals["message_count"] += 1
                    if model not in totals["by_model"]:
                        totals["by_model"][model] = {"input": 0, "output": 0, "cost": 0.0}
                    totals["by_model"][model]["input"] += inp
                    totals["by_model"][model]["output"] += out
                    totals["by_model"][model]["cost"] += cost

                _add(week_totals, week_sessions, session_id)
                if in_today:
                    _add(today_totals, today_sessions, session_id)

    def refresh(self):
        data = self._scan()
        data["last_updated"] = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._data = data
        self._notify(data)

    def _loop(self):
        while not self._stop.is_set():
            self.refresh()
            self._stop.wait(self.config["refresh_interval"])

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()
