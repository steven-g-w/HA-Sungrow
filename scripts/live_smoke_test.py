"""Live smoke test against the real iSolarCloud API.

Reads credentials from the git-ignored .env file in the repo root (never
hardcode credentials here) and exercises the integration's own API client:
login, device list, and real-time data for every supported device type.

Usage:  .venv/Scripts/python.exe scripts/live_smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from custom_components.sungrow_isolarcloud.api import SungrowApiClient  # noqa: E402
from custom_components.sungrow_isolarcloud.points import (  # noqa: E402
    DEVICE_TYPE_POINTS,
)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def load_env() -> dict[str, str]:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        raise SystemExit(".env not found in repo root")
    env: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def mask(value: str | None) -> str:
    if not value:
        return "<empty>"
    return f"{value[:4]}…{value[-4:]} (len={len(value)})"


async def main() -> None:
    env = load_env()
    ps_id = env["PS_ID"]
    # ThreadedResolver avoids an aiodns/pycares version mismatch in the venv.
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        client = SungrowApiClient(
            session,
            env["BASE_URL"],
            env["APP_KEY"],
            env["SECRET_KEY"],
            env["USERNAME"],
            env["PASSWORD"],
        )

        print("== login ==")
        await client.async_login()
        print(f"token: {mask(client._token)}")

        print("\n== getDeviceList ==")
        devices = await client.async_get_device_list(ps_id)
        print(f"{len(devices)} device(s)")
        for dev in devices:
            print(
                "  ps_key={ps_key} type={device_type} name={device_name!r} "
                "sn={device_sn} model={device_model_code}".format(
                    ps_key=dev.get("ps_key"),
                    device_type=dev.get("device_type"),
                    device_name=dev.get("device_name"),
                    device_sn=dev.get("device_sn") or dev.get("sn"),
                    device_model_code=dev.get("device_model_code")
                    or dev.get("device_model"),
                )
            )
        print("\nfull keys of first device:", sorted(devices[0]) if devices else "-")

        by_type: dict[int, list[str]] = {}
        for dev in devices:
            if dev.get("ps_key") and dev.get("device_type") is not None:
                by_type.setdefault(int(dev["device_type"]), []).append(
                    str(dev["ps_key"])
                )
        # The plant pseudo-device is not in the device list.
        by_type.setdefault(11, []).insert(0, f"{ps_id}_11_0_0")

        for device_type, catalog in DEVICE_TYPE_POINTS.items():
            ps_keys = by_type.get(device_type)
            if not ps_keys:
                print(f"\n== no devices of type {device_type}, skipping ==")
                continue

            meta_rows = await client.async_get_open_point_info(device_type)
            meta = {str(r["point_id"]): r for r in meta_rows}
            print(
                f"\n== type={device_type} keys={ps_keys} "
                f"({len(meta)} metadata rows) =="
            )
            result = await client.async_get_realtime_data(
                device_type, ps_keys, list(catalog)
            )
            for item in result.get("device_point_list") or []:
                dp = item.get("device_point", item)
                print(f"  device_point ps_key={dp.get('ps_key')}")
                for key, raw in sorted(dp.items()):
                    if not (key.startswith("p") and key[1:].isdigit()):
                        continue
                    pid = key[1:]
                    m = meta.get(pid, {})
                    storage = (m.get("storage_unit") or "").strip()
                    show = (m.get("show_unit") or "").strip()
                    catalog_name = (
                        catalog[pid].name if pid in catalog else "<not in catalog>"
                    )
                    print(
                        f"    p{pid}: value={raw!r:>14}  "
                        f"api={m.get('point_name')!r} [{storage or show}]  "
                        f"catalog={catalog_name!r}"
                    )


if __name__ == "__main__":
    asyncio.run(main())
