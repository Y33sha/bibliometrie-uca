"""Tests du mapper API DOAJ → format CSV.

Le format CSV stocké est le contrat avec les consommateurs aval
(front, audit Phase 7). Ces tests verrouillent les clés produites et
le traitement des cas dégénérés (sections absentes, listes vides).
"""

from __future__ import annotations

from infrastructure.sources.doaj import to_csv_shape

# Échantillon réel (PLOS ONE, simplifié) — sert de baseline complet.
_PLOS_LIKE = {
    "id": "2fdf1470373343b7bd4f825179c685f5",
    "bibjson": {
        "title": "PLoS ONE",
        "eissn": "1932-6203",
        "publisher": {"name": "Public Library of Science (PLoS)", "country": "US"},
        "language": ["EN"],
        "subject": [
            {"code": "R", "scheme": "LCC", "term": "Medicine"},
            {"code": "Q", "scheme": "LCC", "term": "Science"},
        ],
        "oa_start": 2006,
        "license": [{"type": "CC BY", "BY": True}],
        "apc": {
            "has_apc": True,
            "max": [{"price": 2477, "currency": "USD"}],
        },
        "ref": {"journal": "https://journals.plos.org/plosone/"},
    },
}


def test_maps_baseline_fields_to_csv_keys():
    out = to_csv_shape(_PLOS_LIKE)
    assert out["Journal title"] == "PLoS ONE"
    assert out["Publisher"] == "Public Library of Science (PLoS)"
    assert out["Country of publisher"] == "US"
    assert out["Journal license"] == "CC BY"
    assert out["Subjects"] == "Medicine|Science"
    assert out["Languages in which the journal accepts manuscripts"] == "EN"
    assert out["When did the journal start to publish all content using an open license?"] == "2006"
    assert out["Journal article processing charges (APCs)"] == "Yes"
    assert out["APC amount"] == "2477"
    assert out["APC currency"] == "USD"
    assert out["Journal URL"] == "https://journals.plos.org/plosone/"
    assert out["DOAJ id"] == "2fdf1470373343b7bd4f825179c685f5"


def test_omits_keys_when_source_fields_missing():
    """Le mapper doit filtrer les clés vides — un consommateur SQL
    `doaj_payload->>'X'` retourne alors NULL plutôt que ''."""
    out = to_csv_shape({"id": "abc", "bibjson": {"title": "Foo"}})
    assert out == {"Journal title": "Foo", "DOAJ id": "abc"}


def test_handles_apc_section_missing():
    doc = {"id": "x", "bibjson": {"title": "T"}}
    out = to_csv_shape(doc)
    assert "APC amount" not in out
    assert "Journal article processing charges (APCs)" not in out


def test_has_apc_false_serializes_to_no():
    doc = {"id": "x", "bibjson": {"title": "T", "apc": {"has_apc": False, "max": []}}}
    out = to_csv_shape(doc)
    assert out["Journal article processing charges (APCs)"] == "No"
    assert "APC amount" not in out


def test_joins_multiple_languages_and_subjects():
    doc = {
        "id": "x",
        "bibjson": {
            "title": "T",
            "language": ["EN", "FR", "ES"],
            "subject": [{"term": "A"}, {"term": "B"}],
        },
    }
    out = to_csv_shape(doc)
    assert out["Languages in which the journal accepts manuscripts"] == "EN|FR|ES"
    assert out["Subjects"] == "A|B"


def test_empty_or_malformed_subject_entries_are_skipped():
    doc = {
        "id": "x",
        "bibjson": {
            "title": "T",
            "subject": [{"term": "A"}, {"term": ""}, {"term": "B"}, "not a dict"],
        },
    }
    out = to_csv_shape(doc)
    assert out["Subjects"] == "A|B"


def test_takes_first_license_only():
    doc = {
        "id": "x",
        "bibjson": {
            "title": "T",
            "license": [{"type": "CC BY"}, {"type": "CC BY-NC"}],
        },
    }
    out = to_csv_shape(doc)
    assert out["Journal license"] == "CC BY"


def test_takes_first_apc_price_only():
    """DOAJ peut lister plusieurs devises ; le CSV n'en stocke qu'une."""
    doc = {
        "id": "x",
        "bibjson": {
            "title": "T",
            "apc": {
                "has_apc": True,
                "max": [
                    {"price": 1000, "currency": "EUR"},
                    {"price": 1200, "currency": "USD"},
                ],
            },
        },
    }
    out = to_csv_shape(doc)
    assert out["APC amount"] == "1000"
    assert out["APC currency"] == "EUR"


def test_robust_to_completely_empty_doc():
    assert to_csv_shape({}) == {}


def test_robust_to_bibjson_being_non_dict():
    """Tolérance d'un payload abîmé — pas de crash, dict vide retourné."""
    assert to_csv_shape({"id": "x", "bibjson": "garbage"}) == {"DOAJ id": "x"}
