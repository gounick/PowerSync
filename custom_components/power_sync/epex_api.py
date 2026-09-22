"""EPEX Day-Ahead Price API client.

Fetches day-ahead electricity prices from the EPEX Predictor API and,
for France, directly from Energy-Charts.info. Supports European bidding zones
including Germany, Austria, Belgium, France, Netherlands, Denmark, and Sweden.

Data sourced from Energy-Charts.info, ENTSO-E (prices), and Open-Meteo (weather).
Free API on fair-use basis - no authentication required.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiohttp

from .const import EPEX_API_BASE_URL

_LOGGER = logging.getLogger(__name__)
ENERGY_CHARTS_API_URL = "https://api.energy-charts.info/price"


class EPEXAPIClient:
    """Client for the EPEX Day-Ahead Predictor API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the EPEX API client.

        Args:
            session: aiohttp client session for API requests
        """
        self._session = session

    async def get_prices(
        self,
        region: str = "DE",
        surcharge: float = 0.0,
        tax_percent: float = 0.0,
        hours: int = -1,
    ) -> list[dict]:
        """Fetch price predictions from the EPEX Predictor API.

        Args:
            region: Bidding zone code (DE, AT, BE, FR, NL, SE1-4, DK1-2)
            surcharge: Fixed surcharge in ct/kWh (network fees, levies)
            tax_percent: Tax percentage to add (e.g. 21 for 21% VAT)
            hours: Hours to predict (-1 = all available, typically ~48h)

        Returns:
            List of price entries with 'startsAt' (ISO timestamp) and 'total' (ct/kWh)
        """
        if region.upper() == "FR":
            return await self._get_energy_charts_prices(
                surcharge=surcharge,
                tax_percent=tax_percent,
                hours=hours,
            )

        params = {
            "region": region,
            "surcharge": surcharge,
            "taxPercent": tax_percent,
            "hours": hours,
            "unit": "CT_PER_KWH",
            # Belgian dynamic retail contracts use EPEX's native quarter-hour
            # products. Keep the established hourly aggregation for every
            # other bidding zone until its native-resolution scope is
            # explicitly supported.
            "hourly": "false" if region.upper() == "BE" else "true",
        }

        url = f"{EPEX_API_BASE_URL}/prices"

        try:
            async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    _LOGGER.error("EPEX API returned status %d for region %s", resp.status, region)
                    return []

                data = await resp.json()
                prices = data.get("prices", [])
                known_until = data.get("knownUntil")

                _LOGGER.debug(
                    "EPEX API returned %d price entries for %s (known until %s)",
                    len(prices), region, known_until,
                )
                return prices

        except aiohttp.ClientError as err:
            _LOGGER.error("EPEX API request failed for %s: %s", region, err)
            return []
        except Exception as err:
            _LOGGER.error("Unexpected error fetching EPEX prices for %s: %s", region, err)
            return []

    async def _get_energy_charts_prices(
        self,
        surcharge: float,
        tax_percent: float,
        hours: int,
    ) -> list[dict]:
        """Fetch French day-ahead prices from Energy-Charts.info."""
        today = datetime.now(timezone.utc).date()
        params = {
            "bzn": "FR",
            "start": today.isoformat(),
            "end": (today + timedelta(days=1)).isoformat(),
        }

        try:
            async with self._session.get(
                ENERGY_CHARTS_API_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.error(
                        "Energy-Charts API returned status %d for region FR",
                        resp.status,
                    )
                    return []
                data = await resp.json()
        except aiohttp.ClientError as err:
            _LOGGER.error("Energy-Charts API request failed for FR: %s", err)
            return []
        except Exception as err:
            _LOGGER.error("Unexpected error fetching EPEX prices for FR: %s", err)
            return []

        timestamps = data.get("unix_seconds", [])
        market_prices = data.get("price", [])
        entries = []
        for index, (timestamp, price_mwh) in enumerate(zip(timestamps, market_prices)):
            starts_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            if index + 1 < len(timestamps):
                ends_at = datetime.fromtimestamp(timestamps[index + 1], tz=timezone.utc)
            else:
                ends_at = starts_at + timedelta(minutes=15)
            wholesale_ct = float(price_mwh) / 10
            total_ct = (wholesale_ct + surcharge) * (1 + tax_percent / 100)
            entries.append(
                {
                    "startsAt": starts_at.isoformat(),
                    "endsAt": ends_at.isoformat(),
                    "total": round(total_ct, 6),
                }
            )

        if hours >= 0:
            entries = entries[: hours * 4]
        _LOGGER.debug("Energy-Charts API returned %d price entries for FR", len(entries))
        return entries

    async def validate_region(self, region: str) -> bool:
        """Validate that a region returns price data.

        Args:
            region: Bidding zone code to validate

        Returns:
            True if the region returns valid price data
        """
        prices = await self.get_prices(region=region, hours=1)
        return len(prices) > 0
