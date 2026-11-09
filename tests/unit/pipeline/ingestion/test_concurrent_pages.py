"""Pagination de plusieurs requêtes en parallèle : pages dans l'ordre de chaque requête, erreurs par requête, arrêt sur source indisponible."""

from __future__ import annotations

import pytest

from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.ingestion.common.concurrent_pages import paginate_concurrently
from pipeline.ingestion.common.pages import Page

# Pages de chaque requête : identifiants des documents, page après page.
_PAGES = {"a": [["a1", "a2"], ["a3"]], "b": [["b1"]], "c": [["c1", "c2"], ["c3", "c4"], []]}


def _fetch(item: str, token: str | None) -> Page:
    """Renvoie la page `token` (la première à `None`) de `item`, avec le jeton de la suivante."""
    pages = _PAGES[item]
    index = int(token or 0)
    following = str(index + 1) if index + 1 < len(pages) else None
    return Page([{"id": i} for i in pages[index]], following)


def test_suit_les_pages_de_chaque_requete_dans_l_ordre():
    received: dict[str, list] = {}
    ended: list[tuple[str, Exception | None]] = []

    paginate_concurrently(
        list(_PAGES),
        _fetch,
        max_concurrent=3,
        on_page=lambda item, page: received.setdefault(item, []).extend(
            r["id"] for r in page.records
        ),
        on_end=lambda item, error: ended.append((item, error)),
    )

    assert received == {"a": ["a1", "a2", "a3"], "b": ["b1"], "c": ["c1", "c2", "c3", "c4"]}
    assert sorted(ended) == [("a", None), ("b", None), ("c", None)]


def test_une_erreur_interrompt_seulement_sa_requete():
    def fetch(item: str, token: str | None) -> Page:
        if item == "b":
            raise ValueError("panne")
        return _fetch(item, token)

    ended: dict[str, Exception | None] = {}

    paginate_concurrently(
        list(_PAGES),
        fetch,
        max_concurrent=2,
        on_page=lambda item, page: None,
        on_end=lambda item, error: ended.__setitem__(item, error),
    )

    assert ended["a"] is None
    assert ended["c"] is None
    assert isinstance(ended["b"], ValueError)


def test_source_indisponible_arrete_tout_et_se_propage():
    def fetch(item: str, token: str | None) -> Page:
        raise SourceUnavailableError("x")

    with pytest.raises(SourceUnavailableError):
        paginate_concurrently(
            [str(i) for i in range(20)],
            fetch,
            max_concurrent=3,
            on_page=lambda item, page: None,
            on_end=lambda item, error: None,
        )


def test_une_erreur_d_ecriture_arrete_les_workers_et_se_propage():
    def on_page(item: str, page: Page) -> None:
        raise RuntimeError("écriture")

    with pytest.raises(RuntimeError, match="écriture"):
        paginate_concurrently(
            list(_PAGES) * 10,
            _fetch,
            max_concurrent=3,
            on_page=on_page,
            on_end=lambda item, error: None,
        )
