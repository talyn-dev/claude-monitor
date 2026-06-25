# Claude Monitor

Always-on-top desktop overlay for Windows that shows your real Claude usage percentage — the same numbers on [claude.ai/settings/usage](https://claude.ai/settings/usage).

![Two bars: 5h window and weekly, filled to the actual usage %]

## What it shows

- **5h window bar** — current usage % with exact reset countdown
- **Weekly bar** — 7-day usage % with reset date
- **$ cost estimate** — computed from your local Claude Code session files
- Draggable, frameless, always on top. Right-click to quit.

## Requirements

- Windows 10/11
- Python 3.10+
- Chrome (for auto cookie read) **or** a manual session key

## Install

```
git clone https://github.com/talyn-dev/claude-monitor
cd claude-monitor
pip install -r requirements.txt
python main.py
```

## Getting your session key

The overlay reads your `sessionKey` cookie from Chrome automatically **when Chrome is closed**. If Chrome is open, add the key manually:

1. Open Chrome → go to [claude.ai](https://claude.ai)
2. Press `F12` → Application → Cookies → `https://claude.ai`
3. Find the cookie named `sessionKey`, copy its value
4. Create `config.json` in the project folder:

```json
{
  "claude_session": "sk-ant-sid02-..."
}
```

The session key expires when you log out of claude.ai. Repeat if the bars stop updating.

## config.json options

All settings are optional — the overlay works with no config file.

| Key | Default | Description |
|-----|---------|-------------|
| `claude_session` | `""` | Your sessionKey cookie (auto-read from Chrome if blank) |
| `refresh_interval` | `30` | Seconds between API fetches |
| `opacity` | `0.88` | Window opacity (0.0–1.0) |
| `window_limit_usd` | `0` | Dollar limit for 5h bar fallback (used only if session key unavailable) |
| `weekly_limit_usd` | `0` | Dollar limit for weekly bar fallback |
| `admin_api_key` | `""` | Anthropic Admin API key for org-level cost data |
| `label` | `""` | Short name shown in the tray tooltip / overlay title (handy when running more than one instance) |
| `skip_local_scan` | `false` | Skip the local JSONL cost scan — bars-only mode. Avoids a slow per-refresh scan of a large `~/.claude/projects` history; the `$` estimate is then omitted |

## Running multiple instances

The usage % is per **claude.ai account** (it comes from the sessionKey), so you can
watch more than one subscription at once by running one instance per account. Point
each at its own config with `--config`:

```
pythonw main.py --config config-work.json
pythonw main.py --config config-personal.json
```

Give each a different `claude_session` and a `label` so the two tray icons are easy
to tell apart. Pair with `skip_local_scan: true` if you only want the live % bars.

## Notes

- `config.json` is in `.gitignore` — your session key won't be committed
- The overlay only reads data; it never writes to claude.ai
- Works on Claude.ai Pro and Max plans
