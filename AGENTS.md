# AGENTS.md

Small py-cord bot. No test/lint/CI config — verify manually as below.

## Entrypoints & wiring
- `bot.py` is the only entrypoint and holds all slash commands. It calls `load_dotenv()` and validates env **at import time**, raising `SystemExit` if `DISCORD_TOKEN`, `CRAFTY_BASE_URL`, `DEFAULT_SERVER_ID`, or an auth method is missing — any import-based check needs dummy values.
- `crafty.py` is the async Crafty API v2 client; `main()` in `bot.py` starts Discord and closes the client in `finally`.
- Auth: `CRAFTY_API_TOKEN` (JWT from a Crafty API key) is primary and uses no `/auth/login`. Username/password is fallback only; HTTP 401 triggers one forced re-login + retry. Don't reintroduce mandatory login.
- Commands are fixed to one server: `DEFAULT_SERVER_ID` is required and `crafty.resolve_server()` takes no query. Do not re-add a `server` slash-command option or autocomplete.
- `SERVER_IP` (or legacy `PUBLIC_IP`) makes `/ip` answer purely from env without any Crafty API call; `SERVER_PORT` is optional.
- `CRAFTY_BASE_URL` must include `http://` or `https://`; the Crafty OpenAPI spec defines it as a full base URL. A bare host:port raises `NonHttpUrlClientError`.

## py-cord quirks (hit during development)
- **Never add `from __future__ import annotations` to `bot.py`.** It stringifies `discord.Option` annotations, so py-cord silently registers options with no description and no autocomplete. It is fine in `crafty.py`.
- Keep the four command descriptions verbatim: `Show the server IP address`, `Show the server map`, `Start the server`, `Show the server status`. They come from the requested spec. Keep all comments, UI strings, and docs in English.
- Keep `aiohttp.ClientSession` creation inside `crafty._get_session()` (running loop), not in `__init__`.

## Verification
```bash
python3 -m py_compile bot.py crafty.py
DISCORD_TOKEN=dummy CRAFTY_BASE_URL=https://example.com CRAFTY_API_TOKEN=x DEFAULT_SERVER_ID=s1 \
  .venv/bin/python -c "import bot; print([(c.name, [o.name for o in c.options]) for c in bot.bot.pending_application_commands])"
```
Expect 6 commands (`ip`, `map`, `status`, `start`, `stop`, `restart`), each with no options. Use `.venv/bin/python` for imports — system Python lacks the deps.

## Container / deploy
- `compose.yaml` is a template with placeholders only: never put real hosts/UUIDs/tokens in it. Env vars are inline in `environment:`; no external `.env` is used by Docker. `.dockerignore` excludes `.env`/`.venv` and the Dockerfile copies only `bot.py`/`crafty.py` — update it when adding source modules.
- The `python:3.12-slim` base already provides `ca-certificates`. Don't re-add `apt-get update`/apt installs: that step stalls behind `deb.debian.org` on slow networks.
- `build` + `image: crafty-discord-bot:latest` means `docker compose up -d --build` rebuilds and restarts in one step.
- `extra_hosts` maps `host.docker.internal` to the host gateway: if Crafty runs on the same host, `CRAFTY_BASE_URL` must use that hostname, not `127.0.0.1` (which is the container itself).

## Runtime gotchas
- `CRAFTY_VERIFY_SSL` defaults to false (Crafty uses self-signed certs).
- `TEST_GUILD_ID` sets py-cord `debug_guilds` for instant command registration; without it, global registration may take ~1 hour.
- `/map` replies with an ephemeral error unless `MAP_URL` is set.
- Set `DEFAULT_SERVER_ID` or have a single Crafty server to skip the `server` option; otherwise autocomplete lists server names.
