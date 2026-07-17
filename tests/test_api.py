"""Tests for the iSolarCloud API client."""

from __future__ import annotations

from typing import Any

import aiohttp
from aioresponses import aioresponses
import pytest
from yarl import URL

from custom_components.sungrow_isolarcloud.api import (
    DEVICE_LIST_PATH,
    LOGIN_PATH,
    REALTIME_DATA_PATH,
    SungrowApiClient,
    SungrowApiError,
    SungrowAuthError,
)

BASE_URL = "https://augateway.isolarcloud.com"
LOGIN_URL = f"{BASE_URL}{LOGIN_PATH}"
DEVICE_LIST_URL = f"{BASE_URL}{DEVICE_LIST_PATH}"
REALTIME_URL = f"{BASE_URL}{REALTIME_DATA_PATH}"


def _login_ok(token: str = "token-1") -> dict[str, Any]:
    return {
        "result_code": "1",
        "result_msg": "success",
        "result_data": {"login_state": "1", "token": token},
    }


def _client(session: aiohttp.ClientSession) -> SungrowApiClient:
    return SungrowApiClient(
        session, BASE_URL, "app-key", "secret-key", "user", "password"
    )


async def test_login_success() -> None:
    """A successful login stores the token for later requests."""
    with aioresponses() as mock:
        mock.post(LOGIN_URL, payload=_login_ok("tok-abc"))
        async with aiohttp.ClientSession() as session:
            client = _client(session)
            await client.async_login()
            assert client._token == "tok-abc"


async def test_login_wrong_password() -> None:
    """login_state != 1 raises an auth error."""
    with aioresponses() as mock:
        mock.post(
            LOGIN_URL,
            payload={
                "result_code": "1",
                "result_data": {"login_state": "0", "msg": "password error"},
            },
        )
        async with aiohttp.ClientSession() as session:
            client = _client(session)
            with pytest.raises(SungrowAuthError):
                await client.async_login()


async def test_login_bad_appkey() -> None:
    """A non-1 result_code on login raises an auth error."""
    with aioresponses() as mock:
        mock.post(
            LOGIN_URL,
            payload={"result_code": "010", "result_msg": "appkey is invalid"},
        )
        async with aiohttp.ClientSession() as session:
            client = _client(session)
            with pytest.raises(SungrowAuthError):
                await client.async_login()


async def test_login_no_token() -> None:
    """A login response without a token raises an auth error."""
    with aioresponses() as mock:
        mock.post(
            LOGIN_URL,
            payload={"result_code": "1", "result_data": {"login_state": "1"}},
        )
        async with aiohttp.ClientSession() as session:
            client = _client(session)
            with pytest.raises(SungrowAuthError):
                await client.async_login()


async def test_device_list_logs_in_first() -> None:
    """Calling a data endpoint without a token logs in automatically."""
    with aioresponses() as mock:
        mock.post(LOGIN_URL, payload=_login_ok())
        mock.post(
            DEVICE_LIST_URL,
            payload={
                "result_code": "1",
                "result_data": {
                    "pageList": [{"ps_key": "1_14_1_1", "device_type": 14}]
                },
            },
        )
        async with aiohttp.ClientSession() as session:
            client = _client(session)
            devices = await client.async_get_device_list("1")
            assert devices == [{"ps_key": "1_14_1_1", "device_type": 14}]


async def test_expired_token_triggers_relogin_and_retry() -> None:
    """A token error result code re-authenticates and retries once."""
    with aioresponses() as mock:
        mock.post(LOGIN_URL, payload=_login_ok("tok-old"))
        mock.post(
            DEVICE_LIST_URL,
            payload={"result_code": "E00003", "result_msg": "token is expired"},
        )
        mock.post(LOGIN_URL, payload=_login_ok("tok-new"))
        mock.post(
            DEVICE_LIST_URL,
            payload={"result_code": "1", "result_data": {"pageList": []}},
        )
        async with aiohttp.ClientSession() as session:
            client = _client(session)
            devices = await client.async_get_device_list("1")
            assert devices == []
            assert client._token == "tok-new"


async def test_persistent_api_error_raises() -> None:
    """A non-token API error is raised without endless retries."""
    with aioresponses() as mock:
        mock.post(LOGIN_URL, payload=_login_ok())
        mock.post(
            DEVICE_LIST_URL,
            payload={"result_code": "E00000", "result_msg": "system error"},
        )
        async with aiohttp.ClientSession() as session:
            client = _client(session)
            with pytest.raises(SungrowApiError):
                await client.async_get_device_list("1")


async def test_http_500_raises_api_error() -> None:
    """HTTP-level failures surface as SungrowApiError."""
    with aioresponses() as mock:
        mock.post(LOGIN_URL, status=500)
        async with aiohttp.ClientSession() as session:
            client = _client(session)
            with pytest.raises(SungrowApiError):
                await client.async_login()


async def test_http_401_raises_auth_error() -> None:
    """HTTP 401 surfaces as SungrowAuthError."""
    with aioresponses() as mock:
        mock.post(LOGIN_URL, status=401)
        async with aiohttp.ClientSession() as session:
            client = _client(session)
            with pytest.raises(SungrowAuthError):
                await client.async_login()


async def test_realtime_data_request_shape() -> None:
    """The realtime request contains the expected payload fields."""
    with aioresponses() as mock:
        mock.post(LOGIN_URL, payload=_login_ok())
        mock.post(
            REALTIME_URL,
            payload={"result_code": "1", "result_data": {"device_point_list": []}},
        )
        async with aiohttp.ClientSession() as session:
            client = _client(session)
            await client.async_get_realtime_data(14, ["1_14_1_1"], ["13141"])

        requests = mock.requests[("POST", URL(REALTIME_URL))]
        body = requests[0].kwargs["json"]
        assert body["device_type"] == 14
        assert body["ps_key_list"] == ["1_14_1_1"]
        assert body["point_id_list"] == ["13141"]
        assert body["is_get_point_dict"] == "1"
        assert body["appkey"] == "app-key"
        assert body["token"] == "token-1"
