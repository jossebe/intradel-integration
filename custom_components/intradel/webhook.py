"""Collect a fresh session cookie from the browser, through a webhook.

The site cannot be embedded and read from a Home Assistant page: it sends
``X-Frame-Options: SAMEORIGIN``, and the same-origin policy would forbid reading
another domain's cookies anyway. So the browser has to hand the cookie over
itself, which a one-click bookmarklet does.

A webhook is used rather than the REST API for two reasons. It needs no
long-lived access token, so no credential sits in a bookmark; and a POST of
plain text is a CORS "simple request", so the browser sends it without a
preflight and Home Assistant needs no `cors_allowed_origins` entry.

The webhook only accepts requests from the local network, and the only thing it
can do is replace the session cookie with one the site accepts.
"""

from __future__ import annotations

import logging

from aiohttp.web import Request, Response
from homeassistant.components import webhook
from homeassistant.core import HomeAssistant

from .api import normalize_cookie
from .const import CONF_COOKIE, CONF_WEBHOOK_ID, DOMAIN
from .coordinator import IntradelConfigEntry
from .keepalive import ping_session

_LOGGER = logging.getLogger(__name__)


def async_webhook_id(entry: IntradelConfigEntry) -> str:
    """The entry's webhook id, generating one the first time."""
    return str(entry.data.get(CONF_WEBHOOK_ID) or webhook.async_generate_id())


def async_setup_webhook(hass: HomeAssistant, entry: IntradelConfigEntry) -> None:
    """Register the cookie-collection webhook for this entry."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    async def _handle(hass: HomeAssistant, _id: str, request: Request) -> Response:
        """Store the cookie the browser just sent."""
        cookie = normalize_cookie(await request.text())
        if not cookie:
            return Response(status=400, text="empty cookie")

        coordinator = entry.runtime_data
        if not await ping_session(coordinator.session, cookie):
            # Storing a cookie the site already rejects would only turn into a
            # failed poll; tell the browser instead.
            _LOGGER.warning("Intradel rejected the cookie sent by the bookmarklet")
            return Response(status=400, text="cookie rejected by intradel")

        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_COOKIE: cookie})
        _LOGGER.info("Intradel session cookie updated from the browser")
        return Response(status=200, text="ok")

    webhook.async_register(
        hass,
        DOMAIN,
        "Intradel session cookie",
        webhook_id,
        _handle,
        local_only=True,
        allowed_methods=["POST"],
    )


def async_unload_webhook(hass: HomeAssistant, entry: IntradelConfigEntry) -> None:
    """Remove the webhook."""
    webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
