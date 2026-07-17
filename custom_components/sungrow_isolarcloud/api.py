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
POWER_STATION_LIST_PATH = "/openapi/getPowerStationList"
DEVICE_LIST_PATH = "/openapi/getDeviceList"
REALTIME_DATA_PATH = "/openapi/getDeviceRealTimeData"
OPEN_POINT_INFO_PATH = "/openapi/getOpenPointInfo"
PARAM_CHECK_PATH = "/openapi/paramSettingCheck"
PARAM_SETTING_PATH = "/openapi/paramSetting"
PARAM_TASK_PATH = "/openapi/getParamSettingTask"

# set_type values for paramSetting/paramSettingCheck.
SET_TYPE_WRITE = 0
SET_TYPE_READ = 2

# command_status of a parameter task.
TASK_STATUS_RUNNING = 2
TASK_STATUS_SUCCESS = 8

# result_code values that may mean the token is expired, warranting one
# re-login + retry. Verified live: an invalid token yields E900 "Unauthorized
# access" (E900 is also returned for endpoints the app has no permission
# for, so a retry can be futile — but it only costs one extra login).
# "009" is a missing-parameter error and "010" an invalid-parameter error;
# they must NOT trigger re-authentication.
TOKEN_ERROR_CODES = {"E900"}

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class SungrowApiError(Exception):
    """Raised when the iSolarCloud API returns an error."""


class SungrowAuthError(SungrowApiError):
    """Raised when authentication with iSolarCloud fails."""


class SungrowControlError(SungrowApiError):
    """Raised when a device parameter task is rejected, fails or times out."""


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

    async def async_get_power_station_list(self) -> list[dict[str, Any]]:
        """Return the plants (power stations) visible to this account."""
        result = await self._authenticated_post(
            POWER_STATION_LIST_PATH, {"curPage": 1, "size": 100}
        )
        plants = result.get("pageList") or result.get("page_list") or []
        if not isinstance(plants, list):
            raise SungrowApiError(f"Unexpected power station list payload: {result!r}")
        return plants

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

    async def async_get_open_point_info(
        self, device_type: int
    ) -> list[dict[str, Any]]:
        """Return metadata (name, units) for all measuring points of a type.

        Each row contains ``point_id``, ``point_name``, ``storage_unit`` (the
        unit of raw values) and ``show_unit``. Ratio points (SOC/SOH/PR) have
        an empty storage unit, a ``%`` show unit, and raw values in 0..1.
        """
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            result = await self._authenticated_post(
                OPEN_POINT_INFO_PATH,
                {
                    "device_type": str(device_type),
                    "type": "2",  # 2 = measuring points (1 = fault codes)
                    "curPage": page,
                    "size": 100,
                },
            )
            page_list = result.get("pageList") or []
            rows.extend(row for row in page_list if isinstance(row, dict))
            try:
                row_count = int(result.get("rowCount") or 0)
            except (TypeError, ValueError):
                row_count = 0
            if not page_list or len(rows) >= row_count:
                return rows
            page += 1

    async def async_param_setting_check(self, uuid: str, set_type: int) -> bool:
        """Return whether the device supports parameter read/write.

        set_type: SET_TYPE_READ (2) for read-back, SET_TYPE_WRITE (0) for
        updating parameters.
        """
        result = await self._authenticated_post(
            PARAM_CHECK_PATH, {"set_type": set_type, "uuid": str(uuid)}
        )
        if str(result.get("check_result")) != "1":
            return False
        devices = result.get("dev_result_list") or []
        return bool(devices) and str(devices[0].get("check_result")) == "1"

    async def _async_run_param_task(
        self,
        uuid: str,
        set_type: int,
        param_list: list[dict[str, str]],
        task_name: str,
    ) -> list[dict[str, Any]]:
        """Start a parameter task and poll it to completion.

        paramSetting queues a task that talks to the physical device; the
        result (including current values on read-back) arrives via
        getParamSettingTask once command_status reaches 8.
        """
        result = await self._authenticated_post(
            PARAM_SETTING_PATH,
            {
                "set_type": set_type,
                "uuid": str(uuid),
                "task_name": task_name,
                "expire_second": 120,
                "param_list": param_list,
            },
        )
        device_result = (result.get("dev_result_list") or [{}])[0]
        task_id = device_result.get("task_id")
        if (
            str(result.get("check_result")) != "1"
            or str(device_result.get("code")) != "1"
            or not task_id
        ):
            raise SungrowControlError(f"Parameter task rejected: {result!r}")
        await asyncio.sleep(2)
        for _ in range(20):
            task = await self._authenticated_post(
                PARAM_TASK_PATH, {"task_id": str(task_id), "uuid": str(uuid)}
            )
            try:
                status = int(task.get("command_status"))
            except (TypeError, ValueError):
                status = -1
            if status == TASK_STATUS_RUNNING:
                await asyncio.sleep(3)
                continue
            if status == TASK_STATUS_SUCCESS:
                return [
                    row
                    for row in task.get("param_list") or []
                    if isinstance(row, dict)
                ]
            raise SungrowControlError(
                f"Parameter task {task_id} failed (command_status={status}): "
                f"{task.get('task_name')}"
            )
        raise SungrowControlError(f"Parameter task {task_id} timed out")

    async def async_read_params(
        self, uuid: str, param_codes: list[str]
    ) -> list[dict[str, Any]]:
        """Read current parameter values from the device.

        The API rejects tasks with more than 10 parameters
        ("Parameter:param_list is over 10"), so larger reads are split into
        sequential tasks.
        """
        rows: list[dict[str, Any]] = []
        for start in range(0, len(param_codes), 10):
            chunk = param_codes[start : start + 10]
            rows.extend(
                await self._async_run_param_task(
                    uuid,
                    SET_TYPE_READ,
                    [{"param_code": code, "set_value": ""} for code in chunk],
                    "Home Assistant readback",
                )
            )
        return rows

    async def async_write_params(
        self, uuid: str, values: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Write parameter values to the device."""
        return await self._async_run_param_task(
            uuid,
            SET_TYPE_WRITE,
            [
                {"param_code": code, "set_value": str(value)}
                for code, value in values.items()
            ],
            "Home Assistant update",
        )
