"""Test the vendored Intradel scraper."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.intradel.api import get_data, normalize_cookie, parse

# One bin card and one recypark card, with the column layout the site really
# uses: Date | Vidanges | Kilos for a bin, Date | Parc | Matiere for a recypark.
PAGE = """
<div class="grid"><div class="row">
  <div class="post__content">
    <h3>ORGANIQUE</h3>
    <p>Volume : 40 L</p><p>Nr. Puce : 4000877051</p>
    <p>Statut : ACTIVE</p><p>Depuis : 01-01-2026</p>
    <table>
      <thead><tr><th>Date</th><th>Vidanges</th><th>Kilos</th></tr></thead>
      <tbody>
        <tr><td>11-02-2026</td><td>1</td><td>11.5</td></tr>
        <tr><td>25-03-2026</td><td>1</td><td>10.5</td></tr>
        <tr><td></td><td></td><td></td></tr>
      </tbody>
      <tfoot><tr><td>TOTAL</td><td>2</td><td>22.0 Kg</td></tr></tfoot>
    </table>
  </div>
  <div class="post__content">
    <h3>RECYPARC</h3>
    <p>Depuis : 01-01-2026</p>
    <table>
      <thead><tr><th>Date</th><th>Parc</th><th>Matiere</th></tr></thead>
      <tbody><tr><td>21-03-2026</td><td>WASSEIGES</td><td>Dechets verts (0.55 m3)</td></tr></tbody>
    </table>
  </div>
  <div class="post__content"><p>Note de bas de page, sans h3 ni tableau.</p></div>
</div></div>
"""

LOGIN_PAGE = '<html><form><input name="pLogin" type="hidden"></form></html>'


def test_parse_bin_card() -> None:
    """A bin card yields its name, chip, start date, rows and total."""
    cards = parse(PAGE)

    assert len(cards) == 2
    organic = cards[0]
    assert organic["name"] == "ORGANIQUE"
    assert organic["id"] == "4000877051"
    assert organic["start_date"] == "01-01-2026"
    assert organic["total"] == "22.0"
    # The trailing empty row the site always renders is skipped.
    assert organic["details"] == [
        {"date": "11-02-2026", "detail": "11.5"},
        {"date": "25-03-2026", "detail": "10.5"},
    ]


def test_parse_recyparc_card() -> None:
    """A recypark card has no chip and no footer, so it counts its visits."""
    recyparc = parse(PAGE)[1]

    assert recyparc["name"] == "RECYPARC"
    # No chip number: the name is used as the identifier.
    assert recyparc["id"] == "RECYPARC"
    assert recyparc["total"] == "1"
    assert recyparc["details"] == [{"date": "21-03-2026", "detail": "Dechets verts (0.55 m3)"}]


def test_cards_without_a_heading_are_ignored() -> None:
    """The page's footnotes share the card class but carry no data."""
    assert all(card["name"] for card in parse(PAGE))


def test_login_page_is_reported_as_an_auth_error() -> None:
    """An expired cookie makes the site serve its login form instead."""
    with pytest.raises(ValueError, match="login/password"):
        parse(LOGIN_PAGE)


def test_empty_page() -> None:
    """A page with no card at all parses to an empty list."""
    assert parse("<html><body></body></html>") == []


@pytest.mark.parametrize(
    ("pasted", "expected"),
    [
        # The bare session id: a cookie needs a name, so this sends nothing and
        # the site answers with its login page.
        ("k5mmgp8filf8bq0th1pmkuiir3", "PHPSESSID=k5mmgp8filf8bq0th1pmkuiir3"),
        # Already correct.
        ("PHPSESSID=abc123", "PHPSESSID=abc123"),
        # The whole request header, copied with its name.
        ("Cookie: PHPSESSID=abc123", "PHPSESSID=abc123"),
        ("cookie:PHPSESSID=abc123", "PHPSESSID=abc123"),
        # The header name plus a bare id.
        ("Cookie: abc123", "PHPSESSID=abc123"),
        # Several cookies, as the browser sends them.
        (
            "_ga=GA1.2.17; PHPSESSID=abc123; _gid=GA1.2.21",
            "_ga=GA1.2.17; PHPSESSID=abc123; _gid=GA1.2.21",
        ),
        # Stray whitespace from the copy.
        ("  PHPSESSID=abc123  ", "PHPSESSID=abc123"),
        ("  abc123\n", "PHPSESSID=abc123"),
    ],
)
def test_normalize_cookie(pasted: str, expected: str) -> None:
    """Whatever the user pastes ends up as a usable Cookie header."""
    assert normalize_cookie(pasted) == expected


async def test_get_data_sends_a_named_cookie() -> None:
    """A bare session id is named before it reaches the site."""
    session = MagicMock()
    response = MagicMock()
    response.status = 200
    response.text = AsyncMock(return_value=PAGE)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=context)

    await get_data(session, "k5mmgp8filf8bq0th1pmkuiir3")

    assert session.get.call_args.kwargs["headers"] == {
        "Cookie": "PHPSESSID=k5mmgp8filf8bq0th1pmkuiir3"
    }


def test_normalize_cookie_keeps_the_whole_browser_header() -> None:
    """The analytics cookies are harmless and are passed through untouched."""
    header = "_ga_X=GS2.1; _ga=GA1.2.17; PHPSESSID=k5mm; _gid=GA1.2.21"

    assert normalize_cookie(header) == header
    assert "PHPSESSID=k5mm" in normalize_cookie(header)
