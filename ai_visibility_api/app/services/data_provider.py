"""Real-world query metrics (search volume, competitive difficulty).

Design: a small `DataProvider` interface with two implementations.

- `DataForSEOProvider` calls DataForSEO's real Keywords Data API. This is the
  "real third-party data" path the assessment asks for.
- `HeuristicDataProvider` is a deterministic, hash-seeded estimator used only
  when no DataForSEO credentials are configured (e.g. no trial account yet).
  It is NOT random -- the same query text always yields the same numbers --
  and it is loudly logged/labelled everywhere it surfaces (`data_source`
  field on every DiscoveredQuery) so nothing pretends to be real data it
  isn't. See README "Tradeoffs" for why this exists instead of a hard
  dependency on a third-party trial signup.

Swapping in real credentials later is a config-only change: set
DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD and `get_data_provider()` picks up
the real provider automatically, with the heuristic kept as an automatic
per-call fallback if the live API errors (rate limit, network, etc.) so a
DataForSEO outage degrades scoring quality rather than crashing the pipeline.
"""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

_COMMERCIAL_MARKERS = ("best", "vs", "top", "compare", "review", "alternative")

# DataForSEO's Keywords Data endpoints are location/language scoped. 2840 is
# the standard "United States" location code used across their v3 API.
_DATAFORSEO_LOCATION_CODE = 2840
_DATAFORSEO_LANGUAGE_CODE = "en"


@dataclass
class QueryMetrics:
    estimated_search_volume: int
    competitive_difficulty: int  # 0-100, higher = harder to rank/appear
    source: str  # "dataforseo" | "heuristic"


class DataProvider(ABC):
    @abstractmethod
    def get_query_metrics(self, query_text: str) -> QueryMetrics:
        raise NotImplementedError


class HeuristicDataProvider(DataProvider):
    """Deterministic stand-in for real search data.

    Seeds a couple of pseudo-random values off a SHA-256 hash of the
    normalised query text so results are stable across repeated calls
    (important for `/recheck` semantics: volume/difficulty shouldn't jitter
    on every re-run), then shapes them with a couple of realistic priors:
    shorter/broader queries skew higher-volume than long-tail phrasing, and
    commercial markers ("best", "vs", "compare") skew both volume and
    difficulty upward since those SERPs are typically more contested.
    """

    def get_query_metrics(self, query_text: str) -> QueryMetrics:
        normalized = query_text.strip().lower()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        volume_seed = int(digest[:8], 16)
        difficulty_seed = int(digest[8:16], 16)

        word_count = max(len(normalized.split()), 1)
        base_volume = 50 + (volume_seed % 4500)
        length_factor = max(0.4, 1.6 - 0.08 * word_count)
        is_commercial = any(marker in normalized for marker in _COMMERCIAL_MARKERS)
        commercial_volume_boost = 1.4 if is_commercial else 1.0
        volume = int(base_volume * length_factor * commercial_volume_boost)

        difficulty = difficulty_seed % 100
        if is_commercial:
            difficulty = min(100, difficulty + 15)

        return QueryMetrics(
            estimated_search_volume=volume,
            competitive_difficulty=difficulty,
            source="heuristic",
        )


class DataForSEOProvider(DataProvider):
    """Real search volume + competition via DataForSEO's Keywords Data API."""

    BASE_URL = "https://api.dataforseo.com/v3"

    def __init__(self, login: str, password: str, fallback: DataProvider | None = None):
        self._auth = (login, password)
        self._fallback = fallback or HeuristicDataProvider()

    def get_query_metrics(self, query_text: str) -> QueryMetrics:
        try:
            return self._fetch_live(query_text)
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            logger.warning(
                "DataForSEO call failed for query %r (%s); falling back to heuristic "
                "estimate for this query only.",
                query_text,
                exc,
            )
            return self._fallback.get_query_metrics(query_text)

    def _fetch_live(self, query_text: str) -> QueryMetrics:
        payload = [
            {
                "keywords": [query_text[:80]],
                "location_code": _DATAFORSEO_LOCATION_CODE,
                "language_code": _DATAFORSEO_LANGUAGE_CODE,
            }
        ]
        response = requests.post(
            f"{self.BASE_URL}/keywords_data/google_ads/search_volume/live",
            auth=self._auth,
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        result = body["tasks"][0]["result"][0]

        volume = int(result.get("search_volume") or 0)
        # DataForSEO's Google Ads `competition_index` is already 0-100.
        competition_index = result.get("competition_index")
        difficulty = int(competition_index) if competition_index is not None else 50

        return QueryMetrics(
            estimated_search_volume=volume,
            competitive_difficulty=difficulty,
            source="dataforseo",
        )


def get_data_provider(config) -> DataProvider:
    """`config` is a Flask `app.config` object (dict-like) or plain dict."""
    login = config.get("DATAFORSEO_LOGIN")
    password = config.get("DATAFORSEO_PASSWORD")
    if login and password:
        logger.info("DataForSEO credentials found -- using real search-data provider.")
        return DataForSEOProvider(login, password)

    logger.warning(
        "DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD not set -- using HeuristicDataProvider. "
        "estimated_search_volume/competitive_difficulty are deterministic estimates, "
        "not real third-party data. Set both env vars to enable real DataForSEO data."
    )
    return HeuristicDataProvider()
