"""Regression coverage for EPEX native Belgian quarter-hour requests."""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
EPEX_API_PATH = ROOT / "custom_components" / "power_sync" / "epex_api.py"


def _method_source(method_name: str) -> str:
    source = EPEX_API_PATH.read_text()
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "EPEXAPIClient":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == method_name:
                    segment = ast.get_source_segment(source, item)
                    assert segment is not None
                    return segment
    raise AssertionError(f"EPEXAPIClient.{method_name} not found")


class _Response:
    status = 200

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or {
            "prices": [{"startsAt": "2026-07-30T14:00:00+02:00", "total": 8.2}]
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self) -> dict[str, Any]:
        return self.payload


class _Session:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.payload = payload

    def get(self, url, *, params, timeout):
        self.calls.append((url, dict(params)))
        return _Response(self.payload)


def _request_params(region: str) -> dict[str, Any]:
    namespace: dict[str, Any] = {
        "aiohttp": SimpleNamespace(
            ClientTimeout=lambda **kwargs: kwargs,
            ClientError=Exception,
        ),
        "EPEX_API_BASE_URL": "https://example.test",
        "_LOGGER": SimpleNamespace(
            debug=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        ),
    }
    exec(_method_source("get_prices"), namespace)
    session = _Session()
    client = SimpleNamespace(_session=session)

    asyncio.run(namespace["get_prices"](client, region=region))

    return session.calls[0][1]


def test_belgium_requests_native_quarter_hour_prices():
    assert _request_params("BE")["hourly"] == "false"


def test_other_epex_regions_keep_hourly_aggregation():
    assert _request_params("DE")["hourly"] == "true"


def test_france_routes_to_energy_charts():
    namespace: dict[str, Any] = {}
    exec(_method_source("get_prices"), namespace)
    calls = []

    async def get_energy_charts_prices(**kwargs):
        calls.append(kwargs)
        return [{"total": 1.0}]

    client = SimpleNamespace(_get_energy_charts_prices=get_energy_charts_prices)

    prices = asyncio.run(namespace["get_prices"](client, region="FR", hours=2))

    assert prices == [{"total": 1.0}]
    assert calls == [{"surcharge": 0.0, "tax_percent": 0.0, "hours": 2}]


def test_france_uses_native_energy_charts_quarter_hours():
    namespace: dict[str, Any] = {
        "aiohttp": SimpleNamespace(
            ClientTimeout=lambda **kwargs: kwargs,
            ClientError=Exception,
        ),
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "ENERGY_CHARTS_API_URL": "https://energy-charts.example.test/price",
        "_LOGGER": SimpleNamespace(
            debug=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        ),
    }
    exec(_method_source("_get_energy_charts_prices"), namespace)
    session = _Session(
        {
            "unix_seconds": [0, 900],
            "price": [100.0, 80.0],
            "unit": "EUR / MWh",
        }
    )
    client = SimpleNamespace(_session=session)

    prices = asyncio.run(
        namespace["_get_energy_charts_prices"](
            client,
            surcharge=2.0,
            tax_percent=20.0,
            hours=-1,
        )
    )

    assert session.calls[0][0] == "https://energy-charts.example.test/price"
    assert session.calls[0][1]["bzn"] == "FR"
    assert prices == [
        {
            "startsAt": "1970-01-01T00:00:00+00:00",
            "endsAt": "1970-01-01T00:15:00+00:00",
            "total": 14.4,
        },
        {
            "startsAt": "1970-01-01T00:15:00+00:00",
            "endsAt": "1970-01-01T00:30:00+00:00",
            "total": 12.0,
        },
    ]
