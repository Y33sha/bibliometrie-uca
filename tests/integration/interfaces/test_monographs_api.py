"""Tests du router des monographies : liste (recherche, type, tri) et fiche."""

from functools import partial

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import (
    seed_monograph,
    seed_publication,
    seed_publisher,
    seed_serial,
    uniq,
)

# Publication sans titre normalisé.
_publication = partial(seed_publication, normalize_title=False)


def _seed_publications(monograph_id: int, n: int) -> None:
    for _ in range(n):
        _publication("P", monograph_id=monograph_id)


def _ids(client, **params) -> list[int]:
    r = client.get("/api/monographs", params={"per_page": 200, **params})
    assert r.status_code == 200
    return [m["id"] for m in r.json()["monographs"]]


class TestListMonographs:
    def test_search_by_title(self, client):
        title = uniq("Actes du colloque")
        mid = seed_monograph(title)
        assert _ids(client, search=title) == [mid]

    def test_search_by_isbn_prefix(self, client):
        mid = seed_monograph(uniq("Livre"), isbn="9782999000017")
        assert mid in _ids(client, search="978-2-999-000")

    def test_kind_filters_books_and_proceedings(self, client):
        title = uniq("Volume")
        book = seed_monograph(title)
        volume = seed_monograph(title, proceedings=True)
        assert _ids(client, search=title, type="book") == [book]
        assert _ids(client, search=title, type="proceedings") == [volume]
        assert sorted(_ids(client, search=title, type="book,proceedings")) == sorted([book, volume])

    def test_publisher_and_serial_filters(self, client):
        title = uniq("Rattachement")
        publisher = seed_publisher(title, name_normalized=title.lower())
        serial = seed_serial(title, title_normalized=title.lower())
        in_publisher = seed_monograph(title)
        in_serial = seed_monograph(title)
        seed_monograph(title)
        with owner_pool() as cur:
            cur.execute(
                "UPDATE monographs SET publisher_id = %s WHERE id = %s", (publisher, in_publisher)
            )
            cur.execute("UPDATE monographs SET serial_id = %s WHERE id = %s", (serial, in_serial))
        assert _ids(client, search=title, publisher_id=publisher) == [in_publisher]
        assert _ids(client, search=title, serial_id=serial) == [in_serial]

    def test_unknown_kind_rejected(self, client):
        assert client.get("/api/monographs", params={"type": "journal"}).status_code == 422

    def test_sorted_by_publications_and_counted(self, client):
        title = uniq("Recueil")
        few = seed_monograph(title)
        many = seed_monograph(title)
        _seed_publications(few, 1)
        _seed_publications(many, 3)
        r = client.get("/api/monographs", params={"search": title, "sort": "publications_desc"})
        assert [(m["id"], m["publication_count"]) for m in r.json()["monographs"]] == [
            (many, 3),
            (few, 1),
        ]


class TestMonographsFacets:
    def test_kind_counts_ignore_kind_filter(self, client):
        title = uniq("Facette")
        seed_monograph(title)
        seed_monograph(title)
        seed_monograph(title, proceedings=True)
        r = client.get("/api/monographs/facets", params={"search": title, "type": "book"})
        assert r.status_code == 200
        counts = {o["value"]: o["count"] for o in r.json()["kinds"]}
        assert counts == {"book": 2, "proceedings": 1}

    def test_annees_filtrees_et_comptees(self, client):
        title = uniq("Annee")
        m2019 = seed_monograph(title)
        m2020 = seed_monograph(title)
        with owner_pool() as cur:
            cur.execute("UPDATE monographs SET year = 2019 WHERE id = %s", (m2019,))
            cur.execute("UPDATE monographs SET year = 2020 WHERE id = %s", (m2020,))
        assert _ids(client, search=title, year="2019") == [m2019]
        r = client.get("/api/monographs/facets", params={"search": title, "year": "2019"})
        assert r.json()["years"] == [
            {"value": "2020", "label": None, "count": 1},
            {"value": "2019", "label": None, "count": 1},
        ]

    def test_facette_des_editeurs_et_des_collections(self, client):
        title = uniq("Entite")
        publisher = seed_publisher(title, name_normalized=title.lower())
        serial = seed_serial(title, title_normalized=title.lower())
        mid = seed_monograph(title)
        with owner_pool() as cur:
            cur.execute(
                "UPDATE monographs SET publisher_id = %s, serial_id = %s WHERE id = %s",
                (publisher, serial, mid),
            )
        for kind, entity in (("publisher", publisher), ("serial", serial)):
            r = client.get(
                "/api/monographs/facets/entities",
                params={"kind": kind, "entity_search": title, "search": title},
            )
            assert r.status_code == 200
            assert r.json()["entities"] == [{"id": entity, "label": title, "count": 1}]


class TestMonographPublications:
    def test_publications_filtered_by_monograph(self, client):
        mid = seed_monograph(uniq("Ouvrage"))
        other = seed_monograph(uniq("Autre"))
        chapter = _publication("Chapitre", monograph_id=mid, in_perimeter=True)
        _publication("Ailleurs", monograph_id=other, in_perimeter=True)
        r = client.get("/api/publications", params={"monograph_id": mid})
        assert r.status_code == 200
        assert [p["id"] for p in r.json()["publications"]] == [chapter]
        facets = client.get("/api/publications/facets", params={"monograph_id": mid})
        assert facets.status_code == 200


class TestGetMonograph:
    def test_detail_and_404(self, client):
        mid = seed_monograph(uniq("Fiche"))
        assert client.get(f"/api/monographs/{mid}").json()["id"] == mid
        assert client.get("/api/monographs/999999999").status_code == 404
