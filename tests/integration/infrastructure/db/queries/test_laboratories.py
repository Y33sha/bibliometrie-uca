"""Tests d'intégration pour `infrastructure.db.queries.laboratories`."""

import json

from infrastructure.db.queries.laboratories import (
    LabPersonsFilters,
    get_laboratory,
    get_laboratory_addresses,
    get_laboratory_dashboard,
    get_laboratory_persons,
    list_laboratories,
)


def _create_structure(db, code, name=None, type_="labo", hal_collection=None):
    db.execute(
        """
        INSERT INTO structures (code, name, structure_type, hal_collection)
        VALUES (%s, %s, %s::structure_type, %s) RETURNING id
        """,
        (code, name or code, type_, hal_collection),
    )
    return db.fetchone()["id"]


def _setup_perimeter(db, lab_ids, code="uca"):
    root = _create_structure(db, code=code.upper(), type_="universite")
    all_ids = [root] + list(lab_ids)
    db.execute(
        "INSERT INTO perimeters (code, name, structure_ids) VALUES (%s, %s, %s)",
        (code, code.upper(), all_ids),
    )
    db.execute(
        "INSERT INTO config (key, value) VALUES ('perimeter_persons', to_jsonb(%s::text))",
        (code,),
    )
    # relation est_tutelle_de pour les descendants
    for lab in lab_ids:
        db.execute(
            "INSERT INTO structure_relations (parent_id, child_id, relation_type) "
            "VALUES (%s, %s, 'est_tutelle_de')",
            (root, lab),
        )
    return root


def _create_person(db, last="A", first="Z"):
    db.execute(
        "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
        "VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id",
        (last, first, last, first),
    )
    return db.fetchone()["id"]


def _create_pub_with_authorship(db, person_id, lab_id, doc_type="article", pub_year=2024, in_perimeter=True):
    db.execute(
        "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
        "VALUES ('X', 'x', %s, %s::doc_type) RETURNING id",
        (pub_year, doc_type),
    )
    pub_id = db.fetchone()["id"]
    db.execute(
        """
        INSERT INTO authorships (publication_id, person_id, structure_ids, in_perimeter, roles)
        VALUES (%s, %s, %s, %s, ARRAY['author']::text[]) RETURNING id
        """,
        (pub_id, person_id, [lab_id], in_perimeter),
    )
    return pub_id


class TestListLaboratories:
    def test_lists_labos_in_perimeter(self, db):
        lab = _create_structure(db, code="LAB-1", name="Lab 1")
        _setup_perimeter(db, [lab])
        labs = list_laboratories(db)
        ids = [lab_["id"] for lab_ in labs]
        assert lab in ids

    def test_excludes_root_as_tutelle(self, db):
        lab = _create_structure(db, code="LAB-2")
        _setup_perimeter(db, [lab])
        labs = list_laboratories(db)
        for lab_ in labs:
            if lab_["id"] == lab:
                # La racine est filtrée des tutelles
                tutelles_ids = [t["id"] for t in (lab_["tutelles"] or [])]
                assert all(t != lab for t in tutelles_ids)


class TestGetLaboratory:
    def test_returns_none_for_missing(self, db):
        assert get_laboratory(db, 999_999) is None

    def test_returns_full_profile(self, db):
        lab = _create_structure(db, code="LAB", name="Le labo", hal_collection="LAB-COL")
        res = get_laboratory(db, lab)
        assert res is not None
        assert res["structure"]["code"] == "LAB"
        assert res["structure"]["hal_collection"] == "LAB-COL"
        assert isinstance(res["parents"], list)
        assert isinstance(res["children"], list)
        assert isinstance(res["theses_count"], int)


class TestGetLaboratoryPersons:
    def test_returns_linked_persons(self, db):
        lab = _create_structure(db, code="LAB")
        pid = _create_person(db)
        _create_pub_with_authorship(db, pid, lab)

        res = get_laboratory_persons(
            db, lab, filters=LabPersonsFilters(), page=1, per_page=50, sort="name"
        )
        assert res["total_persons"] == 1
        assert res["persons"][0]["id"] == pid

    def test_search_filters_by_name(self, db):
        lab = _create_structure(db, code="LAB")
        p_match = _create_person(db, last="Dupond", first="Jean")
        p_other = _create_person(db, last="Autre", first="Zed")
        _create_pub_with_authorship(db, p_match, lab)
        _create_pub_with_authorship(db, p_other, lab)

        res = get_laboratory_persons(
            db, lab, filters=LabPersonsFilters(search="Dupond"), page=1, per_page=50, sort="name"
        )
        ids = [p["id"] for p in res["persons"]]
        assert p_match in ids and p_other not in ids

    def test_counts_orphan_authorships(self, db):
        lab = _create_structure(db, code="LAB")
        db.execute(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('X', 'x', 2024, 'article') RETURNING id"
        )
        pub = db.fetchone()["id"]
        db.execute(
            """
            INSERT INTO authorships (publication_id, person_id, structure_ids, roles)
            VALUES (%s, NULL, %s, ARRAY['author']::text[])
            """,
            (pub, [lab]),
        )

        res = get_laboratory_persons(
            db, lab, filters=LabPersonsFilters(), page=1, per_page=50, sort="name"
        )
        assert res["orphan_authorships"]["total"] == 1


class TestGetLaboratoryAddresses:
    def test_lists_linked_addresses(self, db):
        lab = _create_structure(db, code="LAB")
        db.execute(
            "INSERT INTO addresses (raw_text, normalized_text) VALUES ('A', 'a') RETURNING id"
        )
        addr = db.fetchone()["id"]
        db.execute(
            "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
            "VALUES (%s, %s, TRUE)",
            (addr, lab),
        )

        res = get_laboratory_addresses(db, lab, page=1, per_page=50)
        ids = [a["id"] for a in res["addresses"]]
        assert addr in ids

    def test_excludes_rejected_links(self, db):
        lab = _create_structure(db, code="LAB")
        db.execute("INSERT INTO addresses (raw_text, normalized_text) VALUES ('R', 'r') RETURNING id")
        addr = db.fetchone()["id"]
        db.execute(
            "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
            "VALUES (%s, %s, FALSE)",
            (addr, lab),
        )
        res = get_laboratory_addresses(db, lab, page=1, per_page=50)
        ids = [a["id"] for a in res["addresses"]]
        assert addr not in ids


class TestGetLaboratoryDashboard:
    def test_returns_structure_even_when_empty(self, db):
        lab = _create_structure(db, code="LAB")
        res = get_laboratory_dashboard(db, lab)
        assert "pubs_by_year" in res
        assert "oa" in res
        assert "collab" in res
        assert "top_countries" in res
        assert res["oa"]["total"] == 0

    def test_aggregates_oa_and_countries(self, db):
        db.execute(
            "INSERT INTO countries (code, name) VALUES ('us', 'USA') ON CONFLICT DO NOTHING"
        )
        lab = _create_structure(db, code="LAB")
        pid = _create_person(db)
        db.execute(
            """
            INSERT INTO publications (title, title_normalized, pub_year, doc_type, oa_status, countries)
            VALUES ('X', 'x', 2024, 'article', 'gold', ARRAY['fr', 'us'])
            RETURNING id
            """
        )
        pub_id = db.fetchone()["id"]
        db.execute(
            """
            INSERT INTO authorships (publication_id, person_id, structure_ids, in_perimeter, roles)
            VALUES (%s, %s, %s, TRUE, ARRAY['author']::text[])
            """,
            (pub_id, pid, [lab]),
        )

        res = get_laboratory_dashboard(db, lab)
        assert res["oa"]["open_access"] == 1
        assert res["collab"]["international"] == 1
        assert any(c["code"] == "us" for c in res["top_countries"])
