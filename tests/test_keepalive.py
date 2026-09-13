"""Test the session keep-alive."""

from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp import ClientRequest
from yarl import URL

from custom_components.intradel.keepalive import (
    COOKIE_DOMAIN,
    DATA_URL,
    clear_site_cookies,
    ping_session,
)

COOKIE = "PHPSESSID=abc123"


def _session(status: int | None = None, error: Exception | None = None) -> MagicMock:
    """Build a fake aiohttp session whose HEAD returns a status (or raises)."""
    session = MagicMock()
    if error is not None:
        session.head = MagicMock(side_effect=error)
        return session

    response = MagicMock()
    response.status = status
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    session.head = MagicMock(return_value=context)
    return session


async def test_live_session() -> None:
    """A 200 means the session is still valid."""
    session = _session(status=200)

    assert await ping_session(session, COOKIE) is True
    session.head.assert_called_once_with(
        DATA_URL, headers={"Cookie": COOKIE}, allow_redirects=False
    )


async def test_expired_session() -> None:
    """The site redirects to the login page once the session is gone."""
    assert await ping_session(_session(status=302), COOKIE) is False


@pytest.mark.parametrize("status", [401, 403, 500])
async def test_any_non_200_is_treated_as_expired(status: int) -> None:
    """Anything but a 200 means the data page was not served."""
    assert await ping_session(_session(status=status), COOKIE) is False


async def test_network_error_does_not_invalidate_the_session() -> None:
    """A transient outage must not trigger a spurious re-authentication."""
    session = _session(error=aiohttp.ClientError("boom"))

    assert await ping_session(session, COOKIE) is True


async def test_redirects_are_not_followed() -> None:
    """Following the redirect would turn the expiry signal into a 200."""
    session = _session(status=200)
    await ping_session(session, COOKIE)

    assert session.head.call_args.kwargs["allow_redirects"] is False


def _jar_with_stale_session() -> aiohttp.CookieJar:
    """A real cookie jar holding a stale Intradel session."""
    jar = aiohttp.CookieJar()
    cookies = SimpleCookie()
    cookies["PHPSESSID"] = "STALE"
    cookies["PHPSESSID"]["domain"] = "www.intradel.be"
    cookies["PHPSESSID"]["path"] = "/"
    jar.update_cookies(cookies, URL("https://www.intradel.be/"))
    return jar


async def test_a_jar_cookie_would_override_the_header() -> None:
    """Document the aiohttp behaviour this guards against.

    A cookie in the jar replaces a Cookie header of the same name, so a stale
    session silently wins over the one the user just captured.
    """
    jar = _jar_with_stale_session()
    request = ClientRequest("GET", URL(DATA_URL), headers={"Cookie": "PHPSESSID=FRESH"})
    request.update_cookies(jar.filter_cookies(URL(DATA_URL)))

    assert "STALE" in request.headers["Cookie"]
    assert "FRESH" not in request.headers["Cookie"]


async def test_clear_site_cookies_lets_the_header_win() -> None:
    """After clearing, the freshly captured cookie is the one actually sent."""
    jar = _jar_with_stale_session()
    session = MagicMock()
    session.cookie_jar = jar

    clear_site_cookies(session)

    request = ClientRequest("GET", URL(DATA_URL), headers={"Cookie": "PHPSESSID=FRESH"})
    request.update_cookies(jar.filter_cookies(URL(DATA_URL)))
    assert request.headers["Cookie"] == "PHPSESSID=FRESH"


async def test_ping_clears_the_jar_before_asking() -> None:
    """The keep-alive must not ping with a stale session either."""
    session = _session(status=200)
    session.cookie_jar = MagicMock()

    await ping_session(session, COOKIE)

    session.cookie_jar.clear_domain.assert_called_once_with(COOKIE_DOMAIN)
