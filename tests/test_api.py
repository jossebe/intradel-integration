"""Test the vendored Intradel scraper."""

import pytest

from custom_components.intradel.api import parse

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
