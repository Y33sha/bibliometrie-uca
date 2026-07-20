"""Tests de caractérisation pour application/addresses_structures.py
et application/addresses_countries.py."""

import json

import pytest
from sqlalchemy import text

from application.services.addresses.countries import (
    batch_set_country_by_filter,
    batch_set_country_by_ids,
    propagate_countries_to_publications,
    propagate_countries_to_similar,
    set_country,
)
from application.services.addresses.structure_links import (
    batch_review_structure_link,
    review_structure_link,
)
from domain.errors import NotFoundError, ValidationError
from infrastructure.queries.perimeter import PgPerimeterQueries
from infrastructure.repositories import address_repository, authorship_repository
from tests.integration.helpers.authorships import upsert_identity


@pytest.fixture
def repo(sa_sync_conn):
    return address_repository(sa_sync_conn)


@pytest.fixture
def perimeter_queries():
    return PgPerimeterQueries()


@pytest.fixture
def authorship_repo(sa_sync_conn):
    return authorship_repository(sa_sync_conn)


# ── Helpers (SQLAlchemy text, paramstyle nommé) ───────────────────


def _create_structure(conn, code="UCA", name="UCA", structure_type="universite"):
    result = conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (:code, :name, CAST(:st AS structure_type)) RETURNING id"
        ),
        {"code": code, "name": name, "st": structure_type},
    )
    return result.scalar_one()


def _create_perimeter(conn, code, structure_ids):
    conn.execute(
        text("INSERT INTO perimeters (code, name, root_structure_ids) VALUES (:code, :name, :ids)"),
        {"code": code, "name": code.upper(), "ids": structure_ids},
    )


def _set_config(conn, key, value):
    conn.execute(
        text("INSERT INTO config (key, value) VALUES (:key, CAST(:val AS jsonb))"),
        {"key": key, "val": json.dumps(value)},
    )


def _create_address(conn, raw_text="Université Clermont Auvergne"):
    result = conn.execute(
        text(
            "INSERT INTO addresses (raw_text, normalized_text) "
            "VALUES (:raw, lower(:raw)) RETURNING id"
        ),
        {"raw": raw_text},
    )
    return result.scalar_one()


def _insert_address_structure(
    conn, address_id, structure_id, *, is_confirmed=None, matched_form_id=None
):
    result = conn.execute(
        text(
            "INSERT INTO address_structures "
            "(address_id, structure_id, is_confirmed, matched_form_id) "
            "VALUES (:aid, :sid, :ic, :mf) RETURNING id"
        ),
        {"aid": address_id, "sid": structure_id, "ic": is_confirmed, "mf": matched_form_id},
    )
    return result.scalar_one()


def _setup_uca_perimeter(conn):
    """Monte un périmètre UCA minimal pour que propagate_in_perimeter_for_addresses marche."""
    uca = _create_structure(conn, code="UCA", name="UCA", structure_type="universite")
    _create_perimeter(conn, "uca", [uca])
    _set_config(conn, "perimeter_persons", "uca")
    return uca


def _get_link(conn, address_id, structure_id):
    result = conn.execute(
        text(
            "SELECT is_confirmed, matched_form_id FROM address_structures "
            "WHERE address_id = :aid AND structure_id = :sid"
        ),
        {"aid": address_id, "sid": structure_id},
    )
    row = result.first()
    return dict(row._mapping) if row else None


# ── review_structure_link ──────────────────────────────────────────


class TestReviewStructureLink:
    def test_confirm_creates_link_if_absent(self, sa_sync_conn, repo):
        uca = _setup_uca_perimeter(sa_sync_conn)
        addr = _create_address(sa_sync_conn)

        review_structure_link(addr, uca, True, repo=repo)

        link = _get_link(sa_sync_conn, addr, uca)
        assert link is not None
        assert link["is_confirmed"] is True

    def test_reject_creates_link_if_absent(self, sa_sync_conn, repo):
        uca = _setup_uca_perimeter(sa_sync_conn)
        addr = _create_address(sa_sync_conn)

        review_structure_link(addr, uca, False, repo=repo)

        link = _get_link(sa_sync_conn, addr, uca)
        assert link["is_confirmed"] is False

    def test_confirm_updates_existing_link(self, sa_sync_conn, repo):
        uca = _setup_uca_perimeter(sa_sync_conn)
        addr = _create_address(sa_sync_conn)
        _insert_address_structure(sa_sync_conn, addr, uca, is_confirmed=False)

        review_structure_link(addr, uca, True, repo=repo)

        assert _get_link(sa_sync_conn, addr, uca)["is_confirmed"] is True

    def test_reset_deletes_manual_link(self, sa_sync_conn, repo):
        """Reset supprime le lien manuel (matched_form_id IS NULL)."""
        uca = _setup_uca_perimeter(sa_sync_conn)
        addr = _create_address(sa_sync_conn)
        _insert_address_structure(sa_sync_conn, addr, uca, is_confirmed=True)  # manuel

        review_structure_link(addr, uca, None, repo=repo)

        assert _get_link(sa_sync_conn, addr, uca) is None

    def test_reset_preserves_auto_link_but_clears_confirmation(self, sa_sync_conn, repo):
        """Reset sur un lien auto-détecté : le lien reste, is_confirmed → NULL."""
        uca = _setup_uca_perimeter(sa_sync_conn)
        addr = _create_address(sa_sync_conn)
        form_id = sa_sync_conn.execute(
            text(
                "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
                "VALUES (:sid, 'uca', true) RETURNING id"
            ),
            {"sid": uca},
        ).scalar_one()
        _insert_address_structure(
            sa_sync_conn, addr, uca, is_confirmed=False, matched_form_id=form_id
        )

        review_structure_link(addr, uca, None, repo=repo)

        link = _get_link(sa_sync_conn, addr, uca)
        assert link is not None  # lien auto préservé
        assert link["is_confirmed"] is None  # confirmation nettoyée
        assert link["matched_form_id"] == form_id


# ── batch_review_structure_link ────────────────────────────────────


class TestBatchReviewStructureLink:
    def test_empty_returns_zero(self, sa_sync_conn, repo):
        uca = _setup_uca_perimeter(sa_sync_conn)
        updated, changed = batch_review_structure_link([], uca, True, repo=repo)
        assert updated == 0
        assert changed == []

    def test_confirm_upserts_lot(self, sa_sync_conn, repo):
        uca = _setup_uca_perimeter(sa_sync_conn)
        addrs = [_create_address(sa_sync_conn, raw_text=f"adr{i}") for i in range(3)]

        updated, _ = batch_review_structure_link(addrs, uca, True, repo=repo)

        assert updated == 3
        for aid in addrs:
            assert _get_link(sa_sync_conn, aid, uca)["is_confirmed"] is True

    def test_reject_lot(self, sa_sync_conn, repo):
        uca = _setup_uca_perimeter(sa_sync_conn)
        addrs = [_create_address(sa_sync_conn, raw_text=f"x{i}") for i in range(2)]

        batch_review_structure_link(addrs, uca, False, repo=repo)

        for aid in addrs:
            assert _get_link(sa_sync_conn, aid, uca)["is_confirmed"] is False

    def test_reset_lot(self, sa_sync_conn, repo):
        uca = _setup_uca_perimeter(sa_sync_conn)
        a1 = _create_address(sa_sync_conn, raw_text="a1")
        a2 = _create_address(sa_sync_conn, raw_text="a2")
        _insert_address_structure(sa_sync_conn, a1, uca, is_confirmed=True)
        _insert_address_structure(sa_sync_conn, a2, uca, is_confirmed=False)

        updated, _ = batch_review_structure_link([a1, a2], uca, None, repo=repo)

        # Les 2 liens manuels sont supprimés, et comptés parmi les adresses touchées.
        assert updated == 2
        assert _get_link(sa_sync_conn, a1, uca) is None
        assert _get_link(sa_sync_conn, a2, uca) is None


# ── set_country ─────────────────────────────────────────────────────


def _ensure_country(conn, code, name="Test"):
    conn.execute(
        text("INSERT INTO countries (code, name) VALUES (:code, :name) ON CONFLICT DO NOTHING"),
        {"code": code, "name": name},
    )


def _get_countries(conn, address_id):
    result = conn.execute(
        text("SELECT countries FROM addresses WHERE id = :id"), {"id": address_id}
    )
    row = result.first()
    return row.countries if row else None


class TestSetCountry:
    def test_assigns_countries(self, sa_sync_conn, repo):
        _ensure_country(sa_sync_conn, "FR")
        addr = _create_address(sa_sync_conn)
        affected = set_country(addr, ["FR"], repo=repo)
        assert affected == [addr]
        assert _get_countries(sa_sync_conn, addr) == ["FR"]

    def test_raises_on_unknown_country(self, sa_sync_conn, repo):
        """`addresses.countries` est un tableau : aucune clé étrangère n'en garde les éléments."""
        addr = _create_address(sa_sync_conn)
        with pytest.raises(ValidationError, match="Code pays inconnu"):
            set_country(addr, ["ZZ"], repo=repo)
        assert _get_countries(sa_sync_conn, addr) is None

    def test_raises_on_unknown_address(self, sa_sync_conn, repo):
        """L'`UPDATE` n'apparie aucune ligne : sans cette garde, l'API répondrait 200 sans rien faire."""
        _ensure_country(sa_sync_conn, "FR")
        with pytest.raises(NotFoundError):
            set_country(999999, ["FR"], repo=repo)

    def test_raises_on_one_unknown_among_known(self, sa_sync_conn, repo):
        _ensure_country(sa_sync_conn, "FR")
        addr = _create_address(sa_sync_conn)
        with pytest.raises(ValidationError, match="ZZ"):
            set_country(addr, ["FR", "ZZ"], repo=repo)
        assert _get_countries(sa_sync_conn, addr) is None

    def test_none_clears_countries(self, sa_sync_conn, repo):
        _ensure_country(sa_sync_conn, "FR")
        addr = _create_address(sa_sync_conn)
        set_country(addr, ["FR"], repo=repo)
        set_country(addr, None, repo=repo)
        assert _get_countries(sa_sync_conn, addr) is None

    def test_propagates_to_same_normalized_text(self, sa_sync_conn, repo):
        """Les adresses avec même normalized_text héritent des countries."""
        _ensure_country(sa_sync_conn, "FR")
        a1 = _create_address(sa_sync_conn, raw_text="UCA A")
        a2 = _create_address(sa_sync_conn, raw_text="UCA B")
        # Forcer le même normalized_text (simule le pipeline de normalisation)
        sa_sync_conn.execute(
            text(
                "UPDATE addresses SET normalized_text = 'universite clermont auvergne' "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": [a1, a2]},
        )
        set_country(a1, ["FR"], repo=repo)
        assert _get_countries(sa_sync_conn, a1) == ["FR"]
        assert _get_countries(sa_sync_conn, a2) == ["FR"]  # propagé

    def test_propagates_on_short_normalized(self, sa_sync_conn, repo):
        """Deux adresses de même normalized_text court héritent aussi des countries."""
        _ensure_country(sa_sync_conn, "FR")
        a1 = _create_address(sa_sync_conn, raw_text="Lyon A")
        a2 = _create_address(sa_sync_conn, raw_text="Lyon B")
        sa_sync_conn.execute(
            text("UPDATE addresses SET normalized_text = 'lyon' WHERE id = ANY(:ids)"),
            {"ids": [a1, a2]},
        )
        set_country(a1, ["FR"], repo=repo)
        assert _get_countries(sa_sync_conn, a2) == ["FR"]


# ── batch_set_country_by_ids ────────────────────────────────────────


class TestBatchSetCountryByIds:
    def test_adds_to_empty_countries(self, sa_sync_conn, repo):
        _ensure_country(sa_sync_conn, "FR")
        addrs = [_create_address(sa_sync_conn, raw_text=f"a{i}") for i in range(3)]
        modified = batch_set_country_by_ids("FR", addrs, repo=repo)
        assert set(modified) == set(addrs)
        for a in addrs:
            assert _get_countries(sa_sync_conn, a) == ["FR"]

    def test_raises_on_unknown_country(self, sa_sync_conn, repo):
        addr = _create_address(sa_sync_conn)
        with pytest.raises(ValidationError, match="Code pays inconnu"):
            batch_set_country_by_ids("ZZ", [addr], repo=repo)

    def test_raises_on_empty_country_code(self, sa_sync_conn, repo):
        """La chaîne vide ne figure pas au référentiel : le contrôle référentiel la couvre."""
        addr = _create_address(sa_sync_conn)
        with pytest.raises(ValidationError, match="Code pays inconnu"):
            batch_set_country_by_ids("", [addr], repo=repo)

    def test_appends_to_existing_countries(self, sa_sync_conn, repo):
        _ensure_country(sa_sync_conn, "FR")
        _ensure_country(sa_sync_conn, "US")
        addr = _create_address(sa_sync_conn)
        set_country(addr, ["FR"], repo=repo)
        batch_set_country_by_ids("US", [addr], repo=repo)
        countries = _get_countries(sa_sync_conn, addr)
        assert "FR" in countries and "US" in countries

    def test_idempotent_if_already_present(self, sa_sync_conn, repo):
        _ensure_country(sa_sync_conn, "FR")
        addr = _create_address(sa_sync_conn)
        set_country(addr, ["FR"], repo=repo)
        batch_set_country_by_ids("FR", [addr], repo=repo)
        assert _get_countries(sa_sync_conn, addr) == ["FR"]  # pas de doublon


# ── batch_set_country_by_filter ─────────────────────────────────────


class TestBatchSetCountryByFilter:
    def test_filter_by_search(self, sa_sync_conn, repo):
        _ensure_country(sa_sync_conn, "FR")
        match = _create_address(sa_sync_conn, raw_text="Université Clermont")
        other = _create_address(sa_sync_conn, raw_text="MIT Boston")
        modified = batch_set_country_by_filter("FR", search="Clermont", repo=repo)
        assert match in modified
        assert other not in modified

    def test_raises_on_unknown_country(self, sa_sync_conn, repo):
        _create_address(sa_sync_conn, raw_text="Université Clermont")
        with pytest.raises(ValidationError, match="Code pays inconnu"):
            batch_set_country_by_filter("ZZ", search="Clermont", repo=repo)

    def test_filter_has_country_no(self, sa_sync_conn, repo):
        _ensure_country(sa_sync_conn, "FR")
        _ensure_country(sa_sync_conn, "US")
        addr_no = _create_address(sa_sync_conn, raw_text="sans pays")
        addr_yes = _create_address(sa_sync_conn, raw_text="avec pays")
        set_country(addr_yes, ["US"], repo=repo)
        modified = batch_set_country_by_filter("FR", has_country=False, repo=repo)
        assert addr_no in modified
        assert addr_yes not in modified

    def test_empty_filter_raises(self, repo):
        """Aucun filtre → refus (garde-fou : ne pas viser toutes les adresses)."""
        with pytest.raises(ValidationError):
            batch_set_country_by_filter("FR", repo=repo)


# ── propagate_countries_to_similar ──────────────────────────────────


class TestPropagateCountriesToSimilar:
    def test_propagates_divergent_values_from_modified_source(self, sa_sync_conn, repo):
        """Deux adresses de même normalized_text avec countries différents :
        la 2e reçoit les countries de la 1ère quand a1 est dans modified_ids."""
        _ensure_country(sa_sync_conn, "FR")
        a1 = _create_address(sa_sync_conn, raw_text="UCA AA")
        a2 = _create_address(sa_sync_conn, raw_text="UCA BB")
        sa_sync_conn.execute(
            text(
                "UPDATE addresses SET normalized_text = 'universite clermont auvergne' "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": [a1, a2]},
        )
        # a1 a FR, a2 n'a rien
        sa_sync_conn.execute(
            text("UPDATE addresses SET countries = :c WHERE id = :id"),
            {"c": ["FR"], "id": a1},
        )

        propagated = propagate_countries_to_similar(modified_ids=[a1], repo=repo)

        assert a2 in propagated
        assert _get_countries(sa_sync_conn, a2) == ["FR"]

    def test_does_not_propagate_from_unmodified_sources(self, sa_sync_conn, repo):
        """Seules les adresses passées en modified_ids servent de source de propagation : une adresse `a1` avec pays mais hors `modified_ids` ne doit PAS propager vers `a2` similaire. Régression : avant le ciblage, la propagation balayait toute la table et propageait depuis n'importe quelle adresse avec un pays, ce qui rendait la query O(n²) sur 475k lignes."""
        _ensure_country(sa_sync_conn, "FR")
        a1 = _create_address(sa_sync_conn, raw_text="UCA CC")
        a2 = _create_address(sa_sync_conn, raw_text="UCA DD")
        sa_sync_conn.execute(
            text(
                "UPDATE addresses SET normalized_text = 'universite clermont auvergne' "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": [a1, a2]},
        )
        sa_sync_conn.execute(
            text("UPDATE addresses SET countries = :c WHERE id = :id"),
            {"c": ["FR"], "id": a1},
        )

        # On passe un id qui n'a aucun pays : pas de propagation depuis lui.
        propagated = propagate_countries_to_similar(modified_ids=[a2], repo=repo)

        assert propagated == []
        assert _get_countries(sa_sync_conn, a2) is None

    def test_empty_modified_ids_is_noop(self, repo):
        assert propagate_countries_to_similar(modified_ids=[], repo=repo) == []


# ── propagate_countries_to_publications ─────────────────────────────


class TestPropagateCountriesToPublications:
    def test_empty_is_noop(self, sa_sync_conn, repo):
        propagate_countries_to_publications([], repo=repo)  # pas d'exception

    def test_propagates_to_source_pub_and_publication(self, sa_sync_conn, repo):
        """Test d'intégration minimal : une adresse avec countries liée à
        une source_authorship, le pays doit remonter jusqu'à publications.countries."""
        _ensure_country(sa_sync_conn, "FR")
        pub_id = sa_sync_conn.execute(
            text("INSERT INTO publications (title, pub_year) VALUES ('Test', 2024) RETURNING id")
        ).scalar_one()
        sp_id = sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications (source, source_id, title, publication_id) "
                "VALUES ('hal', 'h-1', 'Test', :pid) RETURNING id"
            ),
            {"pid": pub_id},
        ).scalar_one()
        identity_id = upsert_identity(sa_sync_conn)
        sa_id = sa_sync_conn.execute(
            text(
                "INSERT INTO source_authorships "
                "(source, source_publication_id, author_position, identity_id) "
                "VALUES ('hal', :sp, 0, :iid) RETURNING id"
            ),
            {"sp": sp_id, "iid": identity_id},
        ).scalar_one()
        addr = _create_address(sa_sync_conn)
        sa_sync_conn.execute(
            text("UPDATE addresses SET countries = :c WHERE id = :id"),
            {"c": ["FR"], "id": addr},
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_authorship_addresses "
                "(source_authorship_id, address_id) VALUES (:sa, :a)"
            ),
            {"sa": sa_id, "a": addr},
        )

        propagate_countries_to_publications([addr], repo=repo)

        # source_publications.countries mis à jour
        sp_countries = sa_sync_conn.execute(
            text("SELECT countries FROM source_publications WHERE id = :id"), {"id": sp_id}
        ).scalar_one()
        assert sp_countries == ["FR"]
        # publications.countries mis à jour
        p_countries = sa_sync_conn.execute(
            text("SELECT countries FROM publications WHERE id = :id"), {"id": pub_id}
        ).scalar_one()
        assert p_countries == ["FR"]


# ── No-op skip (éviter les cascades massives inutiles) ────────────


class TestPropagationSkipsNoOp:
    """Vérifie que `changed` (les adresses à propager) est vide quand le
    changement de is_confirmed n'affecte pas le calcul in_perimeter — la
    propagation (désormais lancée en tâche de fond par le caller) n'est alors
    pas planifiée.

    Règle : contribue au périmètre ssi le lien existe ET
    is_confirmed IS DISTINCT FROM FALSE (NULL ou TRUE).
    Donc NULL ↔ TRUE ne changent rien, seuls les passages par FALSE comptent.
    """

    def test_confirm_auto_detected_skips_propagation(self, sa_sync_conn, repo):
        """Click Relier sur une adresse auto-détectée (NULL → TRUE) = no-op."""
        uca = _setup_uca_perimeter(sa_sync_conn)
        addr = _create_address(sa_sync_conn)
        # Lien auto-détecté, is_confirmed=NULL (cas reproducteur du bug initial)
        form_id = sa_sync_conn.execute(
            text(
                "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
                "VALUES (:sid, 'uca', true) RETURNING id"
            ),
            {"sid": uca},
        ).scalar_one()
        _insert_address_structure(
            sa_sync_conn, addr, uca, is_confirmed=None, matched_form_id=form_id
        )

        changed = review_structure_link(addr, uca, True, repo=repo)

        assert changed == []
        # Le lien a bien été mis à jour
        assert _get_link(sa_sync_conn, addr, uca)["is_confirmed"] is True

    def test_reconfirm_already_confirmed_skips_propagation(self, sa_sync_conn, repo):
        """Cliquer Relier sur un lien déjà TRUE = no-op."""
        uca = _setup_uca_perimeter(sa_sync_conn)
        addr = _create_address(sa_sync_conn)
        _insert_address_structure(sa_sync_conn, addr, uca, is_confirmed=True)

        changed = review_structure_link(addr, uca, True, repo=repo)

        assert changed == []

    def test_confirm_rejected_triggers_propagation(self, sa_sync_conn, repo):
        """FALSE → TRUE : vrai changement, propagation attendue."""
        uca = _setup_uca_perimeter(sa_sync_conn)
        addr = _create_address(sa_sync_conn)
        _insert_address_structure(sa_sync_conn, addr, uca, is_confirmed=False)

        changed = review_structure_link(addr, uca, True, repo=repo)

        assert changed == [addr]

    def test_reject_confirmed_triggers_propagation(self, sa_sync_conn, repo):
        """TRUE → FALSE : vrai changement (sort du périmètre), propagation."""
        uca = _setup_uca_perimeter(sa_sync_conn)
        addr = _create_address(sa_sync_conn)
        _insert_address_structure(sa_sync_conn, addr, uca, is_confirmed=True)

        changed = review_structure_link(addr, uca, False, repo=repo)

        assert changed == [addr]

    def test_reject_absent_creates_and_triggers_propagation(self, sa_sync_conn, repo):
        """Pas de lien → FALSE : pas de contribution avant ni après, no-op."""
        uca = _setup_uca_perimeter(sa_sync_conn)
        addr = _create_address(sa_sync_conn)

        changed = review_structure_link(addr, uca, False, repo=repo)

        # Avant = pas de lien (ne contribue pas), après = lien FALSE (ne contribue pas)
        # → no-op
        assert changed == []

    def test_confirm_absent_creates_and_triggers_propagation(self, sa_sync_conn, repo):
        """Pas de lien → TRUE : contribue maintenant, propagation attendue."""
        uca = _setup_uca_perimeter(sa_sync_conn)
        addr = _create_address(sa_sync_conn)

        changed = review_structure_link(addr, uca, True, repo=repo)

        assert changed == [addr]

    def test_batch_only_propagates_changed(self, sa_sync_conn, repo):
        """Batch mixte : certaines adresses changent, d'autres non.
        `changed` restreint aux adresses effectivement impactées."""
        uca = _setup_uca_perimeter(sa_sync_conn)
        # a1 : auto-détectée NULL → TRUE (no-op)
        # a2 : rejetée FALSE → TRUE (changement)
        # a3 : pas de lien → TRUE (changement)
        a1 = _create_address(sa_sync_conn, raw_text="a1")
        a2 = _create_address(sa_sync_conn, raw_text="a2")
        a3 = _create_address(sa_sync_conn, raw_text="a3")
        form_id = sa_sync_conn.execute(
            text(
                "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
                "VALUES (:sid, 'uca2', true) RETURNING id"
            ),
            {"sid": uca},
        ).scalar_one()
        _insert_address_structure(sa_sync_conn, a1, uca, is_confirmed=None, matched_form_id=form_id)
        _insert_address_structure(sa_sync_conn, a2, uca, is_confirmed=False)

        _, changed = batch_review_structure_link([a1, a2, a3], uca, True, repo=repo)

        # a1 inchangée (déjà contribuait), a2 et a3 nouvellement contribuent
        assert set(changed) == {a2, a3}
