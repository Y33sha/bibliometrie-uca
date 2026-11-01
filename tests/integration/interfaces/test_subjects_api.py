"""Tests d'intégration du router des sujets (`interfaces.api.routers.subjects`).

Couvre :
- GET /api/subjects (liste, pagination, recherche, tri, regroupement par libellé normalisé)
- GET /api/subjects/{libellé normalisé} (fiche, sujets de vocabulaire, voisins et liens entre voisins, 404)
"""

from __future__ import annotations

from domain.normalize import normalize_text
from domain.subjects.subject import SubjectVocabulary
from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import (
    seed_publication,
    seed_publication_subject,
    seed_subject,
    seed_subject_usage,
    uniq,
)


def _key(subject_id: int) -> str:
    """Renvoie le libellé normalisé du sujet semé `subject_id`."""
    with owner_pool() as cur:
        cur.execute("SELECT label_normalized FROM subjects WHERE id = %s", (subject_id,))
        return cur.fetchone()["label_normalized"]


def _publications(*subject_ids: int, count: int = 1) -> None:
    """Sème `count` publications liées aux sujets, puis recalcule le nombre de publications des sujets et leurs vues."""
    for _ in range(count):
        publication_id = seed_publication("subject-seed", normalize_title=False, doc_type="article")
        for subject_id in subject_ids:
            seed_publication_subject(publication_id, subject_id=subject_id)
    seed_subject_usage()


def _items(client, **params) -> list[dict]:
    r = client.get("/api/subjects", params={"per_page": 200, **params})
    assert r.status_code == 200
    return r.json()["items"]


class TestListSubjects:
    def test_returns_paginated_shape(self, client):
        r = client.get("/api/subjects")
        assert r.status_code == 200
        body = r.json()
        assert {"items", "total", "page", "per_page"} <= set(body)

    def test_per_page_above_limit_rejected(self, client):
        # `per_page` au-delà de 200 : 422.
        r = client.get("/api/subjects", params={"per_page": 500})
        assert r.status_code == 422

    def test_page_below_one_rejected(self, client):
        r = client.get("/api/subjects", params={"page": 0})
        assert r.status_code == 422

    def test_unknown_sort_rejected(self, client):
        r = client.get("/api/subjects", params={"sort": "usage_desc"})
        assert r.status_code == 422

    def test_search_by_label(self, client):
        label = uniq("FindMeSubject")
        _publications(seed_subject(label))
        [item] = _items(client, search=label.lower())
        assert (item["label"], item["usage_count"]) == (label, 1)

    def test_subject_without_publication_excluded(self, client):
        label = uniq("UnusedSubject")
        seed_subject(label)
        seed_subject_usage()
        assert _items(client, search=label) == []

    def test_same_label_across_vocabularies_forms_one_subject(self, client):
        label = uniq("Chimie")
        hal = seed_subject(label, vocabulary=SubjectVocabulary.HAL_DOMAIN)
        rameau = seed_subject(label.lower(), vocabulary=SubjectVocabulary.RAMEAU)
        _publications(hal)
        _publications(hal, rameau)
        _publications(rameau)
        [item] = _items(client, search=label)
        assert item["label_normalized"] == normalize_text(label)
        assert item["vocabularies"] == ["hal_domain", "rameau"]
        # Union des publications : celle des deux sujets compte une fois.
        assert item["usage_count"] == 3

    def test_sort(self, client):
        token = uniq("SortSubject")
        alpha = seed_subject(f"{token} alpha")
        beta = seed_subject(f"{token} beta")
        _publications(alpha, count=2)
        _publications(beta)
        alpha_key, beta_key = normalize_text(f"{token} alpha"), normalize_text(f"{token} beta")
        for sort, expected in (
            ("label_asc", [alpha_key, beta_key]),
            ("label_desc", [beta_key, alpha_key]),
            ("publications_asc", [beta_key, alpha_key]),
            ("publications_desc", [alpha_key, beta_key]),
        ):
            keys = [item["label_normalized"] for item in _items(client, search=token, sort=sort)]
            assert keys == expected, sort


class TestVocabularyFilter:
    def _seed(self) -> tuple[str, str, str]:
        """Sème un sujet HAL et RAMEAU, et un sujet OpenAlex, de même préfixe. Renvoie le préfixe et les deux libellés normalisés."""
        token = uniq("VocabSubject")
        shared = seed_subject(f"{token} chimie", vocabulary=SubjectVocabulary.HAL_DOMAIN)
        shared_rameau = seed_subject(f"{token} chimie", vocabulary=SubjectVocabulary.RAMEAU)
        english = seed_subject(f"{token} chemistry")
        _publications(shared, shared_rameau, english)
        return token, normalize_text(f"{token} chimie"), normalize_text(f"{token} chemistry")

    def test_retains_subjects_of_one_of_the_vocabularies(self, client):
        token, shared, english = self._seed()
        keys = {i["label_normalized"] for i in _items(client, search=token, vocabulary="rameau")}
        assert keys == {shared}
        keys = {
            i["label_normalized"]
            for i in _items(client, search=token, vocabulary="rameau,openalex")
        }
        assert keys == {shared, english}

    def test_unknown_vocabulary_rejected(self, client):
        r = client.get("/api/subjects", params={"vocabulary": "mesh"})
        assert r.status_code == 422

    def test_facets_count_subjects_per_vocabulary_ignoring_their_own_filter(self, client):
        token, _, _ = self._seed()
        r = client.get("/api/subjects/facets", params={"search": token, "vocabulary": "rameau"})
        assert r.status_code == 200
        counts = {o["value"]: o["count"] for o in r.json()["vocabularies"]}
        assert counts == {"openalex": 1, "hal_domain": 1, "rameau": 1, "theses_discipline": 0}


class TestGetSubject:
    def test_404_when_unknown(self, client):
        r = client.get(f"/api/subjects/{uniq('unknown')}")
        assert r.status_code == 404

    def test_returns_vocabulary_subjects_with_ancestors_and_children(self, client):
        root_label, label, child_label = uniq("Racine"), uniq("Domaine"), uniq("Feuille")
        root = seed_subject(root_label, vocabulary=SubjectVocabulary.HAL_DOMAIN, code=uniq("r"))
        subject = seed_subject(
            label, vocabulary=SubjectVocabulary.HAL_DOMAIN, code=uniq("d"), level=2, parent_id=root
        )
        child = seed_subject(
            child_label,
            vocabulary=SubjectVocabulary.HAL_DOMAIN,
            code=uniq("f"),
            level=3,
            parent_id=subject,
        )
        rameau = seed_subject(label, vocabulary=SubjectVocabulary.RAMEAU, code=uniq("ppn"))
        _publications(root, subject, child, rameau)

        r = client.get(f"/api/subjects/{normalize_text(label)}")
        assert r.status_code == 200
        body = r.json()
        assert body["subject"]["label"] == label
        hal, ppn = body["vocabulary_subjects"]
        assert hal["vocabulary"] == "hal_domain"
        assert [a["label"] for a in hal["ancestors"]] == [root_label]
        assert [(c["label"], c["usage_count"]) for c in hal["children"]] == [(child_label, 1)]
        assert ppn["vocabulary"] == "rameau"
        assert (ppn["ancestors"], ppn["children"]) == ([], [])

    def test_returns_neighbors_and_links_between_neighbors(self, client):
        main, n1, n2 = (seed_subject(uniq(name)) for name in ("Main", "Neighbor1", "Neighbor2"))
        _publications(main, n1, n2, count=2)

        r = client.get(f"/api/subjects/{_key(main)}", params={"min_cooccurrence": 1})
        assert r.status_code == 200
        body = r.json()
        assert {n["label_normalized"] for n in body["neighbors"]} == {_key(n1), _key(n2)}
        a, b = sorted([_key(n1), _key(n2)])
        assert body["neighbor_links"] == [{"label_a": a, "label_b": b, "cooccurrence_count": 2}]

    def test_min_cooccurrence_filters(self, client):
        main, weak = seed_subject(uniq("MainFilter")), seed_subject(uniq("WeakNeighbor"))
        _publications(main, weak, count=2)

        r = client.get(f"/api/subjects/{_key(main)}", params={"min_cooccurrence": 5})
        assert r.status_code == 200
        # Deux co-occurrences, sous le seuil de cinq : voisin écarté.
        assert r.json()["neighbors"] == []

    def test_neighbors_limit_param_validation(self, client):
        # `neighbors_limit` au-delà de 100 : 422.
        r = client.get("/api/subjects/chimie", params={"neighbors_limit": 500})
        assert r.status_code == 422
