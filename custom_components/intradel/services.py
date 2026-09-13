"""Services for the Intradel integration.

The login form is gated behind a server-verified invisible reCAPTCHA, so the
only usable credential is a session cookie obtained by logging in with a real
browser. Capturing it by hand through the browser's network inspector is the
documented way, and it is tedious.

`intradel.set_cookie` removes that tedium without touching the reCAPTCHA: the
user still authenticates on the website itself, in their own browser, and only
the resulting session is handed over. A one-click bookmarklet can call this
service, so refreshing the credential stops being a devtools exercise.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.components import persistent_notification, webhook
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.network import get_url

from .const import (
    ATTR_COOKIE,
    CONF_COOKIE,
    CONF_WEBHOOK_ID,
    DOMAIN,
    SERVICE_SET_COOKIE,
    SERVICE_SHOW_BOOKMARKLET,
)
from .coordinator import IntradelConfigEntry
from .keepalive import ping_session

_LOGGER = logging.getLogger(__name__)

SET_COOKIE_SCHEMA = vol.Schema({vol.Required(ATTR_COOKIE): cv.string})


def async_setup_services(hass: HomeAssistant, entry: IntradelConfigEntry) -> None:
    """Register the integration services.

    The integration allows a single config entry, so the service always targets
    that one entry and needs no target selector.
    """

    async def _async_set_cookie(call: ServiceCall) -> None:
        """Replace the stored session cookie with a freshly captured one."""
        cookie = call.data[ATTR_COOKIE].strip()
        if not cookie:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="empty_cookie")

        coordinator = entry.runtime_data
        if not await ping_session(coordinator.session, cookie):
            # Storing a cookie the site already rejects would only turn into a
            # failed poll and a re-authentication prompt; refuse it up front.
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_cookie"
            )

        # Full replace, not a merge: it drops any leftover login/password/town
        # from an entry that used to authenticate that way. Updating the entry
        # triggers the update listener, which reloads it.
        hass.config_entries.async_update_entry(entry, data={CONF_COOKIE: cookie})
        _LOGGER.info("Intradel session cookie updated")

    async def _async_show_bookmarklet(_call: ServiceCall) -> None:
        """Show a ready-to-use bookmarklet in a notification."""
        url = get_url(hass, prefer_external=False) + webhook.async_generate_path(
            entry.data[CONF_WEBHOOK_ID]
        )
        persistent_notification.async_create(
            hass,
            BOOKMARKLET_NOTIFICATION.format(bookmarklet=_bookmarklet(url)),
            title="Intradel: one-click cookie",
            notification_id=f"{DOMAIN}_bookmarklet",
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_COOKIE, _async_set_cookie, schema=SET_COOKIE_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_SHOW_BOOKMARKLET, _async_show_bookmarklet)


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the integration services."""
    hass.services.async_remove(DOMAIN, SERVICE_SET_COOKIE)
    hass.services.async_remove(DOMAIN, SERVICE_SHOW_BOOKMARKLET)


def _bookmarklet(url: str) -> str:
    """Build the bookmarklet that posts the browser's cookie to the webhook.

    A POST of plain text is a CORS "simple request": the browser sends it
    without a preflight, so no `cors_allowed_origins` entry is needed, and
    `no-cors` keeps the browser from complaining about the opaque response.
    """
    return (
        "javascript:(async()=>{const c=document.cookie;"
        "if(!c.includes('PHPSESSID')){"
        "alert('Not logged in to Intradel. Log in first, then click again.');return;}"
        f"try{{await fetch('{url}',{{method:'POST',mode:'no-cors',"
        "headers:{'Content-Type':'text/plain'},body:c});"
        "alert('Cookie sent to Home Assistant.');}"
        "catch(e){alert('Could not reach Home Assistant: '+e);}})();"
    )


BOOKMARKLET_NOTIFICATION = """\
Drag this into your bookmarks bar, or create a bookmark with this as its URL.

Then: log in at https://www.intradel.be/particulier/, check your data is shown, \
and click the bookmark. The cookie is validated against the site before being \
stored, so a stale one is refused rather than saved.

```
{bookmarklet}
```

The link only works from your local network, and the only thing it can do is \
replace the Intradel session cookie.
"""
