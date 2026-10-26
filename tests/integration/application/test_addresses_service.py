"""Tests de caractérisation pour application/addresses_structures.py
et application/addresses_countries.py."""

import pytest
from sqlalchemy import text

from application.services.addresses.countries import (
    batch_set_country_by_filter,
    batch_set_country_by_ids,
    propagate_countries_to_publications,
    set_country,
)
from application.services.addresses.structure_links import (
    batch_review_structure_link,
    review_structure_link,
)
from domain.country_detection import CountryDetectionMethod
from domain.errors import NotFoundError, ValidationError
from infrastructure.db.queues import Queue
from infrastructure.repositories import address_repository, contribution_repository
from pipeline.transformation.countries.refresh_publication_countries import CountryRecompute
from pipeline.transformation.countries.store import CountryCandidatesStore
from pipeline.transformation.structures.perimeter import PerimeterStructures
from tests.integration.helpers.addresses import (
    ensure_country,
    insert_address,
    insert_address_structure,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import queued
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)
from tests.integration.helpers.structures import (
    insert_persons_perimeter,
    insert_structure_name_form,
)


@pytest.fixture
def repo(sa_sync_conn):
    return address_repository(sa_sync_conn)


@pytest.fixture
def perimeter_structures(sa_sync_conn):
    return PerimeterStructures(sa_sync_conn)


@pytest.fixture
def contribution_repo(sa_sync_conn):
    return contribution_repository(sa_sync_conn)


# ── Helpers (SQLAlchemy text, paramstyle nommé) ───────────────────


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
        uca = insert_persons_perimeter(sa_sync_conn)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")

        review_structure_link(addr, uca, True, repo=repo)

        link = _get_link(sa_sync_conn, addr, uca)
        assert link is not None
        assert link["is_confirmed"] is True

    def test_reject_creates_link_if_absent(self, sa_sync_conn, repo):
        uca = insert_persons_perimeter(sa_sync_conn)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")

        review_structure_link(addr, uca, False, repo=repo)

        link = _get_link(sa_sync_conn, addr, uca)
        assert link["is_confirmed"] is False

    def test_confirm_updates_existing_link(self, sa_sync_conn, repo):
        uca = insert_persons_perimeter(sa_sync_conn)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        insert_address_structure(sa_sync_conn, addr, structure_id=uca, is_confirmed=False)

        review_structure_link(addr, uca, True, repo=repo)

        assert _get_link(sa_sync_conn, addr, uca)["is_confirmed"] is True

    def test_reset_deletes_manual_link(self, sa_sync_conn, repo):
        """Reset supprime le lien manuel (matched_form_id IS NULL)."""
        uca = insert_persons_perimeter(sa_sync_conn)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        insert_address_structure(sa_sync_conn, addr, structure_id=uca, is_confirmed=True)  # manuel

        review_structure_link(addr, uca, None, repo=repo)

        assert _get_link(sa_sync_conn, addr, uca) is None

    def test_reset_preserves_auto_link_but_clears_confirmation(self, sa_sync_conn, repo):
        """Reset sur un lien auto-détecté : le lien reste, is_confirmed → NULL."""
        uca = insert_persons_perimeter(sa_sync_conn)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        form_id = insert_structure_name_form(sa_sync_conn, uca, form_text="uca")
        insert_address_structure(
            sa_sync_conn, addr, structure_id=uca, is_confirmed=False, matched_form_id=form_id
        )

        review_structure_link(addr, uca, None, repo=repo)

        link = _get_link(sa_sync_conn, addr, uca)
        assert link is not None  # lien auto préservé
        assert link["is_confirmed"] is None  # confirmation nettoyée
        assert link["matched_form_id"] == form_id


# ── batch_review_structure_link ────────────────────────────────────


class TestBatchReviewStructureLink:
    def test_empty_returns_zero(self, sa_sync_conn, repo):
        uca = insert_persons_perimeter(sa_sync_conn)
        updated, changed = batch_review_structure_link([], uca, True, repo=repo)
        assert updated == 0
        assert changed == []

    def test_confirm_upserts_lot(self, sa_sync_conn, repo):
        uca = insert_persons_perimeter(sa_sync_conn)
        addrs = [insert_address(sa_sync_conn, f"adr{i}") for i in range(3)]

        updated, _ = batch_review_structure_link(addrs, uca, True, repo=repo)

        assert updated == 3
        for aid in addrs:
            assert _get_link(sa_sync_conn, aid, uca)["is_confirmed"] is True

    def test_reject_lot(self, sa_sync_conn, repo):
        uca = insert_persons_perimeter(sa_sync_conn)
        addrs = [insert_address(sa_sync_conn, f"x{i}") for i in range(2)]

        batch_review_structure_link(addrs, uca, False, repo=repo)

        for aid in addrs:
            assert _get_link(sa_sync_conn, aid, uca)["is_confirmed"] is False

    def test_reset_lot(self, sa_sync_conn, repo):
        uca = insert_persons_perimeter(sa_sync_conn)
        a1 = insert_address(sa_sync_conn, "a1")
        a2 = insert_address(sa_sync_conn, "a2")
        insert_address_structure(sa_sync_conn, a1, structure_id=uca, is_confirmed=True)
        insert_address_structure(sa_sync_conn, a2, structure_id=uca, is_confirmed=False)

        updated, _ = batch_review_structure_link([a1, a2], uca, None, repo=repo)

        # Les 2 liens manuels sont supprimés, et comptés parmi les adresses touchées.
        assert updated == 2
        assert _get_link(sa_sync_conn, a1, uca) is None
        assert _get_link(sa_sync_conn, a2, uca) is None


# ── set_country ─────────────────────────────────────────────────────


def _get_countries(conn, address_id):
    result = conn.execute(
        text("SELECT countries FROM addresses WHERE id = :id"), {"id": address_id}
    )
    row = result.first()
    return row.countries if row else None


class TestSetCountry:
    def test_assigns_countries(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        affected = set_country(
            addr, ["FR"], repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
        )
        assert affected == [addr]
        assert _get_countries(sa_sync_conn, addr) == ["FR"]

    def test_manual_country_wins_over_automatic_candidates(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        ensure_country(sa_sync_conn, "DE")
        addr = insert_address(
            sa_sync_conn, "Department of Neurology, University of Mainz (Denmark)"
        )
        CountryCandidatesStore(sa_sync_conn).add(
            CountryDetectionMethod.COUNTRY_NAME, [(addr, ["FR"])]
        )

        set_country(addr, ["DE"], repo=repo, country_recompute=CountryRecompute(sa_sync_conn))

        assert _get_countries(sa_sync_conn, addr) == ["DE"]

    def test_raises_on_unknown_country(self, sa_sync_conn, repo):
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        with pytest.raises(ValidationError, match="Code pays inconnu"):
            set_country(addr, ["ZZ"], repo=repo, country_recompute=CountryRecompute(sa_sync_conn))
        assert _get_countries(sa_sync_conn, addr) is None

    def test_raises_on_unknown_address(self, sa_sync_conn, repo):
        """L'`UPDATE` n'apparie aucune ligne : sans cette garde, l'API répondrait 200 sans rien faire."""
        ensure_country(sa_sync_conn, "FR")
        with pytest.raises(NotFoundError):
            set_country(999999, ["FR"], repo=repo, country_recompute=CountryRecompute(sa_sync_conn))

    def test_raises_on_one_unknown_among_known(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        with pytest.raises(ValidationError, match="ZZ"):
            set_country(
                addr, ["FR", "ZZ"], repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
            )
        assert _get_countries(sa_sync_conn, addr) is None

    def test_none_returns_the_address_to_automatic_candidates(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        ensure_country(sa_sync_conn, "DE")
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne, France")
        CountryCandidatesStore(sa_sync_conn).add(
            CountryDetectionMethod.COUNTRY_NAME, [(addr, ["FR"])]
        )
        set_country(addr, ["DE"], repo=repo, country_recompute=CountryRecompute(sa_sync_conn))

        set_country(addr, None, repo=repo, country_recompute=CountryRecompute(sa_sync_conn))

        assert _get_countries(sa_sync_conn, addr) == ["FR"]


# ── batch_set_country_by_ids ────────────────────────────────────────


class TestBatchSetCountryByIds:
    def test_adds_to_empty_countries(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        addrs = [insert_address(sa_sync_conn, f"a{i}") for i in range(3)]
        modified = batch_set_country_by_ids(
            "FR", addrs, repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
        )
        assert set(modified) == set(addrs)
        for a in addrs:
            assert _get_countries(sa_sync_conn, a) == ["FR"]

    def test_raises_on_unknown_country(self, sa_sync_conn, repo):
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        with pytest.raises(ValidationError, match="Code pays inconnu"):
            batch_set_country_by_ids(
                "ZZ", [addr], repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
            )

    def test_raises_on_empty_country_code(self, sa_sync_conn, repo):
        """La chaîne vide ne figure pas au référentiel : le contrôle référentiel la couvre."""
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        with pytest.raises(ValidationError, match="Code pays inconnu"):
            batch_set_country_by_ids(
                "", [addr], repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
            )

    def test_appends_to_existing_countries(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        ensure_country(sa_sync_conn, "US")
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        set_country(addr, ["FR"], repo=repo, country_recompute=CountryRecompute(sa_sync_conn))
        batch_set_country_by_ids(
            "US", [addr], repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
        )
        assert _get_countries(sa_sync_conn, addr) == ["FR", "US"]

    def test_idempotent_if_already_present(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        set_country(addr, ["FR"], repo=repo, country_recompute=CountryRecompute(sa_sync_conn))
        batch_set_country_by_ids(
            "FR", [addr], repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
        )
        assert _get_countries(sa_sync_conn, addr) == ["FR"]  # pas de doublon


# ── batch_set_country_by_filter ─────────────────────────────────────


class TestBatchSetCountryByFilter:
    def test_filter_by_search(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        match = insert_address(sa_sync_conn, "Université Clermont")
        other = insert_address(sa_sync_conn, "MIT Boston")
        modified = batch_set_country_by_filter(
            "FR", search="Clermont", repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
        )
        assert match in modified
        assert other not in modified

    def test_raises_on_unknown_country(self, sa_sync_conn, repo):
        insert_address(sa_sync_conn, "Université Clermont")
        with pytest.raises(ValidationError, match="Code pays inconnu"):
            batch_set_country_by_filter(
                "ZZ", search="Clermont", repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
            )

    def test_filter_has_country_no(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        ensure_country(sa_sync_conn, "US")
        addr_no = insert_address(sa_sync_conn, "sans pays")
        addr_yes = insert_address(sa_sync_conn, "avec pays")
        set_country(addr_yes, ["US"], repo=repo, country_recompute=CountryRecompute(sa_sync_conn))
        modified = batch_set_country_by_filter(
            "FR", has_country=False, repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
        )
        assert addr_no in modified
        assert addr_yes not in modified

    def test_empty_filter_raises(self, sa_sync_conn, repo):
        """Aucun filtre → refus (garde-fou : ne pas viser toutes les adresses)."""
        with pytest.raises(ValidationError):
            batch_set_country_by_filter(
                "FR", repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
            )


def _marked(conn, address_id):
    return address_id in queued(conn, Queue.ADDRESS_COUNTRIES)


class TestAddressCountriesQueue:
    """Une saisie de pays marque l'adresse : le run suivant reprend la propagation vers les publications si le recalcul ciblé a échoué."""

    def test_set_country_marks_the_address(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")

        set_country(addr, ["FR"], repo=repo, country_recompute=CountryRecompute(sa_sync_conn))

        assert _marked(sa_sync_conn, addr)

    def test_batch_by_ids_marks_the_addresses(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")

        batch_set_country_by_ids(
            "FR", [addr], repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
        )

        assert _marked(sa_sync_conn, addr)

    def test_batch_by_filter_marks_the_addresses(self, sa_sync_conn, repo):
        ensure_country(sa_sync_conn, "FR")
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")

        batch_set_country_by_filter(
            "FR", search="Clermont", repo=repo, country_recompute=CountryRecompute(sa_sync_conn)
        )

        assert _marked(sa_sync_conn, addr)


# ── propagate_countries_to_publications ─────────────────────────────


class TestPropagateCountriesToPublications:
    def test_empty_is_noop(self, sa_sync_conn, repo):
        propagate_countries_to_publications(
            [], country_recompute=CountryRecompute(sa_sync_conn)
        )  # pas d'exception

    def test_propagates_to_source_record_and_publication(self, sa_sync_conn, repo):
        """Test d'intégration minimal : une adresse avec countries liée à
        une source_contribution, le pays doit remonter jusqu'à publications.countries."""
        ensure_country(sa_sync_conn, "FR")
        publication_id = insert_publication(
            sa_sync_conn, "Test", normalize_title=False, doc_type=None
        )
        source_record_id = insert_source_record(
            sa_sync_conn, publication_id, source_id="h-1", title="Test"
        )
        source_contribution_id = insert_source_contribution(sa_sync_conn, source_record_id)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        sa_sync_conn.execute(
            text("UPDATE addresses SET countries = :c WHERE id = :id"),
            {"c": ["FR"], "id": addr},
        )
        insert_source_contribution_address(sa_sync_conn, source_contribution_id, address_id=addr)

        propagate_countries_to_publications(
            [addr], country_recompute=CountryRecompute(sa_sync_conn)
        )

        # source_records.countries mis à jour
        source_record_countries = sa_sync_conn.execute(
            text("SELECT countries FROM source_records WHERE id = :id"), {"id": source_record_id}
        ).scalar_one()
        assert source_record_countries == ["FR"]
        # publications.countries mis à jour
        p_countries = sa_sync_conn.execute(
            text("SELECT countries FROM publications WHERE id = :id"), {"id": publication_id}
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
        uca = insert_persons_perimeter(sa_sync_conn)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        # Lien auto-détecté, is_confirmed=NULL (cas reproducteur du bug initial)
        form_id = insert_structure_name_form(sa_sync_conn, uca, form_text="uca")
        insert_address_structure(sa_sync_conn, addr, structure_id=uca, matched_form_id=form_id)

        changed = review_structure_link(addr, uca, True, repo=repo)

        assert changed == []
        # Le lien a bien été mis à jour
        assert _get_link(sa_sync_conn, addr, uca)["is_confirmed"] is True

    def test_reconfirm_already_confirmed_skips_propagation(self, sa_sync_conn, repo):
        """Cliquer Relier sur un lien déjà TRUE = no-op."""
        uca = insert_persons_perimeter(sa_sync_conn)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        insert_address_structure(sa_sync_conn, addr, structure_id=uca, is_confirmed=True)

        changed = review_structure_link(addr, uca, True, repo=repo)

        assert changed == []

    def test_confirm_rejected_triggers_propagation(self, sa_sync_conn, repo):
        """FALSE → TRUE : vrai changement, propagation attendue."""
        uca = insert_persons_perimeter(sa_sync_conn)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        insert_address_structure(sa_sync_conn, addr, structure_id=uca, is_confirmed=False)

        changed = review_structure_link(addr, uca, True, repo=repo)

        assert changed == [addr]

    def test_reject_confirmed_triggers_propagation(self, sa_sync_conn, repo):
        """TRUE → FALSE : vrai changement (sort du périmètre), propagation."""
        uca = insert_persons_perimeter(sa_sync_conn)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        insert_address_structure(sa_sync_conn, addr, structure_id=uca, is_confirmed=True)

        changed = review_structure_link(addr, uca, False, repo=repo)

        assert changed == [addr]

    def test_reject_absent_creates_and_triggers_propagation(self, sa_sync_conn, repo):
        """Pas de lien → FALSE : pas de contribution avant ni après, no-op."""
        uca = insert_persons_perimeter(sa_sync_conn)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")

        changed = review_structure_link(addr, uca, False, repo=repo)

        # Avant = pas de lien (ne contribue pas), après = lien FALSE (ne contribue pas)
        # → no-op
        assert changed == []

    def test_confirm_absent_creates_and_triggers_propagation(self, sa_sync_conn, repo):
        """Pas de lien → TRUE : contribue maintenant, propagation attendue."""
        uca = insert_persons_perimeter(sa_sync_conn)
        addr = insert_address(sa_sync_conn, "Université Clermont Auvergne")

        changed = review_structure_link(addr, uca, True, repo=repo)

        assert changed == [addr]

    def test_batch_only_propagates_changed(self, sa_sync_conn, repo):
        """Batch mixte : certaines adresses changent, d'autres non.
        `changed` restreint aux adresses effectivement impactées."""
        uca = insert_persons_perimeter(sa_sync_conn)
        # a1 : auto-détectée NULL → TRUE (no-op)
        # a2 : rejetée FALSE → TRUE (changement)
        # a3 : pas de lien → TRUE (changement)
        a1 = insert_address(sa_sync_conn, "a1")
        a2 = insert_address(sa_sync_conn, "a2")
        a3 = insert_address(sa_sync_conn, "a3")
        form_id = insert_structure_name_form(sa_sync_conn, uca, form_text="uca2")
        insert_address_structure(sa_sync_conn, a1, structure_id=uca, matched_form_id=form_id)
        insert_address_structure(sa_sync_conn, a2, structure_id=uca, is_confirmed=False)

        _, changed = batch_review_structure_link([a1, a2, a3], uca, True, repo=repo)

        # a1 inchangée (déjà contribuait), a2 et a3 nouvellement contribuent
        assert set(changed) == {a2, a3}
