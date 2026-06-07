import json
import threading
from datetime import date, datetime
from pathlib import Path


def _match_pricing(pricing, model):
    for key, prices in pricing.items():
        if key != "default" and model.startswith(key):
            return prices
    return pricing["default"]


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
            return {}

        today = date.today().isoformat()
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "total_cost": 0.0,
            "message_count": 0,
            "by_model": {},
        }
        seen_sessions = set()

        for jsonl_file in projects_dir.rglob("*.jsonl"):
            try:
                self._parse_file(jsonl_file, today, totals, seen_sessions)
            except Exception:
                pass

        totals["session_count"] = len(seen_sessions)
        return totals

    def _parse_file(self, path, today_filter, totals, seen_sessions):
        pricing = self.config["pricing"]
        today_only = self.config.get("today_only", True)

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
                if today_only and not timestamp.startswith(today_filter):
                    continue

                seen_sessions.add(record.get("sessionId", str(path)))

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
