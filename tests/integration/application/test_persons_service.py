"""Tests de caractérisation du service des personnes et de l'attribution des contributions orphelines : identifiants, formes de nom, détachement, fusion."""

from functools import partial

import pytest
from sqlalchemy import text

from domain.errors import (
    ConflictError,
    ContributionAlreadyAssignedError,
    NotFoundError,
    RejectedPairError,
    ValidationError,
)
from domain.merge import MergedEntity
from domain.persons.identifier_attribution import AttributionOutcome
from domain.persons.person import PersonExclusion
from infrastructure.db.queues import Queue
from infrastructure.repositories import (
    contribution_repository,
    person_repository,
)
from infrastructure.sql_fragments import REJECTED_PAIRS
from interfaces.api.deps import contribution_service as build_contribution_service, person_service
from tests.integration.helpers.alignment import (
    add_aligned_source_contribution,
    align_source_contributions,
    insert_person_contribution,
    set_perimeter_author_contribution,
)
from tests.integration.helpers.contributions import (
    insert_confirmed_source_contribution,
    insert_contribution,
)
from tests.integration.helpers.persons import (
    insert_person,
    insert_person_identifier,
    insert_person_name_form,
    insert_rejected_contribution,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import queued
from tests.integration.helpers.redirects import redirect_of
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.structures import insert_persons_perimeter

# Forme de nom de source HAL.
_hal_name_form = partial(insert_person_name_form, sources=["hal"])

# Personne « Dupont Jean » par défaut, normalisée par `lower`.
_person = partial(insert_person, last_name="Dupont", first_name="Jean", normalizer="lower")

# Contribution source de forme « jean dupont » par défaut.
_jean_dupont_source_contribution = partial(
    insert_source_contribution, author_name_normalized="jean dupont"
)

# Enregistrement source de titre « Test », d'identifiant « hal-1 » par défaut.
_source_record = partial(insert_source_record, source_id="hal-1", title="Test")


def _publication_evidence(conn, publication_id):
    return _scalar(
        conn,
        "SELECT perimeter_evidence::text[] FROM publications WHERE id = :p",
        p=publication_id,
    )


def _contribution_person(conn, contribution_id):
    return tuple(
        conn.execute(
            text("SELECT person_id, resolution_mode::text FROM contributions WHERE id = :g"),
            {"g": contribution_id},
        ).one()
    )


def _perimeter_contribution(conn, person_id, mode, *, source_id, **source_contribution):
    """Publication du périmètre dont le seule contribution d'auteur, rattachée à la personne par `mode`, réunit une contribution source décrite par `source_contribution`. Rend (publication, contribution)."""
    publication = insert_publication(conn, in_perimeter=True)
    source_record = _source_record(conn, publication, source_id=source_id)
    source_contribution_id = insert_source_contribution(conn, source_record, **source_contribution)
    contribution = align_source_contributions(
        conn, publication, [(source_contribution_id, source_record)]
    )
    set_perimeter_author_contribution(conn, contribution, person_id=person_id, mode=mode)
    return publication, contribution


def _orphan(conn, publication_id, *, source_id="hal-1", source="hal", **source_contribution):
    """Contribution orpheline : contribution d'auteur du périmètre sans personne, d'une contribution source « jean dupont » décrite par `source_contribution`. Rend (contribution, contribution source)."""
    source_record = _source_record(conn, publication_id, source=source, source_id=source_id)
    source_contribution_id = _jean_dupont_source_contribution(
        conn, source_record, source=source, **source_contribution
    )
    contribution = align_source_contributions(
        conn, publication_id, [(source_contribution_id, source_record)]
    )
    set_perimeter_author_contribution(conn, contribution)
    return contribution, source_contribution_id


def _pinned_to(conn, source_contribution_ids):
    """Personne à laquelle chaque contribution source est épinglée, `None` sans épinglage."""
    rows = dict(
        conn.execute(
            text(
                "SELECT source_contribution_id, person_id FROM confirmed_source_contributions"
                " WHERE source_contribution_id = ANY(:ids)"
            ),
            {"ids": source_contribution_ids},
        ).all()
    )
    return [rows.get(i) for i in source_contribution_ids]


@pytest.fixture
def repo(sa_sync_conn):
    return person_repository(sa_sync_conn)


@pytest.fixture
def contribution_repo(sa_sync_conn):
    return contribution_repository(sa_sync_conn)


@pytest.fixture
def service(sa_sync_conn):
    return person_service(sa_sync_conn)


@pytest.fixture
def contribution_service(sa_sync_conn):
    return build_contribution_service(sa_sync_conn)


# ── Helpers ─────────────────────────────────────────────────


def _scalar(conn, sql_text: str, **params):
    return conn.execute(text(sql_text), params).scalar_one_or_none()


# ── add_identifier ─────────────────────────────────────────────────


class TestAddIdentifier:
    def test_refuses_hal_person_id(self, sa_sync_conn, service):
        """`hal_person_id` est la référence d'un compte HAL, que l'extraction observe : personne ne l'attribue à la main."""
        person_id = _person(sa_sync_conn)
        with pytest.raises(ValidationError, match="id_type"):
            service.add_identifier(person_id, "hal_person_id", "12345")

    def test_raises_on_unknown_person(self, service):
        """Sans cette garde, l'identifiant venu d'un formulaire heurterait la clé étrangère."""
        with pytest.raises(NotFoundError):
            service.add_identifier(999999, "orcid", "0000-0001-2345-6789")

    def test_inserts_new(self, sa_sync_conn, service):
        person_id = _person(sa_sync_conn)
        result = service.add_identifier(person_id, "orcid", "0000-0001-2345-6789")
        assert result.outcome is AttributionOutcome.ADDED
        assert result.id_value == "0000-0001-2345-6789"
        status = _scalar(
            sa_sync_conn,
            "SELECT status FROM person_identifiers WHERE id_type='orcid' AND id_value=:v",
            v="0000-0001-2345-6789",
        )
        assert status == "pending"

    def test_reassigns_if_rejected(self, sa_sync_conn, service):
        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        service.add_identifier(p1, "orcid", "0000-0001-2345-6789")
        sa_sync_conn.execute(
            text(
                "UPDATE person_identifiers SET status='rejected' "
                "WHERE id_value='0000-0001-2345-6789'"
            )
        )
        result = service.add_identifier(p2, "orcid", "0000-0001-2345-6789")
        assert result.outcome is AttributionOutcome.REASSIGNED

        row = sa_sync_conn.execute(
            text(
                "SELECT person_id, status FROM person_identifiers "
                "WHERE id_value='0000-0001-2345-6789'"
            )
        ).one()
        assert row.person_id == p2
        assert row.status == "pending"

    def test_raises_when_pending_on_other_person(self, sa_sync_conn, service):
        """Si le même identifiant existe en 'pending' sur une autre personne,
        on lève `CannotAttributeConflict` (pour réattribuer, il faut d'abord
        passer le statut à 'rejected')."""
        import pytest

        from domain.errors import CannotAttributeConflict

        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        service.add_identifier(p1, "orcid", "0000-0001-2345-6789")

        with pytest.raises(CannotAttributeConflict):
            service.add_identifier(p2, "orcid", "0000-0001-2345-6789")

        # L'identifiant reste rattaché à p1.
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT person_id FROM person_identifiers WHERE id_value='0000-0001-2345-6789'",
            )
            == p1
        )

    def test_idempotent_on_same_person(self, sa_sync_conn, service):
        """Réappliquer add_identifier sur la même personne ne change rien."""
        p = _person(sa_sync_conn)
        service.add_identifier(p, "orcid", "0000-0001-2345-6789")
        result = service.add_identifier(p, "orcid", "0000-0001-2345-6789")  # no-op
        assert result.outcome is AttributionOutcome.ALREADY_EXISTS

        row = sa_sync_conn.execute(
            text(
                "SELECT person_id, status FROM person_identifiers "
                "WHERE id_value='0000-0001-2345-6789'"
            )
        ).one()
        assert row.person_id == p
        assert row.status == "pending"


class TestUpdateIdentifierStatus:
    def test_sets_status(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        ident_id = insert_person_identifier(
            sa_sync_conn, p, id_type="orcid", id_value="0000-0001", status="pending"
        )

        result = service.update_identifier_status(ident_id, "confirmed")

        assert result.status == "confirmed"
        assert result.propagated == 0

    def test_raises_not_found(self, sa_sync_conn, service):
        with pytest.raises(NotFoundError):
            service.update_identifier_status(999999, "confirmed")


class TestIdentifierStatusPropagation:
    """Une décision sur un identifiant s'étend aux identifiants `pending` de la même personne que portent les mêmes comptes HAL."""

    ORCID = "0000-0002-1633-8730"
    HAL_ACCOUNT = {"hal_person_id": 11581, "idhal": "nina-radosevic-robin", "orcid": ORCID}

    def _status(self, conn, ident_id):
        return _scalar(
            conn, "SELECT status::text FROM person_identifiers WHERE id = :i", i=ident_id
        )

    def _source_contribution(self, conn, person_id, source, source_id, identifiers, **kw):
        """Contribution source seule dans une contribution rattachée à la personne `person_id`."""
        source_record = _source_record(
            conn, insert_publication(conn), source=source, source_id=source_id
        )
        source_contribution = _jean_dupont_source_contribution(
            conn, source_record, source=source, identifiers=identifiers, **kw
        )
        insert_person_contribution(conn, source_contribution, person_id=person_id)

    def test_rejecting_an_orcid_rejects_its_hal_account(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        self._source_contribution(
            sa_sync_conn, p, "hal", "hal-a", {**self.HAL_ACCOUNT, "idref": "181370662"}
        )
        # Même compte, sans l'ORCID : son idHAL suit le compte.
        self._source_contribution(
            sa_sync_conn, p, "hal", "hal-b", {"hal_person_id": 11581, "idhal": "nr2"}
        )
        # ScanR associe l'ORCID à un autre IdRef : cette association n'entre pas dans la contribution.
        self._source_contribution(
            sa_sync_conn, p, "scanr", "scanr-a", {"orcid": self.ORCID, "idref": "999"}
        )
        orcid = insert_person_identifier(sa_sync_conn, p, id_type="orcid", id_value=self.ORCID)
        account = insert_person_identifier(
            sa_sync_conn, p, id_type="hal_person_id", id_value="11581"
        )
        idhal = insert_person_identifier(
            sa_sync_conn, p, id_type="idhal", id_value="nina-radosevic-robin"
        )
        idhal_2 = insert_person_identifier(sa_sync_conn, p, id_type="idhal", id_value="nr2")
        idref_confirmed = insert_person_identifier(
            sa_sync_conn, p, id_type="idref", id_value="181370662", status="confirmed"
        )
        idref_scanr = insert_person_identifier(sa_sync_conn, p, id_type="idref", id_value="999")

        result = service.update_identifier_status(orcid, "rejected")

        assert result.propagated == 3
        assert {self._status(sa_sync_conn, i) for i in (orcid, account, idhal, idhal_2)} == {
            "rejected"
        }
        assert self._status(sa_sync_conn, idref_confirmed) == "confirmed"
        assert self._status(sa_sync_conn, idref_scanr) == "pending"

    def test_other_persons_are_untouched(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        other = _person(sa_sync_conn, last_name="Autre", first_name="Personne")
        self._source_contribution(sa_sync_conn, p, "hal", "hal-a", self.HAL_ACCOUNT)
        self._source_contribution(sa_sync_conn, other, "hal", "hal-b", {"hal_person_id": 11581})
        orcid = insert_person_identifier(sa_sync_conn, p, id_type="orcid", id_value=self.ORCID)
        other_account = insert_person_identifier(
            sa_sync_conn, other, id_type="idhal", id_value="nina-radosevic-robin"
        )

        service.update_identifier_status(orcid, "confirmed")

        assert self._status(sa_sync_conn, other_account) == "pending"

    def test_neutralized_identifier_does_not_designate_the_account(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        self._source_contribution(
            sa_sync_conn,
            p,
            "hal",
            "hal-a",
            self.HAL_ACCOUNT,
            neutralized_identifiers={"orcid": "shared"},
        )
        orcid = insert_person_identifier(sa_sync_conn, p, id_type="orcid", id_value=self.ORCID)
        account = insert_person_identifier(
            sa_sync_conn, p, id_type="hal_person_id", id_value="11581"
        )

        assert service.update_identifier_status(orcid, "rejected").propagated == 0
        assert self._status(sa_sync_conn, account) == "pending"

    def test_back_to_pending_is_not_propagated(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        self._source_contribution(sa_sync_conn, p, "hal", "hal-a", self.HAL_ACCOUNT)
        orcid = insert_person_identifier(
            sa_sync_conn, p, id_type="orcid", id_value=self.ORCID, status="rejected"
        )
        insert_person_identifier(sa_sync_conn, p, id_type="hal_person_id", id_value="11581")

        assert service.update_identifier_status(orcid, "pending").propagated == 0


class TestIdentifierRejectionOnContributions:
    """Le rejet d'un identifiant détache de la personne les contributions que cet identifiant lui rattache."""

    ORCID = "0000-0002-1825-0097"

    def test_marks_contributions_resolved_by_the_identifier(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        identifiers = {"orcid": self.ORCID}
        by_orcid, orcid_contribution = _perimeter_contribution(
            sa_sync_conn, p, "orcid", source_id="hal-orcid", identifiers=identifiers
        )
        by_name, name_contribution = _perimeter_contribution(
            sa_sync_conn, p, "name", source_id="hal-name", identifiers=identifiers
        )
        manual, manual_contribution = _perimeter_contribution(
            sa_sync_conn, p, "manual", source_id="hal-manual", identifiers=identifiers
        )
        orcid = insert_person_identifier(sa_sync_conn, p, id_type="orcid", id_value=self.ORCID)

        service.update_identifier_status(orcid, "rejected")

        assert queued(sa_sync_conn, Queue.CONTRIBUTION_RESOLUTION) == {orcid_contribution}
        assert _contribution_person(sa_sync_conn, orcid_contribution) == (p, "orcid")

    def test_contribution_without_the_value_is_untouched(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        _, contribution = _perimeter_contribution(
            sa_sync_conn, p, "orcid", source_id="hal-other", identifiers={"orcid": "0000-0001"}
        )
        orcid = insert_person_identifier(sa_sync_conn, p, id_type="orcid", id_value=self.ORCID)

        service.update_identifier_status(orcid, "rejected")

        assert _contribution_person(sa_sync_conn, contribution) == (p, "orcid")

    def test_confirmation_leaves_contributions(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        _, contribution = _perimeter_contribution(
            sa_sync_conn, p, "orcid", source_id="hal-orcid", identifiers={"orcid": self.ORCID}
        )
        orcid = insert_person_identifier(sa_sync_conn, p, id_type="orcid", id_value=self.ORCID)

        service.update_identifier_status(orcid, "confirmed")

        assert _contribution_person(sa_sync_conn, contribution) == (p, "orcid")


class TestSetExclusion:
    def _exclusion(self, conn, p):
        return _scalar(conn, "SELECT exclusion::text FROM persons WHERE id = :p", p=p)

    def test_excludes(self, sa_sync_conn, repo, service):
        p = _person(sa_sync_conn)
        service.set_exclusion(p, PersonExclusion.OUT_OF_PERIMETER)
        assert self._exclusion(sa_sync_conn, p) == "out_of_perimeter"
        assert repo.find_by_id(p).exclusion is PersonExclusion.OUT_OF_PERIMETER

    def test_retains(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        service.set_exclusion(p, PersonExclusion.NOT_A_PERSON)
        service.set_exclusion(p, None)
        assert self._exclusion(sa_sync_conn, p) is None

    def test_raises_not_found(self, sa_sync_conn, service):
        with pytest.raises(NotFoundError):
            service.set_exclusion(999999, PersonExclusion.NOT_A_PERSON)

    def test_refreshes_in_perimeter_of_own_publications_only(self, sa_sync_conn, service):
        excluded = _person(sa_sync_conn, last_name="Exclue", first_name="Ée")
        other = _person(sa_sync_conn, last_name="Autre", first_name="Personne")
        alone = insert_publication(sa_sync_conn, "seule")
        shared = insert_publication(sa_sync_conn, "partagée")
        # Valeur périmée, hors des publications de la personne exclue : le recalcul ciblé la laisse en place.
        unrelated = insert_publication(sa_sync_conn, "sans lien")
        for publication, pid in (
            (alone, excluded),
            (shared, excluded),
            (shared, other),
            (unrelated, other),
        ):
            insert_contribution(
                sa_sync_conn, publication, person_id=pid, in_perimeter=True, roles=["author"]
            )
        sa_sync_conn.execute(
            text(
                "UPDATE publications SET perimeter_evidence = CASE WHEN id <> :u"
                " THEN '{address}'::perimeter_evidence[] ELSE '{}' END WHERE id IN (:a, :s, :u)"
            ),
            {"a": alone, "s": shared, "u": unrelated},
        )

        def flag(publication):
            return _scalar(
                sa_sync_conn, "SELECT in_perimeter FROM publications WHERE id = :p", p=publication
            )

        service.set_exclusion(excluded, PersonExclusion.OUT_OF_PERIMETER)
        assert (flag(alone), flag(shared), flag(unrelated)) == (False, True, False)

        service.set_exclusion(excluded, None)
        assert flag(alone) is True


class TestUpdateName:
    def test_updates_name_and_refreshes_forms(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        insert_person_name_form(sa_sync_conn, p, name_form="dupont jean", sources=["persons"])

        service.update_name(p, "Martin", "Sophie")

        row = sa_sync_conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.last_name == "Martin"
        assert row.first_name == "Sophie"

        row = sa_sync_conn.execute(
            text(
                "SELECT sources FROM person_name_forms "
                "WHERE name_form = 'sophie martin' AND person_id = :pid"
            ),
            {"pid": p},
        ).one()
        assert row.sources == ["persons"]

        # L'ancienne forme 'dupont jean' n'avait que la source 'persons'
        # pour ce pid : le renommage a supprimé la ligne entière.
        row = sa_sync_conn.execute(
            text(
                "SELECT 1 FROM person_name_forms "
                "WHERE name_form = 'dupont jean' AND person_id = :pid"
            ),
            {"pid": p},
        ).first()
        assert row is None

    def test_raises_not_found(self, sa_sync_conn, service):
        with pytest.raises(NotFoundError):
            service.update_name(999999, "X", "X")

    def test_strips_surrounding_space(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        service.update_name(p, "  Martin  ", "  Sophie  ")
        row = sa_sync_conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.last_name == "Martin"
        assert row.first_name == "Sophie"

    def test_raises_without_last_name(self, sa_sync_conn, service):
        """Effacer le patronyme retirerait à la personne les formes que seul son nom canonique porte."""
        p = _person(sa_sync_conn)
        with pytest.raises(ValidationError, match="nom est requis"):
            service.update_name(p, "", "Jean")

    def test_raises_on_blank_last_name(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        with pytest.raises(ValidationError, match="nom est requis"):
            service.update_name(p, "   ", "Jean")


# ── PersonRepository.create ───────────────────────────────────────────────────


class TestCreatePerson:
    def test_creates_and_computes_name_forms(self, sa_sync_conn, repo):
        p = repo.create("Dupont", "Jean")
        forms = {
            r.name_form
            for r in sa_sync_conn.execute(
                text("SELECT name_form FROM person_name_forms WHERE person_id = :p"), {"p": p}
            )
        }
        assert forms == {"jean dupont", "j dupont"}

    def test_strips_surrounding_space(self, sa_sync_conn, repo):
        p = repo.create("  Dupont  ", "  Jean  ")
        row = sa_sync_conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.last_name == "Dupont"
        assert row.first_name == "Jean"

    def test_raises_without_last_name(self, sa_sync_conn, repo):
        """Sans patronyme, `compute_person_name_forms` ne rend aucune forme : la personne ne serait atteignable par aucun nom."""
        with pytest.raises(ValidationError, match="nom est requis"):
            repo.create("", "Jean")


# ── merge_person ────────────────────────────────────────────────────


class TestMergePerson:
    def test_raises_on_self_merge(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        with pytest.raises(ValidationError, match="identiques"):
            service.merge_person(p, p)

    def test_raises_not_found(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            service.merge_person(p, 999999)

    def test_absorbed_id_redirects_to_kept(self, sa_sync_conn, service):
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        service.merge_person(target, source)
        assert redirect_of(sa_sync_conn, MergedEntity.PERSON, source) == target

    def test_absorbed_verdict_kept(self, sa_sync_conn, service):
        """Le rejet d'une forme de la personne absorbée survit à la fusion."""
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        _hal_name_form(sa_sync_conn, source, name_form="intrus x", status="rejected")
        service.merge_person(target, source)
        assert _name_form_status(sa_sync_conn, "intrus x", target) == "rejected"

    def test_target_verdict_prevails(self, sa_sync_conn, service):
        """Sur une forme commune, le verdict de la personne qui absorbe l'emporte."""
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        _hal_name_form(sa_sync_conn, target, name_form="forme commune", status="confirmed")
        _hal_name_form(sa_sync_conn, source, name_form="forme commune", status="rejected")
        service.merge_person(target, source)
        assert _name_form_status(sa_sync_conn, "forme commune", target) == "confirmed"

    def test_pending_target_takes_absorbed_verdict(self, sa_sync_conn, service):
        """Une forme commune en attente chez la personne qui absorbe reprend le verdict de l'autre."""
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        _hal_name_form(sa_sync_conn, target, name_form="forme commune")
        _hal_name_form(sa_sync_conn, source, name_form="forme commune", status="rejected")
        service.merge_person(target, source)
        assert _name_form_status(sa_sync_conn, "forme commune", target) == "rejected"

    def test_confirmed_source_contribution_transferred(self, sa_sync_conn, service):
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        source_contribution_id = _jean_dupont_source_contribution(
            sa_sync_conn,
            _source_record(sa_sync_conn, insert_publication(sa_sync_conn)),
        )
        insert_confirmed_source_contribution(sa_sync_conn, source_contribution_id, person_id=source)

        service.merge_person(target, source)

        assert (
            _scalar(
                sa_sync_conn,
                "SELECT person_id FROM confirmed_source_contributions WHERE source_contribution_id = :i",
                i=source_contribution_id,
            )
            == target
        )

    def test_distinct_persons_transferred(self, sa_sync_conn, service):
        """Les non-doublons de l'absorbée passent à la conservée ; celui qui oppose les deux personnes fusionnées disparaît."""
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        other = _person(sa_sync_conn, last_name="Durand")
        shared = _person(sa_sync_conn, last_name="Duval")
        for a, b in ((source, other), (source, shared), (target, shared), (source, target)):
            service.mark_distinct(a, b)

        service.merge_person(target, source)

        pairs = sa_sync_conn.execute(
            text(
                "SELECT person_id_a, person_id_b FROM distinct_persons WHERE :t IN (person_id_a, person_id_b)"
            ),
            {"t": target},
        ).all()
        assert sorted(pairs) == sorted(
            [(min(target, other), max(target, other)), (min(target, shared), max(target, shared))]
        )

    @pytest.mark.parametrize(
        ("target_exclusion", "source_exclusion", "expected"),
        [
            (None, PersonExclusion.OUT_OF_PERIMETER, PersonExclusion.OUT_OF_PERIMETER),
            (
                PersonExclusion.OUT_OF_PERIMETER,
                PersonExclusion.NOT_A_PERSON,
                PersonExclusion.NOT_A_PERSON,
            ),
            (PersonExclusion.NOT_A_PERSON, None, PersonExclusion.NOT_A_PERSON),
        ],
    )
    def test_strongest_exclusion_kept(
        self, sa_sync_conn, repo, target_exclusion, source_exclusion, expected, service
    ):
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        repo.set_exclusion(target, target_exclusion)
        repo.set_exclusion(source, source_exclusion)

        service.merge_person(target, source)

        assert (
            _scalar(sa_sync_conn, "SELECT exclusion FROM persons WHERE id = :p", p=target)
            == expected
        )


# ── batch_assign_orphan_contributions ─────────────────────────────────


class TestBatchAssignOrphanContributions:
    def test_empty_list_returns_zero(self, sa_sync_conn, contribution_service):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        assert contribution_service.batch_assign_orphan_contributions(person_id, []) == 0

    def test_attaches_contributions_and_pins_all_their_source_contributions(
        self, sa_sync_conn, contribution_service
    ):
        """Chaque contribution passe à la personne en mode `manual` ; toutes ses contributions sources sont épinglées à la personne."""
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        first = insert_publication(sa_sync_conn)
        first_contribution, first_hal = _orphan(sa_sync_conn, first, source_id="h-1")
        source_record_oa = _source_record(sa_sync_conn, first, source="openalex", source_id="W1")
        first_oa = _jean_dupont_source_contribution(
            sa_sync_conn, source_record_oa, source="openalex"
        )
        add_aligned_source_contribution(
            sa_sync_conn, first_contribution, first_oa, source_record_oa
        )
        second = insert_publication(sa_sync_conn)
        second_contribution, second_hal = _orphan(sa_sync_conn, second, source_id="h-2")

        assigned = contribution_service.batch_assign_orphan_contributions(
            person_id, [first_contribution, second_contribution]
        )

        assert assigned == 2
        assert _contribution_person(sa_sync_conn, first_contribution) == (person_id, "manual")
        assert _contribution_person(sa_sync_conn, second_contribution) == (person_id, "manual")
        members = [first_hal, first_oa, second_hal]
        assert _pinned_to(sa_sync_conn, members) == [person_id] * 3
        assert _publication_evidence(sa_sync_conn, first) == ["address"]

    def test_adds_name_forms_under_their_source(self, sa_sync_conn, contribution_service):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        contribution, _ = _orphan(
            sa_sync_conn,
            insert_publication(sa_sync_conn),
            source="openalex",
            source_id="W1",
            author_name_normalized="j dupont",
        )

        contribution_service.batch_assign_orphan_contributions(person_id, [contribution])

        assert _scalar(
            sa_sync_conn,
            "SELECT sources FROM person_name_forms WHERE name_form = 'j dupont' AND person_id = :p",
            p=person_id,
        ) == ["openalex"]

    def test_skips_already_assigned(self, sa_sync_conn, contribution_service):
        """Une contribution déjà rattachée est écartée : ni épinglage, ni changement de personne ; la contribution orphelin du lot est rattaché."""
        insert_persons_perimeter(sa_sync_conn)
        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        owned_publication = insert_publication(sa_sync_conn)
        owned_contribution, owned = _orphan(sa_sync_conn, owned_publication)
        set_perimeter_author_contribution(
            sa_sync_conn, owned_contribution, person_id=p1, mode="name"
        )
        orphan_contribution, orphan = _orphan(
            sa_sync_conn, insert_publication(sa_sync_conn), source_id="h-2"
        )

        assigned = contribution_service.batch_assign_orphan_contributions(
            p2, [owned_contribution, orphan_contribution]
        )

        assert assigned == 1
        assert _contribution_person(sa_sync_conn, owned_contribution) == (p1, "name")
        assert _pinned_to(sa_sync_conn, [owned, orphan]) == [None, p2]
        assert _contribution_person(sa_sync_conn, orphan_contribution) == (p2, "manual")


# ── detach_contributions ─────────────────────────────────────────────


class TestDetachContributions:
    def test_detaches_contribution(self, sa_sync_conn, service):
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        contribution_id = insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        source_contribution_id = _jean_dupont_source_contribution(sa_sync_conn, source_record_id)

        result = service.detach_contributions(
            person_id,
            contributions=[{"source": "hal", "source_contribution_id": source_contribution_id}],
        )

        assert result["detached"] == 1
        assert _contribution_person(sa_sync_conn, contribution_id) == (None, None)

    def test_detaches_all_sources_of_publication_from_single_ref(self, sa_sync_conn, service):
        """Le rejet porte sur la publication entière : sélectionner une source
        détache la contribution de la paire et peuple le store."""
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        contribution_id = insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        source_record_hal = _source_record(sa_sync_conn, publication_id)
        source_record_oa = _source_record(
            sa_sync_conn, publication_id, source="openalex", source_id="oa-1"
        )
        source_contribution_hal = _jean_dupont_source_contribution(sa_sync_conn, source_record_hal)
        _jean_dupont_source_contribution(sa_sync_conn, source_record_oa, source="openalex")

        # Une seule source sélectionnée (la hal).
        result = service.detach_contributions(
            person_id,
            contributions=[{"source": "hal", "source_contribution_id": source_contribution_hal}],
        )

        assert result["detached"] == 1
        assert _contribution_person(sa_sync_conn, contribution_id) == (None, None)
        assert (
            _scalar(
                sa_sync_conn,
                f"SELECT DISTINCT 1 FROM ({REJECTED_PAIRS}) rp WHERE publication_id = :p AND person_id = :pid",
                p=publication_id,
                pid=person_id,
            )
            == 1
        )

    def test_cleans_orphan_source_name_form(self, sa_sync_conn, repo, service):
        """Une forme de nom attestée par une source, devenue sans aucune source
        active après détachement, est supprimée."""
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        source_contribution_id = _jean_dupont_source_contribution(
            sa_sync_conn,
            source_record_id,
            author_name_normalized="dupont jean",
        )
        repo.add_name_form(person_id, "Dupont Jean", source="hal")

        result = service.detach_contributions(
            person_id,
            contributions=[{"source": "hal", "source_contribution_id": source_contribution_id}],
        )
        assert result["cleaned_forms"] == 1
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM person_name_forms WHERE name_form='dupont jean' AND person_id=:p",
                p=person_id,
            )
            is None
        )

    def test_preserves_rejected_orphan_name_form(self, sa_sync_conn, repo, service):
        """Une forme `rejected` devenue orpheline est préservée : la supprimer
        détruirait le blocage de non-retour qu'elle matérialise."""
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        source_contribution_id = _jean_dupont_source_contribution(
            sa_sync_conn,
            source_record_id,
            author_name_normalized="dupont jean",
        )
        repo.add_name_form(person_id, "Dupont Jean", source="hal")
        sa_sync_conn.execute(
            text(
                "UPDATE person_name_forms SET status='rejected' "
                "WHERE name_form='dupont jean' AND person_id=:p"
            ),
            {"p": person_id},
        )

        result = service.detach_contributions(
            person_id,
            contributions=[{"source": "hal", "source_contribution_id": source_contribution_id}],
        )
        assert result["cleaned_forms"] == 0
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM person_name_forms WHERE name_form='dupont jean' AND person_id=:p",
                p=person_id,
            )
            == 1
        )

    def test_preserves_computed_name_form(self, sa_sync_conn, repo, service):
        """Les formes calculées depuis le nom de la personne (source `persons`)
        ne dépendent d'aucune source et survivent au détachement."""
        person_id = repo.create("Dupont", "Jean")

        result = service.detach_contributions(person_id, contributions=[])
        assert result["cleaned_forms"] == 0
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM person_name_forms WHERE name_form='jean dupont' AND person_id=:p",
                p=person_id,
            )
            == 1
        )

    def test_keeps_source_name_form_still_backed(self, sa_sync_conn, repo, service):
        """Une forme encore portée par une contribution source d'une contribution de la personne, dans une autre publication, reste quand on détache une seule publication."""
        person_id = _person(sa_sync_conn)
        pub1 = insert_publication(sa_sync_conn, "P1")
        pub2 = insert_publication(sa_sync_conn, "P2")
        sp1 = _source_record(sa_sync_conn, pub1)
        sp2 = _source_record(sa_sync_conn, pub2, source_id="hal-2")
        sa1 = _jean_dupont_source_contribution(
            sa_sync_conn, sp1, author_name_normalized="dupont jean"
        )
        backing = _jean_dupont_source_contribution(
            sa_sync_conn, sp2, author_name_normalized="dupont jean"
        )
        insert_person_contribution(sa_sync_conn, backing, person_id=person_id)
        repo.add_name_form(person_id, "Dupont Jean", source="hal")

        result = service.detach_contributions(
            person_id, contributions=[{"source": "hal", "source_contribution_id": sa1}]
        )
        assert result["cleaned_forms"] == 0
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM person_name_forms WHERE name_form='dupont jean' AND person_id=:p",
                p=person_id,
            )
            == 1
        )


class TestMarkDistinctPersons:
    def test_raises_on_same_id(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        with pytest.raises(ValidationError, match="elle-même"):
            service.mark_distinct(p, p)

    def test_inserts_ordered_pair(self, sa_sync_conn, service):
        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        service.mark_distinct(p2, p1)
        n = sa_sync_conn.execute(
            text(
                "SELECT COUNT(*) AS n FROM distinct_persons "
                "WHERE person_id_a = :a AND person_id_b = :b"
            ),
            {"a": min(p1, p2), "b": max(p1, p2)},
        ).scalar_one()
        assert n == 1

    def test_idempotent(self, sa_sync_conn, service):
        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        service.mark_distinct(p1, p2)
        service.mark_distinct(p1, p2)
        n = sa_sync_conn.execute(
            text(
                "SELECT COUNT(*) AS n FROM distinct_persons "
                "WHERE person_id_a = :a AND person_id_b = :b"
            ),
            {"a": min(p1, p2), "b": max(p1, p2)},
        ).scalar_one()
        assert n == 1


# ── update_name_form_status ────────────────────────────────────────


def _name_form_status(conn, form, person_id):
    return conn.execute(
        text("SELECT status::text FROM person_name_forms WHERE name_form = :f AND person_id = :p"),
        {"f": form, "p": person_id},
    ).scalar_one()


class TestUpdateNameFormStatus:
    def test_reject_keeps_row_and_sets_status(self, sa_sync_conn, service):
        """Rejeter une forme conserve la row (tombstone du verrou de non-retour)."""
        person_id = _person(sa_sync_conn, last_name="Unique", first_name="Name")
        _hal_name_form(sa_sync_conn, person_id, name_form="intrus unique")

        row = service.update_name_form_status(person_id, "intrus unique", "rejected")

        assert row["status"] == "rejected"
        assert _name_form_status(sa_sync_conn, "intrus unique", person_id) == "rejected"

    def test_confirm_overrides_previous_status(self, sa_sync_conn, service):
        person_id = _person(sa_sync_conn, last_name="Alpha", first_name="Beta")
        _hal_name_form(sa_sync_conn, person_id, name_form="alpha b")

        service.update_name_form_status(person_id, "alpha b", "rejected")
        row = service.update_name_form_status(person_id, "alpha b", "confirmed")

        assert row["status"] == "confirmed"

    def test_derived_form_status_refused(self, sa_sync_conn, repo, service):
        """Une forme dérivée du nom de la personne est confirmée d'office : son statut se refuse."""
        person_id = repo.create("Gamma", "Delta")

        with pytest.raises(ConflictError):
            service.update_name_form_status(person_id, "delta gamma", "rejected")

    def test_unknown_form_raises(self, sa_sync_conn, repo, service):
        person_id = repo.create("Gamma", "Delta")

        with pytest.raises(NotFoundError):
            service.update_name_form_status(person_id, "inexistante xyz", "rejected")

    def test_reject_sets_the_lock(self, sa_sync_conn, service):
        """Rejeter une forme pose le verrou."""
        pid = _person(sa_sync_conn, last_name="Foreign", first_name="Form")
        _hal_name_form(sa_sync_conn, pid, name_form="intrus etranger")

        service.update_name_form_status(pid, "intrus etranger", "rejected")

        assert (
            sa_sync_conn.execute(
                text(
                    "SELECT status::text FROM person_name_forms "
                    "WHERE name_form = 'intrus etranger' AND person_id = :pid"
                ),
                {"pid": pid},
            ).scalar_one()
            == "rejected"
        )


class TestNameFormRejectionOnContributions:
    """Le rejet d'une forme de nom détache de la personne les contributions rattachées par le nom dont une contribution source porte la forme."""

    def test_marks_contributions_resolved_by_name(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        form = {"author_name_normalized": "intrus unique"}
        by_name, name_contribution = _perimeter_contribution(
            sa_sync_conn, p, "name", source_id="hal-n", **form
        )
        by_initials, initials_contribution = _perimeter_contribution(
            sa_sync_conn, p, "compatible_name", source_id="hal-c", **form
        )
        by_orcid, orcid_contribution = _perimeter_contribution(
            sa_sync_conn, p, "orcid", source_id="hal-o", **form
        )
        manual, manual_contribution = _perimeter_contribution(
            sa_sync_conn, p, "manual", source_id="hal-m", **form
        )
        _hal_name_form(sa_sync_conn, p, name_form="intrus unique")

        service.update_name_form_status(p, "intrus unique", "rejected")

        assert queued(sa_sync_conn, Queue.CONTRIBUTION_RESOLUTION) == {
            name_contribution,
            initials_contribution,
        }
        assert _contribution_person(sa_sync_conn, name_contribution) == (p, "name")

    def test_contribution_under_another_form_is_untouched(self, sa_sync_conn, service):
        p = _person(sa_sync_conn)
        _, contribution = _perimeter_contribution(
            sa_sync_conn, p, "name", source_id="hal-n", author_name_normalized="jean dupont"
        )
        _hal_name_form(sa_sync_conn, p, name_form="intrus unique")

        service.update_name_form_status(p, "intrus unique", "rejected")

        assert _contribution_person(sa_sync_conn, contribution) == (p, "name")


# ── assign_orphan_contribution ───────────────────────────────────────


class TestAssignOrphanContribution:
    def test_attaches_contribution_and_pins_all_its_source_contributions(
        self, sa_sync_conn, contribution_service
    ):
        """La contribution passe à la personne en mode `manual` ; toutes ses contributions sources sont épinglées à la personne et la reçoivent dans `source_contributions`."""
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        contribution, hal = _orphan(sa_sync_conn, publication_id)
        source_record_oa = _source_record(
            sa_sync_conn, publication_id, source="openalex", source_id="W1"
        )
        openalex = _jean_dupont_source_contribution(
            sa_sync_conn, source_record_oa, source="openalex"
        )
        add_aligned_source_contribution(sa_sync_conn, contribution, openalex, source_record_oa)

        contribution_service.assign_orphan_contribution(person_id, contribution)

        assert _contribution_person(sa_sync_conn, contribution) == (person_id, "manual")
        assert _pinned_to(sa_sync_conn, [hal, openalex]) == [person_id, person_id]
        assert _publication_evidence(sa_sync_conn, publication_id) == ["address"]
        assert _scalar(
            sa_sync_conn,
            "SELECT sources FROM person_name_forms WHERE name_form = 'jean dupont' AND person_id = :p",
            p=person_id,
        ) == ["hal", "openalex"]

    def test_raises_if_already_assigned(self, sa_sync_conn, contribution_service):
        """Une contribution déjà rattachée n'est pas reprise : le refus nomme la détentrice."""
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        other_id = _person(sa_sync_conn, last_name="Other", first_name="Author")
        contribution, source_contribution_id = _orphan(
            sa_sync_conn, insert_publication(sa_sync_conn)
        )
        set_perimeter_author_contribution(
            sa_sync_conn, contribution, person_id=other_id, mode="name"
        )

        with pytest.raises(ContributionAlreadyAssignedError) as exc:
            contribution_service.assign_orphan_contribution(person_id, contribution)
        assert exc.value.owner_person_id == other_id
        assert _contribution_person(sa_sync_conn, contribution) == (other_id, "name")
        assert _pinned_to(sa_sync_conn, [source_contribution_id]) == [None]

    def test_raises_if_contribution_missing(self, sa_sync_conn, contribution_service):
        person_id = _person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            contribution_service.assign_orphan_contribution(person_id, 999999)


class TestReassignRejectedPairUnit:
    """Pré-contrôle de rejet sur les chemins de réassignation orphan-contributions."""

    def test_assign_blocked_when_rejected(self, sa_sync_conn, contribution_service):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        contribution, source_contribution_id = _orphan(sa_sync_conn, publication_id)
        insert_rejected_contribution(sa_sync_conn, publication_id, person_id=person_id)

        with pytest.raises(RejectedPairError) as exc:
            contribution_service.assign_orphan_contribution(person_id, contribution)
        pair = exc.value.rejected_pairs[0]
        assert pair["publication_id"] == publication_id
        assert pair["person_id"] == person_id
        assert pair["rejected_at"]
        # Rien d'écrit : le pré-contrôle précède l'épinglage.
        assert _pinned_to(sa_sync_conn, [source_contribution_id]) == [None]
        assert _contribution_person(sa_sync_conn, contribution) == (None, None)

    def test_assign_forced_unrejects_and_attaches_contribution(
        self, sa_sync_conn, contribution_service
    ):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        contribution, source_contribution_id = _orphan(sa_sync_conn, publication_id)
        insert_rejected_contribution(sa_sync_conn, publication_id, person_id=person_id)

        contribution_service.assign_orphan_contribution(person_id, contribution, force=True)

        assert (
            _scalar(
                sa_sync_conn,
                f"SELECT DISTINCT 1 FROM ({REJECTED_PAIRS}) rp WHERE publication_id = :p AND person_id = :pid",
                p=publication_id,
                pid=person_id,
            )
            is None
        )
        assert _pinned_to(sa_sync_conn, [source_contribution_id]) == [person_id]
        assert _contribution_person(sa_sync_conn, contribution) == (person_id, "manual")

    def test_batch_blocked_lists_all_rejected(self, sa_sync_conn, contribution_service):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        pub1 = insert_publication(sa_sync_conn, "P1")
        pub2 = insert_publication(sa_sync_conn, "P2")
        group1, sa1 = _orphan(sa_sync_conn, pub1, source_id="h-1")
        group2, sa2 = _orphan(sa_sync_conn, pub2, source_id="h-2")
        insert_rejected_contribution(sa_sync_conn, pub1, person_id=person_id)

        with pytest.raises(RejectedPairError) as exc:
            contribution_service.batch_assign_orphan_contributions(person_id, [group1, group2])
        assert {p["publication_id"] for p in exc.value.rejected_pairs} == {pub1}
        # Rien d'écrit : le pré-contrôle précède l'épinglage.
        assert [_contribution_person(sa_sync_conn, g) for g in (group1, group2)] == [
            (None, None)
        ] * 2
        assert _pinned_to(sa_sync_conn, [sa1, sa2]) == [None, None]

    def test_batch_forced_unrejects_all(self, sa_sync_conn, contribution_service):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        pub1 = insert_publication(sa_sync_conn, "P1")
        contribution, _ = _orphan(sa_sync_conn, pub1, source_id="h-1")
        insert_rejected_contribution(sa_sync_conn, pub1, person_id=person_id)

        assigned = contribution_service.batch_assign_orphan_contributions(
            person_id, [contribution], force=True
        )

        assert assigned == 1
        assert (
            _scalar(
                sa_sync_conn,
                f"SELECT DISTINCT 1 FROM ({REJECTED_PAIRS}) rp WHERE publication_id = :p AND person_id = :pid",
                p=pub1,
                pid=person_id,
            )
            is None
        )
        assert _contribution_person(sa_sync_conn, contribution) == (person_id, "manual")


class TestMergePersonRejectedContributions:
    """La fusion transfère les rejets de l'absorbée vers l'absorbante (clé
    identique), avec dédoublonnage sur conflit de PK."""

    def test_transfers_and_dedups(self, sa_sync_conn, service):
        target = _person(sa_sync_conn, last_name="Cible", first_name="T")
        source = _person(sa_sync_conn, last_name="Source", first_name="S")
        publication_shared = insert_publication(sa_sync_conn, "Shared")
        publication_source_only = insert_publication(sa_sync_conn, "SourceOnly")

        insert_rejected_contribution(
            sa_sync_conn, publication_shared, person_id=target
        )  # conflit : déjà rejeté côté cible
        insert_rejected_contribution(
            sa_sync_conn, publication_shared, person_id=source
        )  # doit être dédoublonné
        insert_rejected_contribution(
            sa_sync_conn, publication_source_only, person_id=source
        )  # doit migrer vers la cible

        service.merge_person(target, source)

        rows = sa_sync_conn.execute(
            text(f"SELECT DISTINCT publication_id, person_id FROM ({REJECTED_PAIRS}) rp")
        ).all()
        assert {(r.publication_id, r.person_id) for r in rows} == {
            (publication_shared, target),
            (publication_source_only, target),
        }

    def test_rejection_prevails_over_merged_contribution(self, sa_sync_conn, service):
        """L'absorbée signe une publication où l'absorbante est rejetée : après fusion, le rejet l'emporte."""
        target = _person(sa_sync_conn, last_name="Cible", first_name="T")
        source = _person(sa_sync_conn, last_name="Source", first_name="S")
        publication = insert_publication(sa_sync_conn, "Conflit")
        _source_record(sa_sync_conn, publication)
        insert_contribution(sa_sync_conn, publication, person_id=source)
        insert_rejected_contribution(sa_sync_conn, publication, person_id=target)

        service.merge_person(target, source)

        contributions_with_person = sa_sync_conn.execute(
            text(
                "SELECT count(*) FROM contributions"
                " WHERE publication_id = :publication AND person_id IS NOT NULL"
            ),
            {"publication": publication},
        ).scalar_one()
        assert contributions_with_person == 0
