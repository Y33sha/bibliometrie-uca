"""Tests de caractérisation pour services/addresses.py.

Couvre review_structure_link et batch_review_structure_link.
Les fonctions de set_country / propagate_countries seront testées dans un
commit séparé (Phase B).
"""

import json

from services.addresses import batch_review_structure_link, review_structure_link


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
