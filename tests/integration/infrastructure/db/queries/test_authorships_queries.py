"""Tests d'intégration pour `infrastructure.db.queries.authorships`."""

from infrastructure.db.queries.authorships import (
    authorships_facets,
    authorships_stats,
    list_authorships,
)


def _create_person(db):
    db.execute(
        "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
        "VALUES ('X', 'Y', 'x', 'y') RETURNING id"
    )
    return db.fetchone()["id"]


def _create_pub(db):
    db.execute(
        "INSERT INTO publications (title, pub_year, doc_type) VALUES ('X', 2024, 'article') RETURNING id"
    )
    return db.fetchone()["id"]


def _create_sd(db, pub_id, source="hal", source_id="h1"):
    db.execute(
        "INSERT INTO source_publications (source, source_id, title, publication_id) "
        "VALUES (%s, %s, 'X', %s) RETURNING id",
        (source, source_id, pub_id),
    )
    return db.fetchone()["id"]


def _create_sp(db, source="hal", source_id="sp1", orcid=None, idhal=None, full_name="X"):
    import json as _json

    source_ids = {}
    if idhal:
        source_ids["idhal"] = idhal
    db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name, orcid, source_ids)
        VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id
        """,
        (source, source_id, full_name, orcid, _json.dumps(source_ids) if source_ids else None),
    )
    return db.fetchone()["id"]


def _create_sa(
    db, sd, sp, source="hal", person_id=None, in_perimeter=True, structure_ids=None
):
    db.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             person_id, in_perimeter, structure_ids)
        VALUES (%s, %s, %s, 0, %s, %s, %s) RETURNING id
        """,
        (source, sd, sp, person_id, in_perimeter, structure_ids),
    )
    return db.fetchone()["id"]


def _create_lab(db, code="LAB"):
    db.execute(
        "INSERT INTO structures (code, name, structure_type) VALUES (%s, 'L', 'labo') RETURNING id",
        (code,),
    )
    return db.fetchone()["id"]


class TestAuthorshipsStats:
    def test_counts_uca_authors(self, db):
        pid = _create_person(db)
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp_linked = _create_sp(db, source_id="sp-linked", orcid="0000-1", idhal="IDH1")
        sp_other = _create_sp(db, source_id="sp-other")
        _create_sa(db, sd, sp_linked, person_id=pid)
        _create_sa(db, sd, sp_other)

        stats = authorships_stats(db, lab_id=0)
        assert stats["total_uca_authors"] >= 2
        assert stats["linked_to_person"] >= 1
        assert stats["with_orcid"] >= 1
        assert stats["with_idhal"] >= 1

    def test_filters_by_lab(self, db):
        lab = _create_lab(db)
        other_lab = _create_lab(db, code="OTHER")
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp_in = _create_sp(db, source_id="sp-in")
        sp_out = _create_sp(db, source_id="sp-out")
        _create_sa(db, sd, sp_in, structure_ids=[lab])
        _create_sa(db, sd, sp_out, structure_ids=[other_lab])

        stats = authorships_stats(db, lab_id=lab)
        assert stats["total_uca_authors"] == 1


class TestAuthorshipsFacets:
    def test_returns_all_facet_keys(self, db):
        pid = _create_person(db)
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp = _create_sp(db, orcid="O", idhal="H")
        _create_sa(db, sd, sp, person_id=pid)

        facets = authorships_facets(db, linked="", has_orcid="", has_idhal="", lab_id=0)
        assert set(facets.keys()) == {"linked", "orcid", "idhal", "labs"}

    def test_excludes_own_filter(self, db):
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp_orcid = _create_sp(db, source_id="with-o", orcid="0000")
        sp_no = _create_sp(db, source_id="no-o")
        _create_sa(db, sd, sp_orcid)
        _create_sa(db, sd, sp_no)

        facets = authorships_facets(db, linked="", has_orcid="yes", has_idhal="", lab_id=0)
        # La facette orcid ignore son propre filtre : yes + no tous deux comptés
        assert facets["orcid"]["yes"] >= 1
        assert facets["orcid"]["no"] >= 1


class TestListAuthorships:
    def test_lists_uca_authors(self, db):
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp = _create_sp(db, full_name="Dupond Jean")
        _create_sa(db, sd, sp)

        res = list_authorships(
            db, search="", linked="", has_orcid="", has_idhal="", lab_id=0, page=1, per_page=50
        )
        assert res["total"] >= 1
        assert any(a["id"] == sp for a in res["authors"])

    def test_search_filters_by_name(self, db):
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp_match = _create_sp(db, source_id="sp-m", full_name="SpecialName Z")
        sp_other = _create_sp(db, source_id="sp-o", full_name="Autre")
        _create_sa(db, sd, sp_match)
        _create_sa(db, sd, sp_other)

        res = list_authorships(
            db,
            search="SpecialName",
            linked="",
            has_orcid="",
            has_idhal="",
            lab_id=0,
            page=1,
            per_page=50,
        )
        ids = [a["id"] for a in res["authors"]]
        assert sp_match in ids
        assert sp_other not in ids
