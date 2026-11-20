"""Async client for the Crafty Controller API v2."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class CraftyAPIError(Exception):
    """Error returned by the Crafty API."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class CraftyClient:
    def __init__(
        self,
        base_url: str,
        api_token: str = "",
        username: str = "",
        password: str = "",
        totp: str = "",
        verify_ssl: bool = False,
        default_server_id: str = "",
        timeout: int = 15,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token.strip()
        self.username = username
        self.password = password
        self.totp = totp
        self.verify_ssl = verify_ssl
        self.default_server_id = default_server_id
        self.timeout = timeout

        # API key token (JWT) from the Crafty panel: use it directly, no login needed.
        self._token: str | None = self.api_token or None
        self._session: aiohttp.ClientSession | None = None
        self._login_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Infrastructure
    # ------------------------------------------------------------------ #
    async def _get_session(self) -> aiohttp.ClientSession:
        # Create the session inside the running event loop to avoid warnings/wrong-loop calls.
        if self._session is None or self._session.closed:
            connector = None if self.verify_ssl else aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def login(self, force: bool = False) -> str:
        """Get a bearer token.

        A configured API token (JWT) takes priority and is used as-is, without calling
        /auth/login. Username/password login happens only when there is no API token
        (or when the old token was rejected and credentials are available as fallback).
        """
        async with self._login_lock:
            if self._token and not force:
                return self._token

            if not (self.username and self.password):
                raise CraftyAPIError(
                    "CRAFTY_API_TOKEN is invalid or has been revoked. "
                    "Generate/copy a new token in the Crafty panel and update .env."
                )

            payload: dict[str, Any] = {
                "username": self.username,
                "password": self.password,
            }
            if self.totp:
                payload["totp"] = self.totp

            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/v2/auth/login", json=payload
            ) as resp:
                data = await self._json(resp)
                if resp.status != 200 or data.get("status") != "ok":
                    error = data.get("error") or data.get("error_data") or "Invalid Crafty credentials"
                    raise CraftyAPIError(f"Crafty login failed: {error}", resp.status)
                token = (data.get("data") or {}).get("token")
                if not token:
                    raise CraftyAPIError("Crafty did not return a token", resp.status)
                self._token = token
                return token

    @staticmethod
    async def _json(resp: aiohttp.ClientResponse) -> dict[str, Any]:
        try:
            data = await resp.json(content_type=None)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    async def request(
        self,
        method: str,
        path: str,
        *,
        retry_auth: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call the API, re-authenticating once if the token expired (HTTP 401)."""
        token = await self.login()
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {token}"

        session = await self._get_session()
        async with session.request(
            method, f"{self.base_url}{path}", headers=headers, **kwargs
        ) as resp:
            if resp.status == 401 and retry_auth:
                await self.login(force=True)
                return await self.request(method, path, retry_auth=False, **kwargs)

            data = await self._json(resp)
            if resp.status >= 400 or data.get("status") == "error":
                error = (
                    data.get("error_data")
                    or data.get("error")
                    or f"Crafty returned HTTP {resp.status}"
                )
                raise CraftyAPIError(str(error), resp.status)
            return data

    # ------------------------------------------------------------------ #
    # Server operations
    # ------------------------------------------------------------------ #
    async def get_servers(self) -> list[dict[str, Any]]:
        data = await self.request("GET", "/api/v2/servers")
        return data.get("data") or []

    async def get_stats(self, server_id: str) -> dict[str, Any]:
        data = await self.request("GET", f"/api/v2/servers/{server_id}/stats")
        return data.get("data") or {}

    async def send_action(self, server_id: str, action: str) -> dict[str, Any]:
        valid = {
            "start_server",
            "stop_server",
            "restart_server",
            "kill_server",
            "backup_server",
            "update_executable",
        }
        if action not in valid:
            raise CraftyAPIError(f"Invalid action: {action}")
        return await self.request(
            "POST", f"/api/v2/servers/{server_id}/action/{action}"
        )

    async def resolve_server(self) -> dict[str, Any]:
        """Return the server configured by DEFAULT_SERVER_ID (or the only one available)."""
        servers = await self.get_servers()
        if not servers:
            raise CraftyAPIError("Crafty has no servers accessible to this account.")

        def matches(server: dict[str, Any], value: str) -> bool:
            value = value.lower()
            fields = (
                server.get("server_name", ""),
                server.get("server_id", ""),
                server.get("server_uuid", ""),
            )
            return any(value == str(f).lower() for f in fields) or any(
                value in str(f).lower() for f in fields
            )

        if self.default_server_id:
            for server in servers:
                if matches(server, self.default_server_id):
                    return server
            raise CraftyAPIError(
                "DEFAULT_SERVER_ID does not match any server on Crafty. "
                f"Available servers: {', '.join(s.get('server_name', '?') for s in servers)}"
            )

        if len(servers) == 1:
            return servers[0]

        names = ", ".join(s.get("server_name", "?") for s in servers)
        raise CraftyAPIError(
            f"DEFAULT_SERVER_ID is not set and multiple servers were found ({names})."
        )
