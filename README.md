# Crafty Discord Bot

Slash commands: `/ip`, `/map`, `/status`, `/start`, `/stop`, `/restart`.
Every command targets the single Crafty server set by `DEFAULT_SERVER_ID`.

## Deploy

```bash
git clone <repo-url>
cd crafty-discord-bot
# Edit compose.yaml: replace every placeholder
docker compose up -d --build
docker compose logs -f
```

Local run instead:
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env
python bot.py
```

## Config

All settings are in `compose.yaml` (`environment:`) or in `.env` for local runs.

| Variable | Required | Purpose |
|----------|----------|---------|
| `DISCORD_TOKEN` | ✅ | Discord bot token |
| `CRAFTY_BASE_URL` | ✅ | Full URL, e.g. `https://crafty.example.com:8443` |
| `CRAFTY_API_TOKEN` | ✅ | JWT from a Crafty API key |
| `DEFAULT_SERVER_ID` | ✅ | Crafty server UUID all commands target |
| `CRAFTY_USERNAME` / `CRAFTY_PASSWORD` / `CRAFTY_TOTP` | ❌ | Fallback login when no API token |
| `CRAFTY_VERIFY_SSL` | ❌ | `false` for self-signed certs |
| `SERVER_IP` / `SERVER_PORT` | ❌ | Manual answer for `/ip`; skips the Crafty API |
| `PUBLIC_IP` | ❌ | Fallback IP for `/ip` |
| `MAP_URL` | ❌ | Web map link for `/map` |
| `SERVER_VERSION` | ❌ | Version shown by `/status` |
| `STOP_RESTART_GUILD_ID` | ❌ | Discord guild allowed to use `/stop` and `/restart` |
| `STOP_RESTART_ROLE_ID` | ❌ | Role required for `/stop` and `/restart` |
| `TEST_GUILD_ID` | ❌ | Register commands instantly in one guild |

Notes:
- Create the API token in Crafty: **User Settings → API Keys**.
- `CRAFTY_BASE_URL` needs the scheme (`http://` or `https://`). If Crafty runs on the same host as the bot, use `http://host.docker.internal:<port>`.
- `/stop` and `/restart` work only with **both** the configured guild and role. Empty values disable them.
- `SERVER_VERSION` overrides Crafty's version field; RAM is displayed in MB.

## Security

Never commit real tokens. After editing `compose.yaml` locally:
```bash
git update-index --skip-worktree compose.yaml
```
