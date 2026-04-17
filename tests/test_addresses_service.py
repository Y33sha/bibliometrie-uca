"""Tests de caractérisation pour services/addresses.py.

Couvre review_structure_link et batch_review_structure_link.
Les fonctions de set_country / propagate_countries seront testées dans un
commit séparé (Phase B).
"""

import json

from services.addresses import (
    batch_review_structure_link,
    batch_set_country_by_filter,
    batch_set_country_by_ids,
    propagate_countries_to_publications,
    propagate_countries_to_similar,
    review_structure_link,
    set_country,
    unassign_manual_structure,
)


# ── Helpers ────────────────────────────────────────────────────────

def _create_structure(db, code="UCA", name="UCA", structure_type="universite"):
    db.execute(
        """
        INSERT INTO structures (code, name, structure_type)
        VALUES (%s, %s, %s::structure_type)
        RETURNING id
        """,
        (code, name, structure_type),
    )
    return db.fetchone()["id"]


def _create_perimeter(db, code, structure_ids):
    db.execute(
        "INSERT INTO perimeters (code, name, structure_ids) VALUES (%s, %s, %s)",
        (code, code.upper(), structure_ids),
    )


def _set_config(db, key, value):
    db.execute(
        "INSERT INTO config (key, value) VALUES (%s, %s::jsonb)",
        (key, json.dumps(value)),
    )


def _create_address(db, raw_text="Université Clermont Auvergne"):
    db.execute(
        """
        INSERT INTO addresses (raw_text, normalized_text)
        VALUES (%s, lower(%s))
        RETURNING id
        """,
        (raw_text, raw_text),
    )
    return db.fetchone()["id"]


def _insert_address_structure(db, address_id, structure_id, *,
                              is_confirmed=None, matched_form_id=None):
    db.execute(
        """
        INSERT INTO address_structures (address_id, structure_id, is_confirmed, matched_form_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (address_id, structure_id, is_confirmed, matched_form_id),
    )
    return db.fetchone()["id"]


def _setup_uca_perimeter(db):
    """Monte un périmètre UCA minimal pour que propagate_uca_for_addresses marche."""
    uca = _create_structure(db, code="UCA", name="UCA", structure_type="universite")
    _create_perimeter(db, "uca", [uca])
    _set_config(db, "perimeter_persons", "uca")
    return uca


def _get_link(db, address_id, structure_id):
    db.execute(
        """
        SELECT is_confirmed, matched_form_id FROM address_structures
        WHERE address_id = %s AND structure_id = %s
        """,
        (address_id, structure_id),
    )
    return db.fetchone()


# ── review_structure_link ──────────────────────────────────────────

class TestReviewStructureLink:
    def test_confirm_creates_link_if_absent(self, db):
        uca = _setup_uca_perimeter(db)
        addr = _create_address(db)

        review_structure_link(db, addr, uca, True)

        link = _get_link(db, addr, uca)
        assert link is not None
        assert link["is_confirmed"] is True

    def test_reject_creates_link_if_absent(self, db):
        uca = _setup_uca_perimeter(db)
        addr = _create_address(db)

        review_structure_link(db, addr, uca, False)

        link = _get_link(db, addr, uca)
        assert link["is_confirmed"] is False

    def test_confirm_updates_existing_link(self, db):
        uca = _setup_uca_perimeter(db)
        addr = _create_address(db)
        _insert_address_structure(db, addr, uca, is_confirmed=False)

        review_structure_link(db, addr, uca, True)

        assert _get_link(db, addr, uca)["is_confirmed"] is True

    def test_reset_deletes_manual_link(self, db):
        """Reset supprime le lien manuel (matched_form_id IS NULL)."""
        uca = _setup_uca_perimeter(db)
        addr = _create_address(db)
        _insert_address_structure(db, addr, uca, is_confirmed=True)  # manuel

        review_structure_link(db, addr, uca, None)

        assert _get_link(db, addr, uca) is None

    def test_reset_preserves_auto_link_but_clears_confirmation(self, db):
        """Reset sur un lien auto-détecté : le lien reste, is_confirmed → NULL."""
        uca = _setup_uca_perimeter(db)
        addr = _create_address(db)
        # Form créée pour pouvoir renseigner matched_form_id
        db.execute(
            """
            INSERT INTO structure_name_forms (structure_id, form_text)
            VALUES (%s, 'uca') RETURNING id
            """,
            (uca,),
        )
        form_id = db.fetchone()["id"]
        _insert_address_structure(db, addr, uca,
                                  is_confirmed=False, matched_form_id=form_id)

        review_structure_link(db, addr, uca, None)

        link = _get_link(db, addr, uca)
        assert link is not None  # lien auto préservé
        assert link["is_confirmed"] is None  # confirmation nettoyée
        assert link["matched_form_id"] == form_id


# ── batch_review_structure_link ────────────────────────────────────

class TestBatchReviewStructureLink:
    def test_empty_returns_zero(self, db):
        uca = _setup_uca_perimeter(db)
        assert batch_review_structure_link(db, [], uca, True) == 0

    def test_confirm_upserts_lot(self, db):
        uca = _setup_uca_perimeter(db)
        addrs = [_create_address(db, raw_text=f"adr{i}") for i in range(3)]

        updated = batch_review_structure_link(db, addrs, uca, True)

        assert updated == 3
        for aid in addrs:
            assert _get_link(db, aid, uca)["is_confirmed"] is True

    def test_reject_lot(self, db):
        uca = _setup_uca_perimeter(db)
        addrs = [_create_address(db, raw_text=f"x{i}") for i in range(2)]

        batch_review_structure_link(db, addrs, uca, False)

        for aid in addrs:
            assert _get_link(db, aid, uca)["is_confirmed"] is False

    def test_reset_lot(self, db):
        uca = _setup_uca_perimeter(db)
        a1 = _create_address(db, raw_text="a1")
        a2 = _create_address(db, raw_text="a2")
        _insert_address_structure(db, a1, uca, is_confirmed=True)
        _insert_address_structure(db, a2, uca, is_confirmed=False)

        batch_review_structure_link(db, [a1, a2], uca, None)

        # Les 2 liens manuels ont été supprimés
        assert _get_link(db, a1, uca) is None
        assert _get_link(db, a2, uca) is None


# ── unassign_manual_structure ───────────────────────────────────────

class TestUnassignManualStructure:
    def test_deletes_manual_link(self, db):
        uca = _setup_uca_perimeter(db)
        addr = _create_address(db)
        _insert_address_structure(db, addr, uca, is_confirmed=True)  # manuel

        assert unassign_manual_structure(db, addr, uca) is True
        assert _get_link(db, addr, uca) is None

    def test_preserves_auto_link(self, db):
        """Un lien auto-détecté (matched_form_id non NULL) n'est pas supprimé."""
        uca = _setup_uca_perimeter(db)
        addr = _create_address(db)
        db.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text) VALUES (%s, 'uca') RETURNING id",
            (uca,),
        )
        form_id = db.fetchone()["id"]
        _insert_address_structure(db, addr, uca,
                                  is_confirmed=True, matched_form_id=form_id)

        assert unassign_manual_structure(db, addr, uca) is False  # rien supprimé
        link = _get_link(db, addr, uca)
        assert link is not None  # lien auto préservé
        assert link["is_confirmed"] is True  # is_confirmed NON touché

    def test_returns_false_if_no_link(self, db):
        uca = _setup_uca_perimeter(db)
        addr = _create_address(db)
        assert unassign_manual_structure(db, addr, uca) is False


# ── set_country ─────────────────────────────────────────────────────

def _ensure_country(db, code, name="Test"):
    db.execute(
        "INSERT INTO countries (code, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (code, name),
    )


def _get_countries(db, address_id):
    db.execute("SELECT countries FROM addresses WHERE id = %s", (address_id,))
    return db.fetchone()["countries"]


class TestSetCountry:
    def test_assigns_countries(self, db):
        _ensure_country(db, "FR")
        addr = _create_address(db)
        affected = set_country(db, addr, ["FR"])
        assert affected == [addr]
        assert _get_countries(db, addr) == ["FR"]

    def test_none_clears_countries(self, db):
        _ensure_country(db, "FR")
        addr = _create_address(db)
        set_country(db, addr, ["FR"])
        set_country(db, addr, None)
        assert _get_countries(db, addr) is None

    def test_propagates_to_same_normalized_text(self, db):
        """Les adresses avec même normalized_text héritent des countries."""
        _ensure_country(db, "FR")
        a1 = _create_address(db, raw_text="UCA A")
        a2 = _create_address(db, raw_text="UCA B")
        # Forcer le même normalized_text (simule le pipeline de normalisation)
        db.execute(
            "UPDATE addresses SET normalized_text = 'universite clermont auvergne' WHERE id IN (%s, %s)",
            (a1, a2),
        )
        set_country(db, a1, ["FR"])
        assert _get_countries(db, a1) == ["FR"]
        assert _get_countries(db, a2) == ["FR"]  # propagé

    def test_no_propagation_on_short_normalized(self, db):
        """Pas de propagation si normalized_text < 5 chars."""
        _ensure_country(db, "FR")
        a1 = _create_address(db, raw_text="addr short A")
        a2 = _create_address(db, raw_text="addr short B")
        db.execute(
            "UPDATE addresses SET normalized_text = 'abc' WHERE id IN (%s, %s)",
            (a1, a2),
        )
        set_country(db, a1, ["FR"])
        assert _get_countries(db, a2) is None


# ── batch_set_country_by_ids ────────────────────────────────────────

class TestBatchSetCountryByIds:
    def test_adds_to_empty_countries(self, db):
        _ensure_country(db, "FR")
        addrs = [_create_address(db, raw_text=f"a{i}") for i in range(3)]
        modified = batch_set_country_by_ids(db, "FR", addrs)
        assert set(modified) == set(addrs)
        for a in addrs:
            assert _get_countries(db, a) == ["FR"]

    def test_appends_to_existing_countries(self, db):
        _ensure_country(db, "FR")
        _ensure_country(db, "US")
        addr = _create_address(db)
        set_country(db, addr, ["FR"])
        batch_set_country_by_ids(db, "US", [addr])
        countries = _get_countries(db, addr)
        assert "FR" in countries and "US" in countries

    def test_idempotent_if_already_present(self, db):
        _ensure_country(db, "FR")
        addr = _create_address(db)
        set_country(db, addr, ["FR"])
        batch_set_country_by_ids(db, "FR", [addr])
        assert _get_countries(db, addr) == ["FR"]  # pas de doublon


# ── batch_set_country_by_filter ─────────────────────────────────────

class TestBatchSetCountryByFilter:
    def test_filter_by_search(self, db):
        _ensure_country(db, "FR")
        match = _create_address(db, raw_text="Université Clermont")
        other = _create_address(db, raw_text="MIT Boston")
        modified = batch_set_country_by_filter(db, "FR", search="Clermont")
        assert match in modified
        assert other not in modified

    def test_filter_has_country_no(self, db):
        _ensure_country(db, "FR")
        _ensure_country(db, "US")
        addr_no = _create_address(db, raw_text="sans pays")
        addr_yes = _create_address(db, raw_text="avec pays")
        set_country(db, addr_yes, ["US"])
        modified = batch_set_country_by_filter(db, "FR", has_country="no")
        assert addr_no in modified
        assert addr_yes not in modified


# ── propagate_countries_to_similar ──────────────────────────────────

class TestPropagateCountriesToSimilar:
    def test_propagates_divergent_values(self, db):
        """Deux adresses de même normalized_text avec countries différents :
        la 2e reçoit les countries de la 1ère."""
        _ensure_country(db, "FR")
        a1 = _create_address(db, raw_text="UCA AA")
        a2 = _create_address(db, raw_text="UCA BB")
        db.execute(
            "UPDATE addresses SET normalized_text = 'universite clermont auvergne' WHERE id IN (%s, %s)",
            (a1, a2),
        )
        # a1 a FR, a2 n'a rien
        db.execute("UPDATE addresses SET countries = %s WHERE id = %s", (["FR"], a1))

        propagated = propagate_countries_to_similar(db)

        assert a2 in propagated
        assert _get_countries(db, a2) == ["FR"]


# ── propagate_countries_to_publications ─────────────────────────────

class TestPropagateCountriesToPublications:
    def test_empty_is_noop(self, db):
        propagate_countries_to_publications(db, [])  # pas d'exception

    def test_propagates_to_source_pub_and_publication(self, db):
        """Test d'intégration minimal : une adresse avec countries liée à
        une source_authorship, le pays doit remonter jusqu'à publications.countries."""
        _ensure_country(db, "FR")
        # Setup minimal : publication + source_publication + source_authorship + adresse liée
        db.execute(
            "INSERT INTO publications (title, pub_year) VALUES ('Test', 2024) RETURNING id"
        )
        pub_id = db.fetchone()["id"]
        db.execute(
            """
            INSERT INTO source_publications (source, source_id, title, publication_id)
            VALUES ('hal', 'h-1', 'Test', %s) RETURNING id
            """,
            (pub_id,),
        )
        sp_id = db.fetchone()["id"]
        db.execute(
            """
            INSERT INTO source_persons (source, source_id, full_name)
            VALUES ('hal', 'p-1', 'J D') RETURNING id
            """
        )
        sperson_id = db.fetchone()["id"]
        db.execute(
            """
            INSERT INTO source_authorships (source, source_publication_id, source_person_id)
            VALUES ('hal', %s, %s) RETURNING id
            """,
            (sp_id, sperson_id),
        )
        sa_id = db.fetchone()["id"]
        addr = _create_address(db)
        db.execute("UPDATE addresses SET countries = %s WHERE id = %s", (["FR"], addr))
        db.execute(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) VALUES (%s, %s)",
            (sa_id, addr),
        )

        propagate_countries_to_publications(db, [addr])

        # source_publications.countries mis à jour
        db.execute("SELECT countries FROM source_publications WHERE id = %s", (sp_id,))
        assert db.fetchone()["countries"] == ["FR"]
        # publications.countries mis à jour
        db.execute("SELECT countries FROM publications WHERE id = %s", (pub_id,))
        assert db.fetchone()["countries"] == ["FR"]
