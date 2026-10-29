"""Fusion manuelle de deux publications : GET /api/publications/{id}/merge-candidates, POST /api/publications/{id}/merge et /merge-preview, sous le rôle de l'API."""

from sqlalchemy import text

from tests.integration.helpers.alignment import (
    align_source_contributions,
    set_perimeter_author_contribution,
)
from tests.integration.helpers.db import owner_connection, owner_pool
from tests.integration.helpers.seeds import seed_person, seed_publication, seed_source_record, uniq
from tests.integration.helpers.sources import insert_source_contribution


def _authored_publication(*, doi: str | None, person_id: int | None) -> int:
    """Publication d'un enregistrement source et d'une contribution du périmètre « Martin, Anne », rattachée par le nom à `person_id` quand il est fourni."""
    publication = seed_publication(uniq("Titre"), doc_type="article")
    source = "crossref" if doi else "hal"
    source_record = seed_source_record(source, publication_id=publication, doi=doi)
    with owner_connection() as conn:
        if doi:
            conn.execute(
                text("UPDATE publications SET doi = :doi WHERE id = :id"),
                {"doi": doi, "id": publication},
            )
        source_contribution = insert_source_contribution(
            conn,
            source_record,
            source=source,
            raw_last_name="Martin",
            raw_first_name="Anne",
            author_name_normalized="martin anne",
            in_perimeter=True,
            roles=["author"],
        )
        contribution = align_source_contributions(
            conn, publication, [(source_contribution, source_record)]
        )
        set_perimeter_author_contribution(
            conn, contribution, person_id=person_id, mode="name" if person_id else None
        )
    return publication


def _exists(publication_id: int) -> bool:
    with owner_pool() as cur:
        cur.execute("SELECT 1 FROM publications WHERE id = %s", (publication_id,))
        return cur.fetchone() is not None


def _persons_of(publication_id: int) -> list[int | None]:
    with owner_pool() as cur:
        cur.execute(
            "SELECT person_id FROM contributions WHERE publication_id = %s", (publication_id,)
        )
        return [row["person_id"] for row in cur.fetchall()]


class TestMerge:
    def test_merges_into_the_doi_carrier_and_keeps_the_person(self, auth_client):
        person = seed_person(uniq("Martin"), "Anne")
        with_doi = _authored_publication(doi=f"10.64628/{uniq('x')}", person_id=None)
        without_doi = _authored_publication(doi=None, person_id=person)

        r = auth_client.post(f"/api/publications/{without_doi}/merge", json={"other_id": with_doi})

        assert r.status_code == 200, r.text
        assert r.json() == {"publication_id": with_doi, "conflicts": 0}
        assert not _exists(without_doi)
        assert _persons_of(with_doi) == [person]

    def test_distinct_dois_are_refused(self, auth_client):
        a = _authored_publication(doi=f"10.1/{uniq('a')}", person_id=None)
        b = _authored_publication(doi=f"10.2/{uniq('b')}", person_id=None)

        r = auth_client.post(f"/api/publications/{a}/merge", json={"other_id": b})

        assert r.status_code == 422
        assert _exists(a)
        assert _exists(b)

    def test_unknown_publication_is_not_found(self, auth_client):
        a = _authored_publication(doi=None, person_id=None)

        r = auth_client.post(f"/api/publications/{a}/merge", json={"other_id": 999999999})

        assert r.status_code == 404


class TestPreview:
    def test_counts_conflicts_without_writing(self, auth_client):
        a = _authored_publication(doi=None, person_id=seed_person(uniq("Martin"), "Anne"))
        b = _authored_publication(doi=None, person_id=seed_person(uniq("Martin"), "Anne"))

        r = auth_client.post(f"/api/publications/{a}/merge-preview", json={"other_id": b})

        assert r.status_code == 200, r.text
        assert r.json()["conflicts"] == 1
        assert _exists(a)
        assert _exists(b)


def _titled_publication(title: str, doi: str | None = None) -> int:
    publication = seed_publication(title, doc_type="article")
    if doi:
        with owner_pool() as cur:
            cur.execute("UPDATE publications SET doi = %s WHERE id = %s", (doi, publication))
    return publication


class TestCandidates:
    def test_similar_titles_without_conflicting_doi(self, client):
        tag = uniq("x", sep="")
        title = f"au rugby comment arbitres et joueurs s adaptent {tag}"
        publication = _titled_publication(title, doi=f"10.64628/{tag}")
        similar = _titled_publication(f"{title} the conversation")
        other_doi = _titled_publication(title, doi=f"10.9/{tag}")

        r = client.get(f"/api/publications/{publication}/merge-candidates")

        assert r.status_code == 200
        ids = [c["publication_id"] for c in r.json()]
        assert similar in ids
        assert other_doi not in ids

    def test_search_by_doi(self, client):
        tag = uniq("x", sep="")
        publication = _titled_publication(f"premier titre {tag}")
        target = _titled_publication(f"second titre {tag}", doi=f"10.64628/{tag}")

        r = client.get(
            f"/api/publications/{publication}/merge-candidates",
            params={"q": f"https://doi.org/10.64628/{tag.upper()}"},
        )

        assert [c["publication_id"] for c in r.json()] == [target]
