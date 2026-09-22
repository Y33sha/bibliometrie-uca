"""Tests du router monographs : liste (recherche, type, tri), fiche, édition."""

import uuid

from tests.integration.helpers.db import owner_pool


def _uniq(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def _seed_monograph(title: str, *, proceedings: bool = False, isbn: str | None = None) -> int:
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO monographs (title, title_normalized, proceedings, isbn)"
            " VALUES (%s, normalize_name_form(%s), %s, %s) RETURNING id",
            (title, title, proceedings, isbn),
        )
        return cur.fetchone()["id"]


def _seed_publications(monograph_id: int, n: int) -> None:
    with owner_pool() as cur:
        for _ in range(n):
            cur.execute(
                "INSERT INTO publications (title, pub_year, monograph_id) VALUES ('P', 2024, %s)",
                (monograph_id,),
            )


def _ids(client, **params) -> list[int]:
    r = client.get("/api/monographs", params={"per_page": 200, **params})
    assert r.status_code == 200
    return [m["id"] for m in r.json()["monographs"]]


class TestListMonographs:
    def test_search_by_title(self, client):
        title = _uniq("Actes du colloque")
        mid = _seed_monograph(title)
        assert _ids(client, search=title) == [mid]

    def test_search_by_isbn_prefix(self, client):
        mid = _seed_monograph(_uniq("Livre"), isbn="9782999000017")
        assert mid in _ids(client, search="978-2-999-000")

    def test_kind_filters_books_and_proceedings(self, client):
        title = _uniq("Volume")
        book = _seed_monograph(title)
        volume = _seed_monograph(title, proceedings=True)
        assert _ids(client, search=title, kind="book") == [book]
        assert _ids(client, search=title, kind="proceedings") == [volume]

    def test_sorted_by_publications_and_counted(self, client):
        title = _uniq("Recueil")
        few = _seed_monograph(title)
        many = _seed_monograph(title)
        _seed_publications(few, 1)
        _seed_publications(many, 3)
        r = client.get("/api/monographs", params={"search": title, "sort": "pubs_desc"})
        assert [(m["id"], m["pub_count"]) for m in r.json()["monographs"]] == [(many, 3), (few, 1)]


class TestGetMonograph:
    def test_detail_and_404(self, client):
        mid = _seed_monograph(_uniq("Fiche"))
        assert client.get(f"/api/monographs/{mid}").json()["id"] == mid
        assert client.get("/api/monographs/999999999").status_code == 404


class TestUpdateMonograph:
    def test_requires_auth(self, client):
        mid = _seed_monograph(_uniq("Protégée"))
        assert client.put(f"/api/monographs/{mid}", json={"year": 2020}).status_code == 401

    def test_updates_fields_and_normalized_title(self, auth_client):
        mid = _seed_monograph(_uniq("Ancien titre"))
        r = auth_client.put(
            f"/api/monographs/{mid}",
            json={"title": "  Nouveau Titre  ", "proceedings": True, "year": 2021},
        )
        assert r.status_code == 200, r.text
        with owner_pool() as cur:
            cur.execute(
                "SELECT title, title_normalized, proceedings, year FROM monographs WHERE id = %s",
                (mid,),
            )
            assert cur.fetchone() == {
                "title": "Nouveau Titre",
                "title_normalized": "nouveau titre",
                "proceedings": True,
                "year": 2021,
            }

    def test_rejects_empty_title_and_unknown_monograph(self, auth_client):
        mid = _seed_monograph(_uniq("Titre"))
        assert auth_client.put(f"/api/monographs/{mid}", json={"title": " "}).status_code == 422
        assert auth_client.put("/api/monographs/999999999", json={"year": 1}).status_code == 404
