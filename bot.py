"""Discord bot for managing a fixed Crafty Controller server via API v2 (py-cord)."""

import asyncio
import json
import logging
import os
from datetime import datetime

import discord
from dotenv import load_dotenv

from crafty import CraftyAPIError, CraftyClient

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("crafty-bot")

# --------------------------------------------------------------------- #
# Configuration from .env
# --------------------------------------------------------------------- #
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
CRAFTY_BASE_URL = os.getenv("CRAFTY_BASE_URL", "").strip()
CRAFTY_API_TOKEN = os.getenv("CRAFTY_API_TOKEN", "").strip()
CRAFTY_USERNAME = os.getenv("CRAFTY_USERNAME", "").strip()
CRAFTY_PASSWORD = os.getenv("CRAFTY_PASSWORD", "").strip()
CRAFTY_TOTP = os.getenv("CRAFTY_TOTP", "").strip()
CRAFTY_VERIFY_SSL = os.getenv("CRAFTY_VERIFY_SSL", "false").lower() in ("1", "true", "yes")
DEFAULT_SERVER_ID = os.getenv("DEFAULT_SERVER_ID", "").strip()
# Manual IP shown by /ip. Falls back to PUBLIC_IP for existing setups.
SERVER_IP = os.getenv("SERVER_IP", "").strip() or os.getenv("PUBLIC_IP", "").strip()
SERVER_PORT = os.getenv("SERVER_PORT", "").strip()
MAP_URL = os.getenv("MAP_URL", "").strip()
TEST_GUILD_ID = os.getenv("TEST_GUILD_ID", "").strip()
# Version shown by /status instead of the value reported by Crafty.
SERVER_VERSION = os.getenv("SERVER_VERSION", "").strip()

# /stop and /restart are restricted to these Discord guild(s) and role(s).
# Comma-separated IDs are supported.
def _parse_ids(raw: str) -> set[int]:
    return {int(part.strip()) for part in raw.split(",") if part.strip().isdigit()}


STOP_RESTART_GUILD_IDS = _parse_ids(os.getenv("STOP_RESTART_GUILD_ID", ""))
STOP_RESTART_ROLE_IDS = _parse_ids(os.getenv("STOP_RESTART_ROLE_ID", ""))

if not (DISCORD_TOKEN and CRAFTY_BASE_URL):
    raise SystemExit(
        "❌ Missing DISCORD_TOKEN or CRAFTY_BASE_URL. "
        "Copy .env.example to .env and fill in the configuration."
    )
if not DEFAULT_SERVER_ID:
    raise SystemExit(
        "❌ DEFAULT_SERVER_ID is required. Set it to the ID/UUID of the server "
        "all commands should target."
    )
if not CRAFTY_API_TOKEN and not (CRAFTY_USERNAME and CRAFTY_PASSWORD):
    raise SystemExit(
        "❌ CRAFTY_API_TOKEN (recommended) or CRAFTY_USERNAME + CRAFTY_PASSWORD "
        "is required if you want the bot to log in automatically."
    )

debug_guilds = [int(TEST_GUILD_ID)] if TEST_GUILD_ID.isdigit() else None
bot = discord.Bot(intents=discord.Intents.default(), debug_guilds=debug_guilds)
crafty = CraftyClient(
    base_url=CRAFTY_BASE_URL,
    api_token=CRAFTY_API_TOKEN,
    username=CRAFTY_USERNAME,
    password=CRAFTY_PASSWORD,
    totp=CRAFTY_TOTP,
    verify_ssl=CRAFTY_VERIFY_SSL,
    default_server_id=DEFAULT_SERVER_ID,
)

COLOR_OK = discord.Color.green()
COLOR_WARN = discord.Color.orange()
COLOR_ERR = discord.Color.red()
COLOR_INFO = discord.Color.blurple()


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
async def error_reply(ctx: discord.ApplicationContext, err: Exception) -> None:
    if isinstance(err, CraftyAPIError):
        message = str(err)
    else:
        log.exception("Unexpected error while handling command")
        message = "An unexpected error occurred. Check the bot logs for details."
    try:
        await ctx.respond(f"❌ {message}", ephemeral=True)
    except discord.HTTPException:
        pass


def server_name(server: dict) -> str:
    return server.get("server_name") or server.get("server_id") or "Server"


def parse_uptime(started: str | None) -> str:
    if not started:
        return "—"
    try:
        start = datetime.strptime(started, "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - start
        hours, rem = divmod(int(delta.total_seconds()), 3600)
        return f"{delta.days} days {hours % 24} hours {rem // 60} minutes"
    except (ValueError, TypeError):
        return str(started)


def parse_players(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(p) for p in raw]
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, list):
            return [str(p) for p in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def format_mem(raw: object) -> str:
    """Crafty may return bytes as a float; always display megabytes."""
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return "—"
    if text.lower().endswith(("mb", "gb", "kb", "b")):
        return text
    try:
        value = float(text)
    except ValueError:
        return text
    # Values >= 1 MiB are bytes from Crafty; smaller numbers are already in MB.
    if value >= 1024 * 1024:
        value /= 1024 * 1024
    return f"{value:.1f} MB"


def can_use_power_commands(ctx: discord.ApplicationContext) -> bool:
    if not STOP_RESTART_GUILD_IDS or not STOP_RESTART_ROLE_IDS:
        return False
    if ctx.guild is None or ctx.guild.id not in STOP_RESTART_GUILD_IDS:
        return False
    role_ids = {role.id for role in getattr(ctx.author, "roles", [])}
    return bool(role_ids & STOP_RESTART_ROLE_IDS)


# --------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------- #
@bot.event
async def on_ready() -> None:
    log.info("Logged in to Discord as %s (ID: %s)", bot.user, bot.user.id)
    mode = "API token" if CRAFTY_API_TOKEN else "username/password"
    log.info("Crafty authentication: %s", mode)
    log.info("Target server: %s", DEFAULT_SERVER_ID)
    log.info(
        "Stop/restart access - guilds: %s, roles: %s",
        sorted(STOP_RESTART_GUILD_IDS) or "none",
        sorted(STOP_RESTART_ROLE_IDS) or "none",
    )


# --------------------------------------------------------------------- #
# Commands (always target the server configured in DEFAULT_SERVER_ID)
# --------------------------------------------------------------------- #
@bot.slash_command(name="ip", description="Show the server IP address")
async def ip(ctx: discord.ApplicationContext):
    """Show the server IP address and port."""
    await ctx.defer()
    try:
        # Manual override: no Crafty API call at all.
        if SERVER_IP:
            embed = discord.Embed(title="🌐 Server address", color=COLOR_INFO)
            embed.add_field(name="IP", value=f"`{SERVER_IP}`", inline=True)
            if SERVER_PORT:
                embed.add_field(name="Port", value=f"`{SERVER_PORT}`", inline=True)
                embed.add_field(
                    name="Connection", value=f"`{SERVER_IP}:{SERVER_PORT}`", inline=False
                )
            embed.set_footer(text="Address from SERVER_IP / SERVER_PORT in .env")
            return await ctx.respond(embed=embed)

        srv = await crafty.resolve_server()
        stats = await crafty.get_stats(srv["server_id"])
        address = stats.get("server_port") or srv.get("server_port")
        ip_addr = srv.get("server_ip") or "Unknown"
        port = address or "?"

        # If Crafty reports a localhost/private IP, show PUBLIC_IP instead when configured.
        is_local = ip_addr in ("127.0.0.1", "0.0.0.0", "localhost", "::1") or ip_addr.startswith(
            ("192.168.", "10.", "172.")
        )
        shown_ip = PUBLIC_IP if (is_local and PUBLIC_IP) else ip_addr

        embed = discord.Embed(
            title=f"🌐 Server address — {server_name(srv)}",
            color=COLOR_INFO,
        )
        embed.add_field(name="IP", value=f"`{shown_ip}`", inline=True)
        embed.add_field(name="Port", value=f"`{port}`", inline=True)
        embed.add_field(name="Connection", value=f"`{shown_ip}:{port}`", inline=False)
        if is_local and PUBLIC_IP:
            embed.set_footer(text="Public address from the PUBLIC_IP variable in .env")
        else:
            embed.set_footer(text="Data from Crafty API v2")
        await ctx.respond(embed=embed)
    except Exception as err:
        await error_reply(ctx, err)


@bot.slash_command(name="map", description="Show the server map")
async def map_cmd(ctx: discord.ApplicationContext):
    """Send a link to the configured web map (BlueMap/dynmap/...)."""
    if not MAP_URL:
        return await ctx.respond(
            "❌ `MAP_URL` is not configured in `.env`.", ephemeral=True
        )
    await ctx.defer()
    try:
        srv = await crafty.resolve_server()
        embed = discord.Embed(
            title=f"🗺️ Map — {server_name(srv)}",
            description=f"[👉 Click here to open the map]({MAP_URL})",
            color=COLOR_INFO,
        )
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="Open map",
                url=MAP_URL,
                style=discord.ButtonStyle.link,
                emoji="🗺️",
            )
        )
        await ctx.respond(embed=embed, view=view)
    except Exception as err:
        await error_reply(ctx, err)


@bot.slash_command(name="status", description="Show the server status")
async def status(ctx: discord.ApplicationContext):
    """Show status, players, CPU/RAM, world, etc."""
    await ctx.defer()
    try:
        srv = await crafty.resolve_server()
        stats = await crafty.get_stats(srv["server_id"])

        running = bool(stats.get("running"))
        crashed = bool(stats.get("crashed"))
        waiting = bool(stats.get("waiting_start"))
        if crashed:
            state, color = "💥 Crashed", COLOR_ERR
        elif running:
            state, color = "🟢 Running", COLOR_OK
        elif waiting:
            state, color = "🟡 Starting", COLOR_WARN
        else:
            state, color = "🔴 Stopped", COLOR_ERR

        embed = discord.Embed(
            title=f"📊 Status — {server_name(srv)}",
            description=state,
            color=color,
        )
        embed.add_field(name="👥 Players", value=f"{stats.get('online', 0)}/{stats.get('max', 0)}", inline=True)
        embed.add_field(name="⚙️ CPU", value=f"{stats.get('cpu', '?')}%", inline=True)
        embed.add_field(name="💾 RAM", value=f"{format_mem(stats.get('mem'))} ({stats.get('mem_percent', '?')}%)", inline=True)

        world = stats.get("world_name") or "—"
        if stats.get("world_size"):
            world += f" ({stats['world_size']})"
        embed.add_field(name="🗺️ World", value=str(world), inline=True)
        embed.add_field(name="📦 Version", value=SERVER_VERSION or str(stats.get("version") or "—"), inline=True)
        embed.add_field(name="⏱️ Uptime", value=parse_uptime(stats.get("started")), inline=True)
        embed.add_field(name="🕐 Started at", value=str(stats.get("started") or "—"), inline=True)

        players = parse_players(stats.get("players"))
        if players:
            shown = ", ".join(players[:10])
            if len(players) > 10:
                shown += f" (+{len(players) - 10})"
            embed.add_field(name="Player list", value=shown[:1024], inline=False)

        embed.set_footer(text="Data from Crafty API v2")
        await ctx.respond(embed=embed)
    except Exception as err:
        await error_reply(ctx, err)


async def _power_action(ctx: discord.ApplicationContext, action: str, verb: str) -> None:
    await ctx.defer()
    try:
        if action in ("stop_server", "restart_server") and not can_use_power_commands(ctx):
            return await ctx.respond(
                "❌ You are not allowed to use `/stop` or `/restart`. "
                "The configured Discord guild and role are required.",
                ephemeral=True,
            )

        srv = await crafty.resolve_server()
        name = server_name(srv)
        if action == "start_server":
            stats = await crafty.get_stats(srv["server_id"])
            if stats.get("running"):
                return await ctx.respond(f"⚠️ **{name}** is already running.")
            if stats.get("waiting_start"):
                return await ctx.respond(f"⚠️ **{name}** is currently starting.")

        await crafty.send_action(srv["server_id"], action)
        await ctx.respond(
            f"✅ Sent the **{verb}** command to server **{name}**.\n"
            "Use `/status` to check the status."
        )
    except Exception as err:
        await error_reply(ctx, err)


@bot.slash_command(name="start", description="Start the server")
async def start(ctx: discord.ApplicationContext):
    await _power_action(ctx, "start_server", "start")


@bot.slash_command(name="stop", description="Stop the server (bonus)")
async def stop(ctx: discord.ApplicationContext):
    await _power_action(ctx, "stop_server", "stop")


@bot.slash_command(name="restart", description="Restart the server (bonus)")
async def restart(ctx: discord.ApplicationContext):
    await _power_action(ctx, "restart_server", "restart")


# --------------------------------------------------------------------- #
# Run the bot
# --------------------------------------------------------------------- #
async def main() -> None:
    try:
        await bot.start(DISCORD_TOKEN)
    finally:
        await crafty.close()


if __name__ == "__main__":
    asyncio.run(main())
