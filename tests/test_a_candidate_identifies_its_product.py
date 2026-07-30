"""A candidate has to identify the product it describes — by id, and by name.

Two ways it did not, both invisible until the ask started carrying real
candidates (audit §8.1):

*No anchor on the branded row.* USDA's candidate has always carried its
`fdc_id` through to the resolution. Open Food Facts' carried nothing, because
the search envelope never asked for `code` — so the anchor was missing from
exactly the candidates most likely to be the answer. A packaged product is the
case where identity is a FACT rather than a judgement, and it was the one case
a stored resolution could not point at.

*The name dropped whenever a brand existed.* `ProductCandidate.describe()`
returned brand + line + variant and fell back to the canonical name only when
all three were empty, so "Royo Everything Bagel" under brand "Royo" described
itself as "Royo" — the maker, not the product. `FoodIdentity.describe()` has a
long docstring about this exact failure; the candidate type never got the rule.
"""
import pytest

from skills.nutrition import off


def _resp(products):
    class _Resp:
        status_code = 200

        def json(self):
            return {"products": products}
    return _Resp()


def _client(products):
    class _C:
        async def get(self, *a, **k):
            return _resp(products)
    return _C()


_BAR = {
    "code": "7340001234567",
    "product_name": "Salty Peanut Protein Bar",
    "brands": "Barebells",
    "nutriments": {"energy-kcal_100g": 364, "proteins_100g": 36,
                   "carbohydrates_100g": 27, "fat_100g": 15},
}


async def test_the_branded_search_carries_the_barcode(monkeypatch):
    """Through the real client, not by reading the fields constant."""
    monkeypatch.setattr(off, "_client", lambda: _client([_BAR]))
    hit = await off.search("barebells salty peanut")
    assert hit is not None
    assert hit["code"] == "7340001234567"


async def test_the_siblings_carry_theirs_too(monkeypatch):
    """The variant the user picks becomes the anchored resolution, so it needs
    the same id the primary hit has."""
    second = dict(_BAR, code="7340009999999",
                  product_name="Barebells Cookies and Cream Protein Bar")
    monkeypatch.setattr(off, "_client", lambda: _client([_BAR, second]))
    rows = await off.search_variants("barebells protein bar", limit=4)
    assert len(rows) >= 2
    assert all(r["code"] for r in rows)


async def test_the_anchor_reaches_the_candidate(monkeypatch):
    """The whole point of fetching it: a resolution that names a PRODUCT.

    Through `candidates_from_live`, which is the one adapter that knows the
    live sources' shapes — a second reader of the envelope here would be the
    drift this join exists to end.
    """
    from skills.nutrition.shadow import candidates_from_live

    monkeypatch.setattr(off, "_client", lambda: _client([_BAR]))
    hit = await off.search("barebells salty peanut")
    built = candidates_from_live("barebells salty peanut",
                                 {"is_packaged": True}, off=hit)
    branded = [c for c in built if c.source == "off"]
    assert branded, "the branded row did not become a candidate"
    assert branded[0].source_id == "7340001234567"
    # And onto the numbers themselves — provenance is per value, and a profile
    # whose source_id is blank cannot say which product it priced.
    assert branded[0].profile.values["calories"].source_id == "7340001234567"


def test_the_resolver_path_anchors_the_branded_row_as_well():
    """`candidates.off_candidate` is the write path's adapter. Two adapters
    over one envelope is how a field added in one place stays missing in the
    other, which is what happened to `source_id`."""
    from skills.nutrition.candidates import off_candidate

    c = off_candidate({"name": "Salty Peanut Protein Bar", "brand": "Barebells",
                       "code": "7340001234567", "_match": "exact",
                       "per100g": {"calories": 364, "protein": 36,
                                   "carbs": 27, "fat": 15}})
    assert c is not None and c.source_id == "7340001234567"


@pytest.mark.parametrize("kwargs,expected", [
    ({"canonical_name": "Royo Everything Bagel", "brand": "Royo"},
     "Royo Everything Bagel"),
    ({"canonical_name": "Bagel", "brand": "Royo", "variant": "Everything"},
     "Royo Everything Bagel"),
    ({"canonical_name": "Sopressata", "brand": "Seppe"}, "Seppe Sopressata"),
])
def test_a_candidate_never_describes_itself_as_its_brand(kwargs, expected):
    from skills.nutrition.candidate_sets import ProductCandidate

    assert ProductCandidate(candidate_id="c", **kwargs).describe() == expected
