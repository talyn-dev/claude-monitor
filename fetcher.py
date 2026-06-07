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


def _parse_ts(ts_str):
    """ISO 8601 → epoch float, or None."""
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def seconds_until_window_rolls(oldest_epoch, window_hours):
    """How long until the oldest message ages out of the rolling window."""
    if oldest_epoch is None:
        return 0
    rolls_at = oldest_epoch + window_hours * 3600
    return max(0, int(rolls_at - datetime.now(timezone.utc).timestamp()))


def seconds_until_weekly_reset(week_start_day=6):  # noqa: E302
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
            return {"window": _empty_totals(), "week": _empty_totals(), "source": "local"}

        now_epoch  = datetime.now(timezone.utc).timestamp()
        window_h   = self.config.get("window_hours", 5)
        window_cut = now_epoch - window_h * 3600

        today = date.today()
        week_start_day = self.config.get("week_start_day", 6)
        days_since_start = (today.weekday() - week_start_day) % 7
        week_start_str = (today - timedelta(days=days_since_start)).isoformat()

        window_totals = _empty_totals()
        week_totals   = _empty_totals()
        week_sessions: set   = set()
        window_oldest: list  = [None]   # mutable box

        for jsonl_file in projects_dir.rglob("*.jsonl"):
            try:
                self._parse_jsonl(
                    jsonl_file, window_cut, week_start_str,
                    window_totals, week_totals, week_sessions, window_oldest,
                )
            except Exception:
                pass

        week_totals["session_count"] = len(week_sessions)
        return {
            "window": window_totals,
            "window_oldest_ts": window_oldest[0],
            "week": week_totals,
            "source": "local",
        }

    def _parse_jsonl(self, path, window_cut, week_start_str,
                     window_totals, week_totals, week_sessions, window_oldest):
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

                ts_str   = record.get("timestamp", "")
                date_str = ts_str[:10]
                msg_epoch = _parse_ts(ts_str)

                in_week   = date_str >= week_start_str
                in_window = msg_epoch is not None and msg_epoch >= window_cut

                if not in_week and not in_window:
                    continue

                model  = msg.get("model", "")
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
                    t["input_tokens"]          += inp
                    t["output_tokens"]         += out
                    t["cache_creation_tokens"] += cache_w
                    t["cache_read_tokens"]     += cache_r
                    t["total_cost"]            += cost
                    t["message_count"]         += 1
                    if model not in t["by_model"]:
                        t["by_model"][model] = {"input": 0, "output": 0, "cost": 0.0}
                    t["by_model"][model]["input"]  += inp
                    t["by_model"][model]["output"] += out
                    t["by_model"][model]["cost"]   += cost

                if in_week:
                    week_sessions.add(record.get("sessionId", str(path)))
                    _add(week_totals)

                if in_window:
                    _add(window_totals)
                    if window_oldest[0] is None or msg_epoch < window_oldest[0]:
                        window_oldest[0] = msg_epoch

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
