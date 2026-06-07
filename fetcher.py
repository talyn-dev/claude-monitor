import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _merge(dst, src):
    for k in ("input_tokens", "output_tokens", "cache_creation_tokens",
              "cache_read_tokens", "total_cost", "message_count", "session_count"):
        dst[k] = dst.get(k, 0) + src.get(k, 0)
    for model, vals in src.get("by_model", {}).items():
        if model not in dst["by_model"]:
            dst["by_model"][model] = {"input": 0, "output": 0, "cost": 0.0}
        dst["by_model"][model]["input"] += vals.get("input", 0)
        dst["by_model"][model]["output"] += vals.get("output", 0)
        dst["by_model"][model]["cost"] += vals.get("cost", 0.0)


def seconds_until_daily_reset():
    now = datetime.now(timezone.utc)
    tomorrow = now.date() + timedelta(days=1)
    reset = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc)
    return max(0, int((reset - now).total_seconds()))


def seconds_until_weekly_reset(week_start_day=6):
    now = datetime.now(timezone.utc)
    days_until = (week_start_day - now.weekday()) % 7 or 7
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


# ── Anthropic Admin API ───────────────────────────────────────────────────────

_API_BASE = "https://api.anthropic.com"


def _api_get(path, params, admin_key):
    url = f"{_API_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "x-api-key": admin_key,
        "anthropic-version": "2023-06-01",
        "User-Agent": "ClaudeMonitor/1.0",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _fetch_claude_code_day(admin_key, day):
    """Fetch Claude Code Analytics for a single day. Returns _empty_totals dict."""
    totals = _empty_totals()
    params = {"starting_at": day.isoformat(), "limit": 1000}

    while True:
        data = _api_get("/v1/organizations/usage_report/claude_code", params, admin_key)

        for record in data.get("data", []):
            core = record.get("core_metrics", {})
            totals["session_count"] += core.get("num_sessions", 0)

            for mb in record.get("model_breakdown", []):
                tokens = mb.get("tokens", {})
                cost_cents = mb.get("estimated_cost", {}).get("amount", 0)
                model = mb.get("model", "")

                inp   = tokens.get("input", 0)
                out   = tokens.get("output", 0)
                cache_r = tokens.get("cache_read", 0)
                cache_w = tokens.get("cache_creation", 0)
                cost  = cost_cents / 100.0  # cents → dollars

                totals["input_tokens"]         += inp
                totals["output_tokens"]        += out
                totals["cache_read_tokens"]    += cache_r
                totals["cache_creation_tokens"] += cache_w
                totals["total_cost"]           += cost
                totals["message_count"]        += 1

                if model not in totals["by_model"]:
                    totals["by_model"][model] = {"input": 0, "output": 0, "cost": 0.0}
                totals["by_model"][model]["input"]  += inp
                totals["by_model"][model]["output"] += out
                totals["by_model"][model]["cost"]   += cost

        if not data.get("has_more"):
            break
        params["page"] = data["next_page"]

    return totals


# ── Fetcher ───────────────────────────────────────────────────────────────────

class UsageFetcher:
    def __init__(self, config):
        self.config = config
        self._data = {}
        self._lock = threading.Lock()
        self._callbacks = []
        self._stop = threading.Event()
        # Cache past-day API results so they're only fetched once per session
        self._day_cache: dict[str, dict] = {}

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

    # ── Anthropic API path ────────────────────────────────────────────────────

    def _fetch_from_api(self, admin_key):
        today = date.today()
        week_start_day = self.config.get("week_start_day", 6)
        days_since_start = (today.weekday() - week_start_day) % 7
        week_start = today - timedelta(days=days_since_start)

        week_days = [week_start + timedelta(days=i) for i in range(days_since_start + 1)]
        today_str = today.isoformat()

        def fetch_day(d):
            key = d.isoformat()
            if key != today_str and key in self._day_cache:
                return key, self._day_cache[key]
            result = _fetch_claude_code_day(admin_key, d)
            if key != today_str:
                self._day_cache[key] = result
            return key, result

        today_totals = _empty_totals()
        week_totals = _empty_totals()

        with ThreadPoolExecutor(max_workers=min(7, len(week_days))) as ex:
            futures = {ex.submit(fetch_day, d): d for d in week_days}
            for f in as_completed(futures):
                try:
                    key, day_data = f.result()
                    _merge(week_totals, day_data)
                    if key == today_str:
                        _merge(today_totals, day_data)
                except Exception:
                    pass

        return {"today": today_totals, "week": week_totals, "source": "api"}

    # ── Local JSONL path ──────────────────────────────────────────────────────

    def _scan_local(self):
        claude_dir = Path(self.config["claude_dir"])
        projects_dir = claude_dir / "projects"
        if not projects_dir.exists():
            return {"today": _empty_totals(), "week": _empty_totals(), "source": "local"}

        today = date.today()
        today_str = today.isoformat()
        week_start_day = self.config.get("week_start_day", 6)
        days_since_start = (today.weekday() - week_start_day) % 7
        week_start_str = (today - timedelta(days=days_since_start)).isoformat()

        today_totals = _empty_totals()
        week_totals = _empty_totals()
        today_sessions: set = set()
        week_sessions: set = set()

        for jsonl_file in projects_dir.rglob("*.jsonl"):
            try:
                self._parse_jsonl(jsonl_file, today_str, week_start_str,
                                  today_totals, week_totals, today_sessions, week_sessions)
            except Exception:
                pass

        today_totals["session_count"] = len(today_sessions)
        week_totals["session_count"] = len(week_sessions)
        return {"today": today_totals, "week": week_totals, "source": "local"}

    def _parse_jsonl(self, path, today_str, week_start_str,
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

                date_str = record.get("timestamp", "")[:10]
                if date_str < week_start_str:
                    continue

                in_today = date_str == today_str
                session_id = record.get("sessionId", str(path))
                week_sessions.add(session_id)
                if in_today:
                    today_sessions.add(session_id)

                model = msg.get("model", "")
                prices = pricing.get(model) or _match_pricing(pricing, model)

                inp     = usage.get("input_tokens", 0)
                out     = usage.get("output_tokens", 0)
                cache_w = usage.get("cache_creation_input_tokens", 0)
                cache_r = usage.get("cache_read_input_tokens", 0)
                cost = (
                    (inp / 1_000_000) * prices["input"]
                    + (out / 1_000_000) * prices["output"]
                    + (cache_w / 1_000_000) * prices["cache_write"]
                    + (cache_r / 1_000_000) * prices["cache_read"]
                )

                def _add(t):
                    t["input_tokens"] += inp
                    t["output_tokens"] += out
                    t["cache_creation_tokens"] += cache_w
                    t["cache_read_tokens"] += cache_r
                    t["total_cost"] += cost
                    t["message_count"] += 1
                    if model not in t["by_model"]:
                        t["by_model"][model] = {"input": 0, "output": 0, "cost": 0.0}
                    t["by_model"][model]["input"] += inp
                    t["by_model"][model]["output"] += out
                    t["by_model"][model]["cost"] += cost

                _add(week_totals)
                if in_today:
                    _add(today_totals)

    # ── Main refresh ──────────────────────────────────────────────────────────

    def refresh(self):
        admin_key = self.config.get("admin_api_key", "").strip()
        if admin_key:
            try:
                data = self._fetch_from_api(admin_key)
            except urllib.error.HTTPError as e:
                data = self._scan_local()
                data["api_error"] = f"HTTP {e.code}: {e.reason}"
            except Exception as e:
                data = self._scan_local()
                data["api_error"] = str(e)
        else:
            data = self._scan_local()

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
