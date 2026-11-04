"""Lecture des sources et des listes de revues d'OpenAlex."""

from datetime import date

from domain.sources.openalex import OpenAlexSource, OpenAlexSourceList
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.ingestion.openalex import sources as mod

_NATURE = {
    "id": "https://openalex.org/S137773608",
    "issn": ["0028-0836", "1476-4687", "invalide"],
    "type": "journal",
    "listed_in": ["cwts-core", "doyens"],
    "works_count": 449150,
}


def test_lit_une_source(monkeypatch):
    calls = []

    def respond(*_a, **kwargs):
        calls.append(kwargs["params"])
        return {"results": [_NATURE]}

    monkeypatch.setattr(mod, "http_request_with_retry", respond)
    out = mod.fetch_sources("issn", ["0028-0836"], sources_api="x")
    assert out == [
        OpenAlexSource(
            "S137773608", ("0028-0836", "1476-4687"), "journal", ("cwts-core", "doyens"), 449150
        )
    ]
    assert calls[0]["filter"] == "issn:0028-0836"


def test_filtre_par_identifiant_en_forme_url(monkeypatch):
    calls = []

    def respond(*_a, **kwargs):
        calls.append(kwargs["params"])
        return {"results": []}

    monkeypatch.setattr(mod, "http_request_with_retry", respond)
    mod.fetch_sources("openalex", ["S1", "S2"], sources_api="x")
    assert calls[0]["filter"] == "openalex:https://openalex.org/S1|https://openalex.org/S2"


def test_un_echec_renvoie_none(monkeypatch):
    def boom(*_a, **_k):
        raise SourceUnavailableError("openalex")

    monkeypatch.setattr(mod, "http_request_with_retry", boom)
    assert mod.fetch_sources("issn", ["0028-0836"], sources_api="x") is None
    assert mod.fetch_source_lists(source_lists_api="x") is None


def test_lit_une_liste(monkeypatch):
    payload = {
        "results": [
            {
                "id": "https://openalex.org/source-lists/doyens",
                "maintainer": "Conférence des doyens de médecine",
                "url": "https://conferencedesdoyensdemedecine.org/",
                "list_version": "2026-10-01",
            },
            {"id": "https://openalex.org/source-lists/doaj", "list_version": None},
        ]
    }
    monkeypatch.setattr(mod, "http_request_with_retry", lambda *a, **k: payload)
    assert mod.fetch_source_lists(source_lists_api="x") == [
        OpenAlexSourceList(
            "doyens",
            "Conférence des doyens de médecine",
            "https://conferencedesdoyensdemedecine.org/",
            date(2026, 10, 1),
        ),
        OpenAlexSourceList("doaj", None, None, None),
    ]
