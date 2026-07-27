"""Coordinator for the update entity: periodically checks this repo's
GitHub Releases for a version newer than what's installed.

Not published to the default HACS store yet (see README Installation), so
HACS never creates its own update.* entity for it - confirmed absent on a
live instance (only update.hacs_update existed, no per-repository
entities for custom-repository installs). This coordinator/entity fills
that specific gap. Detection only, same as the rest of this project: it
never installs anything itself, just links to the release.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, GITHUB_REPO, UPDATE_CHECK_INTERVAL_HOURS

_LOGGER = logging.getLogger(__name__)

_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# GitHub's REST API serves plain JSON without an API version pinned via
# this header too, but pinning it is GitHub's own documented
# recommendation (avoids being silently opted into a future breaking
# default). No auth token: fine for one low-frequency request every
# UPDATE_CHECK_INTERVAL_HOURS from a single home instance, well under the
# unauthenticated 60 requests/hour rate limit.
_REQUEST_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# HA's frontend truncates/warns on an overly long update release_summary;
# 255 is the documented safe limit for UpdateEntity.release_summary.
_RELEASE_SUMMARY_MAX_LENGTH = 255


class LatestRelease(TypedDict):
    version: str
    release_url: str
    release_summary: str | None


class UpdateCheckCoordinator(DataUpdateCoordinator[LatestRelease | None]):
    """Holds the latest non-draft, non-prerelease GitHub release for this
    repo, or None if none could be determined (e.g. GitHub unreachable) -
    the update entity reports itself unavailable in that case rather than
    guessing, same defensive approach as the trace-reading coordinator's
    try/except (see coordinator.py)."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_update_check",
            update_interval=timedelta(hours=UPDATE_CHECK_INTERVAL_HOURS),
        )

    async def _async_update_data(self) -> LatestRelease | None:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(_RELEASES_URL, headers=_REQUEST_HEADERS) as resp:
                if resp.status != 200:
                    raise UpdateFailed(
                        f"GitHub API returned HTTP {resp.status} for {_RELEASES_URL}"
                    )
                payload: dict[str, Any] = await resp.json()
        except UpdateFailed:
            raise
        except Exception as err:  # noqa: BLE001 - any network/parse failure -> unavailable, not a crash
            raise UpdateFailed(f"Could not reach GitHub: {err}") from err

        # /releases/latest already excludes drafts and prereleases by
        # GitHub's own definition of "latest" - filtered again here
        # defensively in case that ever changes, rather than trusting the
        # endpoint name alone.
        if payload.get("draft") or payload.get("prerelease"):
            return None

        tag_name = payload.get("tag_name")
        if not isinstance(tag_name, str) or not tag_name:
            return None
        version = tag_name.removeprefix("v")

        summary = payload.get("body")
        if isinstance(summary, str) and len(summary) > _RELEASE_SUMMARY_MAX_LENGTH:
            summary = summary[: _RELEASE_SUMMARY_MAX_LENGTH - 1] + "…"

        return LatestRelease(
            version=version,
            release_url=payload.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases",
            release_summary=summary if isinstance(summary, str) else None,
        )
