"""Tests de caractérisation pour application/addresses_structures.py
et application/addresses_countries.py (async)."""

import json

import pytest

from application import addresses_structures as addresses_structures_module
from application.addresses_countries import (
    batch_set_country_by_filter,
    batch_set_country_by_ids,
    propagate_countries_to_publications,
    propagate_countries_to_similar,
    set_country,
)
from application.addresses_structures import (
    batch_review_structure_link,
    review_structure_link,
    unassign_manual_structure,
)
from infrastructure.db.queries.perimeter import PgAsyncPerimeterQueries
from infrastructure.repositories import async_address_repository, async_authorship_repository


@pytest.fixture
def repo(async_db):
    return async_address_repository(async_db)


@pytest.fixture
def perimeter_queries():
    return PgAsyncPerimeterQueries()


@pytest.fixture
def authorship_repo(async_db):
    return async_authorship_repository(async_db)


# ── Helpers ────────────────────────────────────────────────────────


async def _create_structure(db, code="UCA", name="UCA", structure_type="universite"):
    await db.execute(
        """
        INSERT INTO structures (code, name, structure_type)
        VALUES (%s, %s, %s::structure_type)
        RETURNING id
        """,
        (code, name, structure_type),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_perimeter(db, code, structure_ids):
    await db.execute(
        "INSERT INTO perimeters (code, name, structure_ids) VALUES (%s, %s, %s)",
        (code, code.upper(), structure_ids),
    )


async def _set_config(db, key, value):
    await db.execute(
        "INSERT INTO config (key, value) VALUES (%s, %s::jsonb)",
        (key, json.dumps(value)),
    )


async def _create_address(db, raw_text="Université Clermont Auvergne"):
    await db.execute(
        """
        INSERT INTO addresses (raw_text, normalized_text)
        VALUES (%s, lower(%s))
        RETURNING id
        """,
        (raw_text, raw_text),
    )
    row = await db.fetchone()
    return row["id"]


async def _insert_address_structure(
    db, address_id, structure_id, *, is_confirmed=None, matched_form_id=None
):
    await db.execute(
        """
        INSERT INTO address_structures (address_id, structure_id, is_confirmed, matched_form_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (address_id, structure_id, is_confirmed, matched_form_id),
    )
    row = await db.fetchone()
    return row["id"]


async def _setup_uca_perimeter(db):
    """Monte un périmètre UCA minimal pour que propagate_uca_for_addresses marche."""
    uca = await _create_structure(db, code="UCA", name="UCA", structure_type="universite")
    await _create_perimeter(db, "uca", [uca])
    await _set_config(db, "perimeter_persons", "uca")
    return uca


async def _get_link(db, address_id, structure_id):
    await db.execute(
        """
        SELECT is_confirmed, matched_form_id FROM address_structures
        WHERE address_id = %s AND structure_id = %s
        """,
        (address_id, structure_id),
    )
    return await db.fetchone()


# ── review_structure_link ──────────────────────────────────────────


class TestReviewStructureLink:
    async def test_confirm_creates_link_if_absent(
        self, async_db, repo, authorship_repo, perimeter_queries
    ):
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)

        await review_structure_link(
            async_db,
            addr,
            uca,
            True,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        link = await _get_link(async_db, addr, uca)
        assert link is not None
        assert link["is_confirmed"] is True

    async def test_reject_creates_link_if_absent(
        self, async_db, repo, authorship_repo, perimeter_queries
    ):
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)

        await review_structure_link(
            async_db,
            addr,
            uca,
            False,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        link = await _get_link(async_db, addr, uca)
        assert link["is_confirmed"] is False

    async def test_confirm_updates_existing_link(
        self, async_db, repo, authorship_repo, perimeter_queries
    ):
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        await _insert_address_structure(async_db, addr, uca, is_confirmed=False)

        await review_structure_link(
            async_db,
            addr,
            uca,
            True,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert (await _get_link(async_db, addr, uca))["is_confirmed"] is True

    async def test_reset_deletes_manual_link(
        self, async_db, repo, authorship_repo, perimeter_queries
    ):
        """Reset supprime le lien manuel (matched_form_id IS NULL)."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        await _insert_address_structure(async_db, addr, uca, is_confirmed=True)  # manuel

        await review_structure_link(
            async_db,
            addr,
            uca,
            None,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert await _get_link(async_db, addr, uca) is None

    async def test_reset_preserves_auto_link_but_clears_confirmation(
        self, async_db, repo, authorship_repo, perimeter_queries
    ):
        """Reset sur un lien auto-détecté : le lien reste, is_confirmed → NULL."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        await async_db.execute(
            """
            INSERT INTO structure_name_forms (structure_id, form_text)
            VALUES (%s, 'uca') RETURNING id
            """,
            (uca,),
        )
        form_id = (await async_db.fetchone())["id"]
        await _insert_address_structure(
            async_db, addr, uca, is_confirmed=False, matched_form_id=form_id
        )

        await review_structure_link(
            async_db,
            addr,
            uca,
            None,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        link = await _get_link(async_db, addr, uca)
        assert link is not None  # lien auto préservé
        assert link["is_confirmed"] is None  # confirmation nettoyée
        assert link["matched_form_id"] == form_id


# ── batch_review_structure_link ────────────────────────────────────


class TestBatchReviewStructureLink:
    async def test_empty_returns_zero(self, async_db, repo, authorship_repo, perimeter_queries):
        uca = await _setup_uca_perimeter(async_db)
        assert (
            await batch_review_structure_link(
                async_db,
                [],
                uca,
                True,
                repo=repo,
                authorship_repo=authorship_repo,
                perimeter_queries=perimeter_queries,
            )
            == 0
        )

    async def test_confirm_upserts_lot(self, async_db, repo, authorship_repo, perimeter_queries):
        uca = await _setup_uca_perimeter(async_db)
        addrs = [await _create_address(async_db, raw_text=f"adr{i}") for i in range(3)]

        updated = await batch_review_structure_link(
            async_db,
            addrs,
            uca,
            True,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert updated == 3
        for aid in addrs:
            assert (await _get_link(async_db, aid, uca))["is_confirmed"] is True

    async def test_reject_lot(self, async_db, repo, authorship_repo, perimeter_queries):
        uca = await _setup_uca_perimeter(async_db)
        addrs = [await _create_address(async_db, raw_text=f"x{i}") for i in range(2)]

        await batch_review_structure_link(
            async_db,
            addrs,
            uca,
            False,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        for aid in addrs:
            assert (await _get_link(async_db, aid, uca))["is_confirmed"] is False

    async def test_reset_lot(self, async_db, repo, authorship_repo, perimeter_queries):
        uca = await _setup_uca_perimeter(async_db)
        a1 = await _create_address(async_db, raw_text="a1")
        a2 = await _create_address(async_db, raw_text="a2")
        await _insert_address_structure(async_db, a1, uca, is_confirmed=True)
        await _insert_address_structure(async_db, a2, uca, is_confirmed=False)

        await batch_review_structure_link(
            async_db,
            [a1, a2],
            uca,
            None,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        # Les 2 liens manuels ont été supprimés
        assert await _get_link(async_db, a1, uca) is None
        assert await _get_link(async_db, a2, uca) is None


# ── unassign_manual_structure ───────────────────────────────────────


class TestUnassignManualStructure:
    async def test_deletes_manual_link(self, async_db, repo, authorship_repo, perimeter_queries):
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        await _insert_address_structure(async_db, addr, uca, is_confirmed=True)  # manuel

        assert (
            await unassign_manual_structure(
                async_db,
                addr,
                uca,
                repo=repo,
                authorship_repo=authorship_repo,
                perimeter_queries=perimeter_queries,
            )
            is True
        )
        assert await _get_link(async_db, addr, uca) is None

    async def test_preserves_auto_link(self, async_db, repo, authorship_repo, perimeter_queries):
        """Un lien auto-détecté (matched_form_id non NULL) n'est pas supprimé."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        await async_db.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text) VALUES (%s, 'uca') RETURNING id",
            (uca,),
        )
        form_id = (await async_db.fetchone())["id"]
        await _insert_address_structure(
            async_db, addr, uca, is_confirmed=True, matched_form_id=form_id
        )

        assert (
            await unassign_manual_structure(
                async_db,
                addr,
                uca,
                repo=repo,
                authorship_repo=authorship_repo,
                perimeter_queries=perimeter_queries,
            )
            is False
        )  # rien supprimé
        link = await _get_link(async_db, addr, uca)
        assert link is not None  # lien auto préservé
        assert link["is_confirmed"] is True  # is_confirmed NON touché

    async def test_returns_false_if_no_link(
        self, async_db, repo, authorship_repo, perimeter_queries
    ):
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        assert (
            await unassign_manual_structure(
                async_db,
                addr,
                uca,
                repo=repo,
                authorship_repo=authorship_repo,
                perimeter_queries=perimeter_queries,
            )
            is False
        )


# ── set_country ─────────────────────────────────────────────────────


async def _ensure_country(db, code, name="Test"):
    await db.execute(
        "INSERT INTO countries (code, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (code, name),
    )


async def _get_countries(db, address_id):
    await db.execute("SELECT countries FROM addresses WHERE id = %s", (address_id,))
    row = await db.fetchone()
    return row["countries"]


class TestSetCountry:
    async def test_assigns_countries(self, async_db, repo):
        await _ensure_country(async_db, "FR")
        addr = await _create_address(async_db)
        affected = await set_country(async_db, addr, ["FR"], repo=repo)
        assert affected == [addr]
        assert await _get_countries(async_db, addr) == ["FR"]

    async def test_none_clears_countries(self, async_db, repo):
        await _ensure_country(async_db, "FR")
        addr = await _create_address(async_db)
        await set_country(async_db, addr, ["FR"], repo=repo)
        await set_country(async_db, addr, None, repo=repo)
        assert await _get_countries(async_db, addr) is None

    async def test_propagates_to_same_normalized_text(self, async_db, repo):
        """Les adresses avec même normalized_text héritent des countries."""
        await _ensure_country(async_db, "FR")
        a1 = await _create_address(async_db, raw_text="UCA A")
        a2 = await _create_address(async_db, raw_text="UCA B")
        # Forcer le même normalized_text (simule le pipeline de normalisation)
        await async_db.execute(
            "UPDATE addresses SET normalized_text = 'universite clermont auvergne' WHERE id IN (%s, %s)",
            (a1, a2),
        )
        await set_country(async_db, a1, ["FR"], repo=repo)
        assert await _get_countries(async_db, a1) == ["FR"]
        assert await _get_countries(async_db, a2) == ["FR"]  # propagé

    async def test_no_propagation_on_short_normalized(self, async_db, repo):
        """Pas de propagation si normalized_text < 5 chars."""
        await _ensure_country(async_db, "FR")
        a1 = await _create_address(async_db, raw_text="addr short A")
        a2 = await _create_address(async_db, raw_text="addr short B")
        await async_db.execute(
            "UPDATE addresses SET normalized_text = 'abc' WHERE id IN (%s, %s)",
            (a1, a2),
        )
        await set_country(async_db, a1, ["FR"], repo=repo)
        assert await _get_countries(async_db, a2) is None


# ── batch_set_country_by_ids ────────────────────────────────────────


class TestBatchSetCountryByIds:
    async def test_adds_to_empty_countries(self, async_db, repo):
        await _ensure_country(async_db, "FR")
        addrs = [await _create_address(async_db, raw_text=f"a{i}") for i in range(3)]
        modified = await batch_set_country_by_ids(async_db, "FR", addrs, repo=repo)
        assert set(modified) == set(addrs)
        for a in addrs:
            assert await _get_countries(async_db, a) == ["FR"]

    async def test_appends_to_existing_countries(self, async_db, repo):
        await _ensure_country(async_db, "FR")
        await _ensure_country(async_db, "US")
        addr = await _create_address(async_db)
        await set_country(async_db, addr, ["FR"], repo=repo)
        await batch_set_country_by_ids(async_db, "US", [addr], repo=repo)
        countries = await _get_countries(async_db, addr)
        assert "FR" in countries and "US" in countries

    async def test_idempotent_if_already_present(self, async_db, repo):
        await _ensure_country(async_db, "FR")
        addr = await _create_address(async_db)
        await set_country(async_db, addr, ["FR"], repo=repo)
        await batch_set_country_by_ids(async_db, "FR", [addr], repo=repo)
        assert await _get_countries(async_db, addr) == ["FR"]  # pas de doublon


# ── batch_set_country_by_filter ─────────────────────────────────────


class TestBatchSetCountryByFilter:
    async def test_filter_by_search(self, async_db, repo):
        await _ensure_country(async_db, "FR")
        match = await _create_address(async_db, raw_text="Université Clermont")
        other = await _create_address(async_db, raw_text="MIT Boston")
        modified = await batch_set_country_by_filter(async_db, "FR", search="Clermont", repo=repo)
        assert match in modified
        assert other not in modified

    async def test_filter_has_country_no(self, async_db, repo):
        await _ensure_country(async_db, "FR")
        await _ensure_country(async_db, "US")
        addr_no = await _create_address(async_db, raw_text="sans pays")
        addr_yes = await _create_address(async_db, raw_text="avec pays")
        await set_country(async_db, addr_yes, ["US"], repo=repo)
        modified = await batch_set_country_by_filter(async_db, "FR", has_country="no", repo=repo)
        assert addr_no in modified
        assert addr_yes not in modified


# ── propagate_countries_to_similar ──────────────────────────────────


class TestPropagateCountriesToSimilar:
    async def test_propagates_divergent_values(self, async_db, repo):
        """Deux adresses de même normalized_text avec countries différents :
        la 2e reçoit les countries de la 1ère."""
        await _ensure_country(async_db, "FR")
        a1 = await _create_address(async_db, raw_text="UCA AA")
        a2 = await _create_address(async_db, raw_text="UCA BB")
        await async_db.execute(
            "UPDATE addresses SET normalized_text = 'universite clermont auvergne' WHERE id IN (%s, %s)",
            (a1, a2),
        )
        # a1 a FR, a2 n'a rien
        await async_db.execute("UPDATE addresses SET countries = %s WHERE id = %s", (["FR"], a1))

        propagated = await propagate_countries_to_similar(async_db, repo=repo)

        assert a2 in propagated
        assert await _get_countries(async_db, a2) == ["FR"]


# ── propagate_countries_to_publications ─────────────────────────────


class TestPropagateCountriesToPublications:
    async def test_empty_is_noop(self, async_db, repo):
        await propagate_countries_to_publications(async_db, [], repo=repo)  # pas d'exception

    async def test_propagates_to_source_pub_and_publication(self, async_db, repo):
        """Test d'intégration minimal : une adresse avec countries liée à
        une source_authorship, le pays doit remonter jusqu'à publications.countries."""
        await _ensure_country(async_db, "FR")
        await async_db.execute(
            "INSERT INTO publications (title, pub_year) VALUES ('Test', 2024) RETURNING id"
        )
        pub_id = (await async_db.fetchone())["id"]
        await async_db.execute(
            """
            INSERT INTO source_publications (source, source_id, title, publication_id)
            VALUES ('hal', 'h-1', 'Test', %s) RETURNING id
            """,
            (pub_id,),
        )
        sp_id = (await async_db.fetchone())["id"]
        await async_db.execute(
            """
            INSERT INTO source_persons (source, source_id, full_name)
            VALUES ('hal', 'p-1', 'J D') RETURNING id
            """
        )
        sperson_id = (await async_db.fetchone())["id"]
        await async_db.execute(
            """
            INSERT INTO source_authorships (source, source_publication_id, source_person_id)
            VALUES ('hal', %s, %s) RETURNING id
            """,
            (sp_id, sperson_id),
        )
        sa_id = (await async_db.fetchone())["id"]
        addr = await _create_address(async_db)
        await async_db.execute("UPDATE addresses SET countries = %s WHERE id = %s", (["FR"], addr))
        await async_db.execute(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) VALUES (%s, %s)",
            (sa_id, addr),
        )

        await propagate_countries_to_publications(async_db, [addr], repo=repo)

        # source_publications.countries mis à jour
        await async_db.execute("SELECT countries FROM source_publications WHERE id = %s", (sp_id,))
        assert (await async_db.fetchone())["countries"] == ["FR"]
        # publications.countries mis à jour
        await async_db.execute("SELECT countries FROM publications WHERE id = %s", (pub_id,))
        assert (await async_db.fetchone())["countries"] == ["FR"]


# ── No-op skip (éviter les cascades massives inutiles) ────────────


class TestPropagationSkipsNoOp:
    """Vérifie que la propagation UCA est skippée quand le changement de
    is_confirmed n'affecte pas le calcul in_perimeter.

    Règle : contribue au périmètre ssi le lien existe ET
    is_confirmed IS DISTINCT FROM FALSE (NULL ou TRUE).
    Donc NULL ↔ TRUE ne changent rien, seuls les passages par FALSE comptent.
    """

    @pytest.fixture
    def spy_propagate(self, monkeypatch):
        """Remplace propagate_uca_for_addresses par un spy qui compte les appels."""
        calls: list[list[int]] = []

        async def fake_propagate(cur, address_ids, **kw):  # noqa: ARG001
            calls.append(list(address_ids))

        monkeypatch.setattr(
            addresses_structures_module, "propagate_uca_for_addresses", fake_propagate
        )
        return calls

    async def test_confirm_auto_detected_skips_propagation(
        self, async_db, repo, authorship_repo, perimeter_queries, spy_propagate
    ):
        """Click Relier sur une adresse auto-détectée (NULL → TRUE) = no-op."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        # Lien auto-détecté, is_confirmed=NULL (cas reproducteur du bug initial)
        await async_db.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text) VALUES (%s, 'uca') RETURNING id",
            (uca,),
        )
        form_id = (await async_db.fetchone())["id"]
        await _insert_address_structure(
            async_db, addr, uca, is_confirmed=None, matched_form_id=form_id
        )

        await review_structure_link(
            async_db,
            addr,
            uca,
            True,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert spy_propagate == []
        # Le lien a bien été mis à jour
        assert (await _get_link(async_db, addr, uca))["is_confirmed"] is True

    async def test_reconfirm_already_confirmed_skips_propagation(
        self, async_db, repo, authorship_repo, perimeter_queries, spy_propagate
    ):
        """Cliquer Relier sur un lien déjà TRUE = no-op."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        await _insert_address_structure(async_db, addr, uca, is_confirmed=True)

        await review_structure_link(
            async_db,
            addr,
            uca,
            True,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert spy_propagate == []

    async def test_confirm_rejected_triggers_propagation(
        self, async_db, repo, authorship_repo, perimeter_queries, spy_propagate
    ):
        """FALSE → TRUE : vrai changement, propagation attendue."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        await _insert_address_structure(async_db, addr, uca, is_confirmed=False)

        await review_structure_link(
            async_db,
            addr,
            uca,
            True,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert spy_propagate == [[addr]]

    async def test_reject_confirmed_triggers_propagation(
        self, async_db, repo, authorship_repo, perimeter_queries, spy_propagate
    ):
        """TRUE → FALSE : vrai changement (sort du périmètre), propagation."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        await _insert_address_structure(async_db, addr, uca, is_confirmed=True)

        await review_structure_link(
            async_db,
            addr,
            uca,
            False,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert spy_propagate == [[addr]]

    async def test_reject_absent_creates_and_triggers_propagation(
        self, async_db, repo, authorship_repo, perimeter_queries, spy_propagate
    ):
        """Pas de lien → FALSE : pas de contribution avant ni après, no-op."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)

        await review_structure_link(
            async_db,
            addr,
            uca,
            False,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        # Avant = pas de lien (ne contribue pas), après = lien FALSE (ne contribue pas)
        # → no-op, skip propagation
        assert spy_propagate == []

    async def test_confirm_absent_creates_and_triggers_propagation(
        self, async_db, repo, authorship_repo, perimeter_queries, spy_propagate
    ):
        """Pas de lien → TRUE : contribue maintenant, propagation attendue."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)

        await review_structure_link(
            async_db,
            addr,
            uca,
            True,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert spy_propagate == [[addr]]

    async def test_batch_only_propagates_changed(
        self, async_db, repo, authorship_repo, perimeter_queries, spy_propagate
    ):
        """Batch mixte : certaines adresses changent, d'autres non.
        Propagation restreinte aux adresses effectivement impactées."""
        uca = await _setup_uca_perimeter(async_db)
        # a1 : auto-détectée NULL → TRUE (no-op)
        # a2 : rejetée FALSE → TRUE (changement)
        # a3 : pas de lien → TRUE (changement)
        a1 = await _create_address(async_db, raw_text="a1")
        a2 = await _create_address(async_db, raw_text="a2")
        a3 = await _create_address(async_db, raw_text="a3")
        await async_db.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text) VALUES (%s, 'uca2') RETURNING id",
            (uca,),
        )
        form_id = (await async_db.fetchone())["id"]
        await _insert_address_structure(
            async_db, a1, uca, is_confirmed=None, matched_form_id=form_id
        )
        await _insert_address_structure(async_db, a2, uca, is_confirmed=False)

        await batch_review_structure_link(
            async_db,
            [a1, a2, a3],
            uca,
            True,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert len(spy_propagate) == 1
        # a1 inchangée (déjà contribuait), a2 et a3 nouvellement contribuent
        assert set(spy_propagate[0]) == {a2, a3}

    async def test_unassign_nonexistent_skips_propagation(
        self, async_db, repo, authorship_repo, perimeter_queries, spy_propagate
    ):
        """Unassign sur un lien inexistant : rien à faire, skip."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)

        deleted = await unassign_manual_structure(
            async_db,
            addr,
            uca,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert deleted is False
        assert spy_propagate == []

    async def test_unassign_rejected_manual_skips_propagation(
        self, async_db, repo, authorship_repo, perimeter_queries, spy_propagate
    ):
        """Unassign d'un lien manuel FALSE : avant ne contribue pas, après
        non plus (lien disparu) → skip."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        await _insert_address_structure(async_db, addr, uca, is_confirmed=False)

        deleted = await unassign_manual_structure(
            async_db,
            addr,
            uca,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert deleted is True
        assert spy_propagate == []

    async def test_unassign_confirmed_manual_triggers_propagation(
        self, async_db, repo, authorship_repo, perimeter_queries, spy_propagate
    ):
        """Unassign d'un lien manuel TRUE : contribuait, ne contribue plus → propagation."""
        uca = await _setup_uca_perimeter(async_db)
        addr = await _create_address(async_db)
        await _insert_address_structure(async_db, addr, uca, is_confirmed=True)

        deleted = await unassign_manual_structure(
            async_db,
            addr,
            uca,
            repo=repo,
            authorship_repo=authorship_repo,
            perimeter_queries=perimeter_queries,
        )

        assert deleted is True
        assert spy_propagate == [[addr]]
