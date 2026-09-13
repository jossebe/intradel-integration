"""Fetch and parse the Intradel data page.

Vendored from pyintradel 0.0.7 rather than depended upon. That package pins
``beautifulsoup4>=4.15``, while Home Assistant ships 4.13 for its own
integrations; asking for the newer one left the container with a half-upgraded
BeautifulSoup (a 4.14+ ``filter.py`` next to a 4.13 ``_typing.py``) and the
integration failed to import at all. Vendoring the ~100 lines that matter drops
the version conflict entirely and uses whatever BeautifulSoup Home Assistant
already provides.

Only the cookie path is kept: the login form is gated behind a server-verified
invisible reCAPTCHA, so login/password/town can no longer authenticate and the
town table it needed is gone with it.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from bs4 import BeautifulSoup, Tag

_LOGGER = logging.getLogger(__name__)

DATA_URL = "https://www.intradel.be/particulier/data.php"

# The cookie that actually carries the session; the rest is analytics.
SESSION_COOKIE = "PHPSESSID"

# Raised with this wording when the site serves its login page instead of the
# data: the coordinator turns it into a re-authentication request.
AUTH_ERROR = "Wrong response received, login/password seems incorrect"


def normalize_cookie(cookie: str) -> str:
    """Accept the shapes a user may realistically paste.

    A cookie is a ``name=value`` pair, so pasting the session id on its own
    sends no cookie at all: the site then serves its login page, which the
    parser reports as wrong credentials -- a misleading error that is
    impossible to diagnose from the UI. Copying the whole request header,
    ``Cookie:`` prefix included, fails the same way.

    So: strip a leading header name, and name a bare id ``PHPSESSID``.
    """
    value = cookie.strip()
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()
    if "=" not in value:
        value = f"{SESSION_COOKIE}={value}"
    return value


async def get_data(session: aiohttp.ClientSession, cookie: str) -> list[dict[str, Any]]:
    """Fetch the waste collection data using a browser session cookie."""
    async with session.get(DATA_URL, headers={"Cookie": normalize_cookie(cookie)}) as resp:
        if resp.status != 200:
            raise ValueError(f"Received error {resp.status}", await resp.text())
        return parse(await resp.text())


def parse(response: str) -> list[dict[str, Any]]:
    """Parse the data page into one dict per bin and per recypark."""
    results: list[dict[str, Any]] = []
    soup = BeautifulSoup(response, features="html.parser")

    # The login form is only rendered when the session is not (or no longer)
    # authenticated, which is how an expired cookie shows up here.
    if soup.select_one('[name="pLogin"]') is not None:
        raise ValueError(AUTH_ERROR, response)

    for card in soup.select(".grid .row .post__content"):
        if card.find("h3") is None:
            continue
        name = _name(card)
        details = _details(card)
        results.append(
            {
                "name": name,
                "start_date": _start_date(card),
                "id": _chip_id(card) or name,
                "details": details,
                "total": _total(card) or str(len(details)),
            }
        )

    return results


def _require_tag(node: object) -> Tag:
    """Narrow a bs4 lookup result to a Tag, failing loudly on unexpected markup."""
    if not isinstance(node, Tag):
        raise ValueError("Unexpected response structure from intradel")
    return node


def _text(node: object) -> str:
    """The text of a bs4 node, failing loudly on unexpected markup."""
    # BeautifulSoup types .text as Any; every text access goes through here, so
    # this single cast keeps the rest of the module strictly typed.
    return str(_require_tag(node).text)


def _after_colon(text: str) -> str:
    """The part of a "Label : value" paragraph after the colon."""
    _, _, value = text.partition(":")
    return value.strip()


def _name(card: Tag) -> str:
    """The fraction name: ORGANIQUE, RESIDUEL or RECYPARC."""
    return _text(card.find("h3")).strip()


def _start_date(card: Tag) -> str:
    """The "Depuis:" date, which the site sets to 1 January of the current year.

    Bin cards carry four paragraphs (volume, chip, status, date) while the
    recypark card carries only the date.
    """
    info = card.find_all("p")
    return _after_colon(_text(info[3] if len(info) > 1 else info[0]))


def _chip_id(card: Tag) -> str | None:
    """The bin's chip number; the recypark card has none."""
    info = card.find_all("p")
    if len(info) > 1:
        return _after_colon(_text(info[1]))
    return None


def _details(card: Tag) -> list[dict[str, str]]:
    """One entry per table row: its date and its payload.

    The payload is a weight for a bin and a free-text list of dropped-off items
    for a recypark. Rows with fewer columns than expected are skipped rather
    than raising, because the markup changes without notice.
    """
    rows: list[dict[str, str]] = []
    for row in _require_tag(card.find("tbody")).find_all("tr"):
        cells = _require_tag(row).find_all("td")
        if len(cells) < 3:
            continue
        date = _text(cells[0])
        # The site renders an empty row when the list is empty; a valid row
        # always carries a date.
        if date:
            rows.append({"date": date, "detail": _text(cells[2])})
    return rows


def _total(card: Tag) -> str | None:
    """The table footer total: kilograms for a bin, absent for a recypark."""
    footer = card.find("tfoot")
    if not isinstance(footer, Tag):
        return None
    cells = footer.find_all("td")
    if len(cells) < 3:
        return None
    return _text(cells[2]).split(" ")[0].strip()
