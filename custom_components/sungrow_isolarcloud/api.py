"""Async client for the Sungrow iSolarCloud OpenAPI.

Implements the V1 (account login, non-OAuth) flavour of the API documented at
https://developer-api.isolarcloud.com/:

* ``POST /openapi/login`` — exchange username/password for a token.
* ``POST /openapi/getDeviceList`` — list devices of a plant (``ps_id``).
* ``POST /openapi/getDeviceRealTimeData`` — read measuring points by
  ``ps_key`` and ``point_id``.

Every request carries the application key in the JSON body (``appkey``) and
the secret key in the ``x-access-key`` header.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

LOGIN_PATH = "/openapi/login"
DEVICE_LIST_PATH = "/openapi/getDeviceList"
REALTIME_DATA_PATH = "/openapi/getDeviceRealTimeData"

# result_code values that mean the token is missing/expired and a re-login
# should be attempted.
TOKEN_ERROR_CODES = {"009", "010", "E00003", "1005"}

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class SungrowApiError(Exception):
    """Raised when the iSolarCloud API returns an error."""


class SungrowAuthError(SungrowApiError):
    """Raised when authentication with iSolarCloud fails."""


class SungrowApiClient:
    """Minimal async client for the iSolarCloud OpenAPI."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        app_key: str,
        secret_key: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._app_key = app_key
        self._secret_key = secret_key
        self._username = username
        self._password = password
        self._token: str | None = None
        self._login_lock = asyncio.Lock()

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "HomeAssistant",
            "x-access-key": self._secret_key,
            "sys_code": "901",
        }
        if self._token:
            headers["token"] = self._token
        return headers

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a JSON payload and return the decoded JSON response."""
        body = {"appkey": self._app_key, "lang": "_en_US", **payload}
        if self._token and "user_password" not in payload:
            body["token"] = self._token
        url = f"{self._base_url}{path}"
        try:
            async with self._session.post(
                url, json=body, headers=self._headers, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status == 401:
                    raise SungrowAuthError(f"HTTP 401 from {path}")
                response.raise_for_status()
                data = await response.json(content_type=None)
        except SungrowApiError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise SungrowApiError(f"Error communicating with iSolarCloud: {err}") from err
        if not isinstance(data, dict):
            raise SungrowApiError(f"Unexpected response from {path}: {data!r}")
        return data

    async def async_login(self) -> None:
        """Log in and store the API token."""
        async with self._login_lock:
            data = await self._post(
                LOGIN_PATH,
                {
                    "user_account": self._username,
                    "user_password": self._password,
                    "login_type": "1",
                },
            )
            result_code = str(data.get("result_code"))
            result_data = data.get("result_data") or {}
            if result_code != "1":
                raise SungrowAuthError(
                    f"Login failed (result_code={result_code}): {data.get('result_msg')}"
                )
            if str(result_data.get("login_state")) != "1":
                # login_state 0 = wrong password, 2 = locked, etc.
                raise SungrowAuthError(
                    f"Login rejected (login_state={result_data.get('login_state')}): "
                    f"{result_data.get('msg') or data.get('result_msg')}"
                )
            token = result_data.get("token")
            if not token:
                raise SungrowAuthError("Login succeeded but no token was returned")
            self._token = token
            _LOGGER.debug("Logged in to iSolarCloud, token acquired")

    async def _authenticated_post(
        self, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """POST with automatic login/re-login on token errors."""
        if self._token is None:
            await self.async_login()
        data = await self._post(path, payload)
        result_code = str(data.get("result_code"))
        result_msg = str(data.get("result_msg") or "")
        if result_code != "1" and (
            result_code in TOKEN_ERROR_CODES or "token" in result_msg.lower()
        ):
            _LOGGER.debug(
                "Token rejected (result_code=%s, msg=%s); re-authenticating",
                result_code,
                result_msg,
            )
            self._token = None
            await self.async_login()
            data = await self._post(path, payload)
            result_code = str(data.get("result_code"))
        if result_code != "1":
            raise SungrowApiError(
                f"iSolarCloud error on {path} (result_code={result_code}): "
                f"{data.get('result_msg')}"
            )
        return data.get("result_data") or {}

    async def async_get_device_list(self, ps_id: str) -> list[dict[str, Any]]:
        """Return the devices belonging to a plant."""
        result = await self._authenticated_post(
            DEVICE_LIST_PATH,
            {"ps_id": ps_id, "curPage": 1, "size": 100},
        )
        devices = result.get("pageList") or result.get("page_list") or []
        if not isinstance(devices, list):
            raise SungrowApiError(f"Unexpected device list payload: {result!r}")
        return devices

    async def async_get_realtime_data(
        self,
        device_type: int,
        ps_key_list: list[str],
        point_ids: list[str],
    ) -> dict[str, Any]:
        """Return real-time measuring point data for a set of devices.

        The response contains ``device_point_list`` (one ``device_point`` per
        ps_key, with values keyed ``p<point_id>``) and, when supported by the
        server, ``point_dict`` metadata (names/units) because we request
        ``is_get_point_dict``.
        """
        return await self._authenticated_post(
            REALTIME_DATA_PATH,
            {
                "device_type": device_type,
                "ps_key_list": ps_key_list,
                "point_id_list": point_ids,
                "is_get_point_dict": "1",
            },
        )
