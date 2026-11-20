# 🤖 Discord bot for Crafty Controller

A Discord bot built with Python + [py-cord](https://github.com/Pycord-Development/pycord) that manages Minecraft servers through the **Crafty Controller API v2**.

## Commands

| Command | Description |
|---------|-------------|
| `/ip` | Show the server IP address and port. Set `SERVER_IP`/`SERVER_PORT` to hardcode the answer — no Crafty API call is made. Otherwise it reads the server data from Crafty. |
| `/map` | Send a link/button to the configured web map (BlueMap, dynmap, ...). |
| `/status` | Show server state, player count, CPU/RAM, world, version, uptime, and player list. |
| `/start` | Start the server (no-op if it is already running or starting). |
| `/stop` | Stop the server *(bonus)*. |
| `/restart` | Restart the server *(bonus)*. |

All commands target one fixed server configured by `DEFAULT_SERVER_ID`. There is no per-command server selector — simply run `/status`, `/start`, etc. Set `DEFAULT_SERVER_ID` to the server's ID or UUID in the `environment:` block of `compose.yaml` (or in `.env` for local runs). The bot refuses to start if this value is missing.

## Setup

### 1. Create the Discord bot
1. Go to <https://discord.com/developers/applications> → **New Application** → **Bot** tab → **Add Bot**.
2. Copy the **Token** into `DISCORD_TOKEN`.
3. **OAuth2 → URL Generator**: select scopes `bot` + `applications.commands`; minimum permissions: `Send Messages`, `Embed Links`. Open the generated URL to invite the bot.

### 2. Get a Crafty API token (recommended)
The bot uses a Crafty **API token (JWT)** directly — no username/password and no `/auth/login` call.

1. In the Crafty panel: **User Settings → API Keys** → create a key with access to the server and the **command** permission (needed by `/start`, `/stop`, `/restart`). `full_access` is the simplest option.
2. Get the token for that key. If the UI has no copy button, do this once via the API:

```bash
# (1) Log in to get a session token — ONLY used to create the API token
curl -k -X POST https://CRAFTY_IP:8443/api/v2/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"your_password"}'
# -> {"status":"ok","data":{"token":"<SESSION_TOKEN>","user_id":"1",...}}

# (2) List the user's keys (user_id comes from step 1):
curl -k -H 'Authorization: Bearer <SESSION_TOKEN>' \
  https://CRAFTY_IP:8443/api/v2/users/1/key

# (3) Replace key_id with one from the list and get the JWT:
curl -k -H 'Authorization: Bearer <SESSION_TOKEN>' \
  https://CRAFTY_IP:8443/api/v2/users/1/key/1
# -> {"status":"ok","data":"<THE_JWT>"}
```

3. Paste the JWT from `data` into `CRAFTY_API_TOKEN` — in `.env` for local runs, or in the `environment:` block of `compose.yaml` for Docker.

Note: the token has no fixed expiry, but becomes invalid when the key is deleted or you change your password / revoke sessions in Crafty (`valid_tokens_from`). The bot reports this clearly; just generate a new token.

**Fallback:** if you prefer not to use an API token, leave `CRAFTY_API_TOKEN` empty and set `CRAFTY_USERNAME` + `CRAFTY_PASSWORD` (+ `CRAFTY_TOTP` if MFA is enabled). The bot will then log in automatically and refresh the token when it expires.

### 3. Configure and run locally
Use `.env` for local runs only. For Docker, skip this and edit the `environment:` block in `compose.yaml` instead.

```bash
cd crafty-discord-bot
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your values

python bot.py
```

To register slash commands immediately, set `TEST_GUILD_ID` to a Discord server ID (right-click the server → Copy ID; requires Developer Mode). Without it, global registration can take up to an hour.

## Deploy with Docker Compose (recommended)

`compose.yaml` is a ready-to-edit example: all settings live in its `environment:` block, so **no external `.env` file is needed**. Replace the placeholder values (at minimum `DISCORD_TOKEN`, `CRAFTY_API_TOKEN`, `CRAFTY_BASE_URL`, `DEFAULT_SERVER_ID`, and `MAP_URL`) before deploying.

```bash
docker compose build      # builds the crafty-discord-bot:latest image
docker compose up -d
docker compose logs -f    # follow logs
docker compose restart
docker compose down
```
The image contains only `bot.py`, `crafty.py`, and dependencies, and runs as a non-root user. After changing code: `docker compose up -d --build`.

**Hostname note:** if Crafty runs on the same host as the bot, `127.0.0.1` inside the container points to the container itself. Set this in the `environment:` block:
```yaml
CRAFTY_BASE_URL: "http://host.docker.internal:8443"
```
`compose.yaml` already maps `host.docker.internal` to the host gateway. If Crafty runs on a different machine, use that machine's LAN/public IP. With Podman: `podman-compose build && podman-compose up -d`.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ | Discord bot token |
| `CRAFTY_BASE_URL` | ✅ | Crafty API URL, e.g. `https://127.0.0.1:8443` |
| `CRAFTY_API_TOKEN` | ✅* | JWT from a Crafty API key (recommended) |
| `CRAFTY_USERNAME` | ✅* | Username (only if not using an API token) |
| `CRAFTY_PASSWORD` | ✅* | Password (only if not using an API token) |
| `CRAFTY_TOTP` | ❌ | 2FA code (for the fallback login method) |
| `CRAFTY_VERIFY_SSL` | ❌ | `false` by default because Crafty uses a self-signed cert |
| `DEFAULT_SERVER_ID` | ✅ | ID/UUID of the single server all commands target |
| `SERVER_IP` | ❌ | Manual IP shown by `/ip`; skips the Crafty API |
| `SERVER_PORT` | ❌ | Manual port shown by `/ip` (optional) |
| `PUBLIC_IP` | ❌ | Fallback/public IP for `/ip` when `SERVER_IP` is unset |
| `MAP_URL` | ❌ | Web map link for `/map` |
| `TEST_GUILD_ID` | ❌ | Register commands instantly in one guild |

\* Provide at least one of: `CRAFTY_API_TOKEN` **or** the pair `CRAFTY_USERNAME` + `CRAFTY_PASSWORD`.

## Technical notes
- `CRAFTY_BASE_URL` must be a full URL including the scheme, e.g. `https://localhost:8443` (per the Crafty OpenAPI spec). A bare `127.0.0.1:8443` fails with `NonHttpUrlClientError`.
- Every request sends `Authorization: Bearer <token>`. With `CRAFTY_API_TOKEN`, the token is used from the start (no `/auth/login`); if Crafty returns 401 and credentials are available, the bot logs in once and retries.
- A Crafty API key is essentially a JWT signed with Crafty's secret, carrying a `token_id`, created via `GET /api/v2/users/{user_id}/key/{key_id}` (that endpoint requires session auth to create).
- Status comes from `GET /api/v2/servers/{id}/stats`; power actions use `POST /api/v2/servers/{id}/action/{action}`.
- No secrets are written to logs. Sensitive values live in `.env` (local runs) or in the `environment:` block of `compose.yaml` (Docker) — do not commit either file with real credentials.
