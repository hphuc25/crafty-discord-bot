"""Discord bot for managing Crafty Controller servers via API v2 (py-cord)."""

import asyncio
import json
import logging
import os
from datetime import datetime

import discord
from discord import Option
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
PUBLIC_IP = os.getenv("PUBLIC_IP", "").strip()
MAP_URL = os.getenv("MAP_URL", "").strip()
TEST_GUILD_ID = os.getenv("TEST_GUILD_ID", "").strip()

if not (DISCORD_TOKEN and CRAFTY_BASE_URL):
    raise SystemExit(
        "❌ Missing DISCORD_TOKEN or CRAFTY_BASE_URL. "
        "Copy .env.example to .env and fill in the configuration."
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
async def server_autocomplete(ctx: discord.AutocompleteContext) -> list[str]:
    try:
        servers = await crafty.get_servers()
    except Exception:
        return []
    typed = (ctx.value or "").lower()
    return [
        s.get("server_name", "")
        for s in servers
        if typed in s.get("server_name", "").lower()
    ][:25]


def server_option():
    """Shared option for commands that need to select a server."""
    return Option(
        str,
        "Server name or UUID (leave empty if Crafty has only one server or DEFAULT_SERVER_ID is set)",
        autocomplete=server_autocomplete,
        required=False,
    )


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


# --------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------- #
@bot.event
async def on_ready() -> None:
    log.info("Logged in to Discord as %s (ID: %s)", bot.user, bot.user.id)
    mode = "API token" if CRAFTY_API_TOKEN else "username/password"
    log.info("Crafty authentication: %s", mode)


# --------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------- #
@bot.slash_command(name="ip", description="Show the server IP address")
async def ip(
    ctx: discord.ApplicationContext,
    server: server_option() = None,  # type: ignore[valid-type]
):
    """Show the server IP address and port."""
    await ctx.defer()
    try:
        srv = await crafty.resolve_server(server)
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
async def map_cmd(
    ctx: discord.ApplicationContext,
    server: server_option() = None,  # type: ignore[valid-type]
):
    """Send a link to the configured web map (BlueMap/dynmap/...)."""
    if not MAP_URL:
        return await ctx.respond(
            "❌ `MAP_URL` is not configured in `.env`.", ephemeral=True
        )
    await ctx.defer()
    try:
        srv = await crafty.resolve_server(server)
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
async def status(
    ctx: discord.ApplicationContext,
    server: server_option() = None,  # type: ignore[valid-type]
):
    """Show status, players, CPU/RAM, world, etc."""
    await ctx.defer()
    try:
        srv = await crafty.resolve_server(server)
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
        embed.add_field(name="💾 RAM", value=f"{stats.get('mem', '?')} ({stats.get('mem_percent', '?')}%)", inline=True)

        world = stats.get("world_name") or "—"
        if stats.get("world_size"):
            world += f" ({stats['world_size']})"
        embed.add_field(name="🗺️ World", value=str(world), inline=True)
        embed.add_field(name="📦 Version", value=str(stats.get("version") or "—"), inline=True)
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


async def _power_action(ctx: discord.ApplicationContext, server, action: str, verb: str) -> None:
    await ctx.defer()
    try:
        srv = await crafty.resolve_server(server)
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
async def start(
    ctx: discord.ApplicationContext,
    server: server_option() = None,  # type: ignore[valid-type]
):
    await _power_action(ctx, server, "start_server", "start")


@bot.slash_command(name="stop", description="Stop the server (bonus)")
async def stop(
    ctx: discord.ApplicationContext,
    server: server_option() = None,  # type: ignore[valid-type]
):
    await _power_action(ctx, server, "stop_server", "stop")


@bot.slash_command(name="restart", description="Restart the server (bonus)")
async def restart(
    ctx: discord.ApplicationContext,
    server: server_option() = None,  # type: ignore[valid-type]
):
    await _power_action(ctx, server, "restart_server", "restart")


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
