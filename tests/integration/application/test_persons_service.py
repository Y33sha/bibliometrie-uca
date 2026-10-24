"""Tests de caractérisation du service des personnes et de l'attribution des contributions orphelines : identifiants, formes de nom, détachement, fusion."""

from functools import partial

import pytest
from sqlalchemy import text

from application.services.contributions.assign_orphans import (
    assign_orphan_contribution,
    batch_assign_orphan_contributions,
)
from application.services.persons.core import (
    add_identifier,
    create_person,
    detach_contributions,
    mark_distinct,
    merge_person,
    set_exclusion,
    update_identifier_status,
    update_name,
    update_name_form_status,
)
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
from pipeline.transformation.publications.publication_perimeter import (
    PublicationPerimeterRecompute,
)
from tests.integration.helpers.contributions import (
    insert_confirmed_source_contribution,
    insert_contribution,
)
from tests.integration.helpers.groups import (
    add_group_member,
    insert_group,
    insert_person_group,
    set_perimeter_author_group,
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

_PERIMETER = PublicationPerimeterRecompute()


def _publication_evidence(conn, publication_id):
    return _scalar(
        conn,
        "SELECT perimeter_evidence::text[] FROM publications WHERE id = :p",
        p=publication_id,
    )


def _group_person(conn, group_id):
    return tuple(
        conn.execute(
            text(
                "SELECT person_id, resolution_mode::text FROM source_contribution_groups"
                " WHERE id = :g"
            ),
            {"g": group_id},
        ).one()
    )


def _perimeter_group(conn, person_id, mode, *, source_id, **source_contribution):
    """Publication du périmètre dont le seul groupe d'auteur, rattaché à la personne par `mode`, réunit une contribution source décrite par `source_contribution`. Rend (publication, groupe)."""
    publication = insert_publication(conn, in_perimeter=True)
    source_record = _source_record(conn, publication, source_id=source_id)
    source_contribution_id = insert_source_contribution(conn, source_record, **source_contribution)
    group = insert_group(conn, publication, [(source_contribution_id, source_record)])
    set_perimeter_author_group(conn, group, person_id=person_id, mode=mode)
    return publication, group


def _orphan(conn, publication_id, *, source_id="hal-1", source="hal", **source_contribution):
    """Contribution orpheline : groupe d'auteur du périmètre sans personne, d'une contribution source « jean dupont » décrite par `source_contribution`. Rend (groupe, contribution source)."""
    source_record = _source_record(conn, publication_id, source=source, source_id=source_id)
    source_contribution_id = _jean_dupont_source_contribution(
        conn, source_record, source=source, **source_contribution
    )
    group = insert_group(conn, publication_id, [(source_contribution_id, source_record)])
    set_perimeter_author_group(conn, group)
    return group, source_contribution_id


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


# ── Helpers ─────────────────────────────────────────────────


def _scalar(conn, sql_text: str, **params):
    return conn.execute(text(sql_text), params).scalar_one_or_none()


# ── add_identifier ─────────────────────────────────────────────────


class TestAddIdentifier:
    def test_manual_source_refuses_hal_person_id(self, sa_sync_conn, repo):
        """`hal_person_id` est la référence d'un compte HAL, que l'extraction observe : personne ne l'attribue à la main."""
        person_id = _person(sa_sync_conn)
        with pytest.raises(ValidationError, match="id_type"):
            add_identifier(person_id, "hal_person_id", "12345", source="manual", repo=repo)

    def test_auto_source_accepts_hal_person_id(self, sa_sync_conn, repo):
        """La promotion depuis les contributions sources reste libre de le poser."""
        person_id = _person(sa_sync_conn)
        result = add_identifier(person_id, "hal_person_id", "12345", repo=repo)
        assert result.outcome is AttributionOutcome.ADDED

    def test_manual_source_raises_on_unknown_person(self, repo):
        """Sans cette garde, l'identifiant venu d'un formulaire heurterait la clé étrangère."""
        with pytest.raises(NotFoundError):
            add_identifier(999999, "orcid", "0000-0001-2345-6789", source="manual", repo=repo)

    def test_inserts_new(self, sa_sync_conn, repo):
        person_id = _person(sa_sync_conn)
        result = add_identifier(person_id, "orcid", "0000-0001-2345-6789", repo=repo)
        assert result.outcome is AttributionOutcome.ADDED
        assert result.id_value == "0000-0001-2345-6789"
        status = _scalar(
            sa_sync_conn,
            "SELECT status FROM person_identifiers WHERE id_type='orcid' AND id_value=:v",
            v="0000-0001-2345-6789",
        )
        assert status == "pending"

    def test_reassigns_if_rejected(self, sa_sync_conn, repo):
        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        add_identifier(p1, "orcid", "0000-0001-2345-6789", repo=repo)
        sa_sync_conn.execute(
            text(
                "UPDATE person_identifiers SET status='rejected' "
                "WHERE id_value='0000-0001-2345-6789'"
            )
        )
        result = add_identifier(p2, "orcid", "0000-0001-2345-6789", repo=repo)
        assert result.outcome is AttributionOutcome.REASSIGNED

        row = sa_sync_conn.execute(
            text(
                "SELECT person_id, status FROM person_identifiers "
                "WHERE id_value='0000-0001-2345-6789'"
            )
        ).one()
        assert row.person_id == p2
        assert row.status == "pending"

    def test_raises_when_pending_on_other_person(self, sa_sync_conn, repo):
        """Si le même identifiant existe en 'pending' sur une autre personne,
        on lève `CannotAttributeConflict` (pour réattribuer, il faut d'abord
        passer le statut à 'rejected')."""
        import pytest

        from domain.errors import CannotAttributeConflict

        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        add_identifier(p1, "orcid", "0000-0001-2345-6789", repo=repo)

        with pytest.raises(CannotAttributeConflict):
            add_identifier(p2, "orcid", "0000-0001-2345-6789", repo=repo)

        # L'identifiant reste rattaché à p1.
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT person_id FROM person_identifiers WHERE id_value='0000-0001-2345-6789'",
            )
            == p1
        )

    def test_idempotent_on_same_person(self, sa_sync_conn, repo):
        """Réappliquer add_identifier sur la même personne ne change rien."""
        p = _person(sa_sync_conn)
        add_identifier(p, "orcid", "0000-0001-2345-6789", repo=repo)
        result = add_identifier(p, "orcid", "0000-0001-2345-6789", repo=repo)  # no-op
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
    def test_sets_status(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        ident_id = insert_person_identifier(
            sa_sync_conn, p, id_type="orcid", id_value="0000-0001", status="pending"
        )

        result = update_identifier_status(ident_id, "confirmed", repo=repo)

        assert result.status == "confirmed"
        assert result.propagated == 0

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_identifier_status(999999, "confirmed", repo=repo)


class TestIdentifierStatusPropagation:
    """Une décision sur un identifiant s'étend aux identifiants `pending` de la même personne que portent les mêmes comptes HAL."""

    ORCID = "0000-0002-1633-8730"
    HAL_ACCOUNT = {"hal_person_id": 11581, "idhal": "nina-radosevic-robin", "orcid": ORCID}

    def _status(self, conn, ident_id):
        return _scalar(
            conn, "SELECT status::text FROM person_identifiers WHERE id = :i", i=ident_id
        )

    def _source_contribution(self, conn, person_id, source, source_id, identifiers, **kw):
        """Contribution source seule dans un groupe rattaché à la personne `person_id`."""
        source_record = _source_record(
            conn, insert_publication(conn), source=source, source_id=source_id
        )
        source_contribution = _jean_dupont_source_contribution(
            conn, source_record, source=source, identifiers=identifiers, **kw
        )
        insert_person_group(conn, source_contribution, person_id=person_id)

    def test_rejecting_an_orcid_rejects_its_hal_account(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        self._source_contribution(
            sa_sync_conn, p, "hal", "hal-a", {**self.HAL_ACCOUNT, "idref": "181370662"}
        )
        # Même compte, sans l'ORCID : son idHAL suit le compte.
        self._source_contribution(
            sa_sync_conn, p, "hal", "hal-b", {"hal_person_id": 11581, "idhal": "nr2"}
        )
        # ScanR associe l'ORCID à un autre IdRef : cette association n'entre pas dans le groupe.
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

        result = update_identifier_status(orcid, "rejected", repo=repo)

        assert result.propagated == 3
        assert {self._status(sa_sync_conn, i) for i in (orcid, account, idhal, idhal_2)} == {
            "rejected"
        }
        assert self._status(sa_sync_conn, idref_confirmed) == "confirmed"
        assert self._status(sa_sync_conn, idref_scanr) == "pending"

    def test_other_persons_are_untouched(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        other = _person(sa_sync_conn, last_name="Autre", first_name="Personne")
        self._source_contribution(sa_sync_conn, p, "hal", "hal-a", self.HAL_ACCOUNT)
        self._source_contribution(sa_sync_conn, other, "hal", "hal-b", {"hal_person_id": 11581})
        orcid = insert_person_identifier(sa_sync_conn, p, id_type="orcid", id_value=self.ORCID)
        other_account = insert_person_identifier(
            sa_sync_conn, other, id_type="idhal", id_value="nina-radosevic-robin"
        )

        update_identifier_status(orcid, "confirmed", repo=repo)

        assert self._status(sa_sync_conn, other_account) == "pending"

    def test_neutralized_identifier_does_not_designate_the_account(self, sa_sync_conn, repo):
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

        assert update_identifier_status(orcid, "rejected", repo=repo).propagated == 0
        assert self._status(sa_sync_conn, account) == "pending"

    def test_back_to_pending_is_not_propagated(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        self._source_contribution(sa_sync_conn, p, "hal", "hal-a", self.HAL_ACCOUNT)
        orcid = insert_person_identifier(
            sa_sync_conn, p, id_type="orcid", id_value=self.ORCID, status="rejected"
        )
        insert_person_identifier(sa_sync_conn, p, id_type="hal_person_id", id_value="11581")

        assert update_identifier_status(orcid, "pending", repo=repo).propagated == 0


class TestIdentifierRejectionOnGroups:
    """Le rejet d'un identifiant détache de la personne les groupes que cet identifiant lui rattache."""

    ORCID = "0000-0002-1825-0097"

    def test_marks_groups_resolved_by_the_identifier(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        identifiers = {"orcid": self.ORCID}
        by_orcid, orcid_group = _perimeter_group(
            sa_sync_conn, p, "orcid", source_id="hal-orcid", identifiers=identifiers
        )
        by_name, name_group = _perimeter_group(
            sa_sync_conn, p, "name", source_id="hal-name", identifiers=identifiers
        )
        manual, manual_group = _perimeter_group(
            sa_sync_conn, p, "manual", source_id="hal-manual", identifiers=identifiers
        )
        orcid = insert_person_identifier(sa_sync_conn, p, id_type="orcid", id_value=self.ORCID)

        update_identifier_status(orcid, "rejected", repo=repo)

        assert queued(sa_sync_conn, Queue.GROUP_RESOLUTION) == {orcid_group}
        assert _group_person(sa_sync_conn, orcid_group) == (p, "orcid")

    def test_group_without_the_value_is_untouched(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        _, group = _perimeter_group(
            sa_sync_conn, p, "orcid", source_id="hal-other", identifiers={"orcid": "0000-0001"}
        )
        orcid = insert_person_identifier(sa_sync_conn, p, id_type="orcid", id_value=self.ORCID)

        update_identifier_status(orcid, "rejected", repo=repo)

        assert _group_person(sa_sync_conn, group) == (p, "orcid")

    def test_confirmation_leaves_groups(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        _, group = _perimeter_group(
            sa_sync_conn, p, "orcid", source_id="hal-orcid", identifiers={"orcid": self.ORCID}
        )
        orcid = insert_person_identifier(sa_sync_conn, p, id_type="orcid", id_value=self.ORCID)

        update_identifier_status(orcid, "confirmed", repo=repo)

        assert _group_person(sa_sync_conn, group) == (p, "orcid")


class TestSetExclusion:
    def _exclusion(self, conn, p):
        return _scalar(conn, "SELECT exclusion::text FROM persons WHERE id = :p", p=p)

    def test_excludes(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        set_exclusion(
            p,
            PersonExclusion.OUT_OF_PERIMETER,
            conn=sa_sync_conn,
            repo=repo,
            perimeter_recompute=_PERIMETER,
        )
        assert self._exclusion(sa_sync_conn, p) == "out_of_perimeter"
        assert repo.find_by_id(p).exclusion is PersonExclusion.OUT_OF_PERIMETER

    def test_retains(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        set_exclusion(
            p,
            PersonExclusion.NOT_A_PERSON,
            conn=sa_sync_conn,
            repo=repo,
            perimeter_recompute=_PERIMETER,
        )
        set_exclusion(p, None, conn=sa_sync_conn, repo=repo, perimeter_recompute=_PERIMETER)
        assert self._exclusion(sa_sync_conn, p) is None

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            set_exclusion(
                999999,
                PersonExclusion.NOT_A_PERSON,
                conn=sa_sync_conn,
                repo=repo,
                perimeter_recompute=_PERIMETER,
            )

    def test_refreshes_in_perimeter_of_own_publications_only(self, sa_sync_conn, repo):
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

        set_exclusion(
            excluded,
            PersonExclusion.OUT_OF_PERIMETER,
            conn=sa_sync_conn,
            repo=repo,
            perimeter_recompute=_PERIMETER,
        )
        assert (flag(alone), flag(shared), flag(unrelated)) == (False, True, False)

        set_exclusion(excluded, None, conn=sa_sync_conn, repo=repo, perimeter_recompute=_PERIMETER)
        assert flag(alone) is True


class TestUpdateName:
    def test_updates_name_and_refreshes_forms(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        insert_person_name_form(sa_sync_conn, p, name_form="dupont jean", sources=["persons"])

        update_name(p, "Martin", "Sophie", repo=repo)

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
        # pour ce pid : refresh_name_forms a dû supprimer la row entièrement.
        row = sa_sync_conn.execute(
            text(
                "SELECT 1 FROM person_name_forms "
                "WHERE name_form = 'dupont jean' AND person_id = :pid"
            ),
            {"pid": p},
        ).first()
        assert row is None

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_name(999999, "X", "X", repo=repo)

    def test_strips_surrounding_space(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        update_name(p, "  Martin  ", "  Sophie  ", repo=repo)
        row = sa_sync_conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.last_name == "Martin"
        assert row.first_name == "Sophie"

    def test_raises_without_last_name(self, sa_sync_conn, repo):
        """Effacer le patronyme retirerait à la personne les formes que seul son nom canonique porte."""
        p = _person(sa_sync_conn)
        with pytest.raises(ValidationError, match="nom est requis"):
            update_name(p, "", "Jean", repo=repo)

    def test_raises_on_blank_last_name(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        with pytest.raises(ValidationError, match="nom est requis"):
            update_name(p, "   ", "Jean", repo=repo)


# ── create_person ───────────────────────────────────────────────────


class TestCreatePerson:
    def test_creates_and_computes_name_forms(self, sa_sync_conn, repo):
        p = create_person("Dupont", "Jean", repo=repo)
        forms = {
            r.name_form
            for r in sa_sync_conn.execute(
                text("SELECT name_form FROM person_name_forms WHERE person_id = :p"), {"p": p}
            )
        }
        assert forms == {"jean dupont", "j dupont"}

    def test_strips_surrounding_space(self, sa_sync_conn, repo):
        p = create_person("  Dupont  ", "  Jean  ", repo=repo)
        row = sa_sync_conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.last_name == "Dupont"
        assert row.first_name == "Jean"

    def test_raises_without_last_name(self, sa_sync_conn, repo):
        """Sans patronyme, `compute_person_name_forms` ne rend aucune forme : la personne ne serait atteignable par aucun nom."""
        with pytest.raises(ValidationError, match="nom est requis"):
            create_person("", "Jean", repo=repo)


# ── merge_person ────────────────────────────────────────────────────


class TestMergePerson:
    def test_raises_on_self_merge(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        with pytest.raises(ValidationError, match="identiques"):
            merge_person(p, p, repo=repo)

    def test_raises_not_found(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            merge_person(p, 999999, repo=repo)

    def test_absorbed_id_redirects_to_kept(self, sa_sync_conn, repo):
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        merge_person(target, source, repo=repo)
        assert redirect_of(sa_sync_conn, MergedEntity.PERSON, source) == target

    def test_absorbed_verdict_kept(self, sa_sync_conn, repo):
        """Le rejet d'une forme de la personne absorbée survit à la fusion."""
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        _hal_name_form(sa_sync_conn, source, name_form="intrus x", status="rejected")
        merge_person(target, source, repo=repo)
        assert _name_form_status(sa_sync_conn, "intrus x", target) == "rejected"

    def test_target_verdict_prevails(self, sa_sync_conn, repo):
        """Sur une forme commune, le verdict de la personne qui absorbe l'emporte."""
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        _hal_name_form(sa_sync_conn, target, name_form="forme commune", status="confirmed")
        _hal_name_form(sa_sync_conn, source, name_form="forme commune", status="rejected")
        merge_person(target, source, repo=repo)
        assert _name_form_status(sa_sync_conn, "forme commune", target) == "confirmed"

    def test_pending_target_takes_absorbed_verdict(self, sa_sync_conn, repo):
        """Une forme commune en attente chez la personne qui absorbe reprend le verdict de l'autre."""
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        _hal_name_form(sa_sync_conn, target, name_form="forme commune")
        _hal_name_form(sa_sync_conn, source, name_form="forme commune", status="rejected")
        merge_person(target, source, repo=repo)
        assert _name_form_status(sa_sync_conn, "forme commune", target) == "rejected"

    def test_confirmed_source_contribution_transferred(self, sa_sync_conn, repo):
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        source_contribution_id = _jean_dupont_source_contribution(
            sa_sync_conn,
            _source_record(sa_sync_conn, insert_publication(sa_sync_conn)),
        )
        insert_confirmed_source_contribution(sa_sync_conn, source_contribution_id, person_id=source)

        merge_person(target, source, repo=repo)

        assert (
            _scalar(
                sa_sync_conn,
                "SELECT person_id FROM confirmed_source_contributions WHERE source_contribution_id = :i",
                i=source_contribution_id,
            )
            == target
        )

    def test_distinct_persons_transferred(self, sa_sync_conn, repo):
        """Les non-doublons de l'absorbée passent à la conservée ; celui qui oppose les deux personnes fusionnées disparaît."""
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        other = _person(sa_sync_conn, last_name="Durand")
        shared = _person(sa_sync_conn, last_name="Duval")
        for a, b in ((source, other), (source, shared), (target, shared), (source, target)):
            mark_distinct(a, b, repo=repo)

        merge_person(target, source, repo=repo)

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
        self, sa_sync_conn, repo, target_exclusion, source_exclusion, expected
    ):
        target = _person(sa_sync_conn)
        source = _person(sa_sync_conn, last_name="Dupond")
        repo.set_exclusion(target, target_exclusion)
        repo.set_exclusion(source, source_exclusion)

        merge_person(target, source, repo=repo)

        assert (
            _scalar(sa_sync_conn, "SELECT exclusion FROM persons WHERE id = :p", p=target)
            == expected
        )


# ── batch_assign_orphan_contributions ─────────────────────────────────


class TestBatchAssignOrphanContributions:
    def test_empty_list_returns_zero(self, sa_sync_conn, repo, contribution_repo):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        assert (
            batch_assign_orphan_contributions(
                person_id,
                [],
                perimeter_recompute=_PERIMETER,
                repo=repo,
                contribution_repo=contribution_repo,
                conn=sa_sync_conn,
            )
            == 0
        )

    def test_attaches_groups_and_pins_all_members(self, sa_sync_conn, repo, contribution_repo):
        """Chaque groupe passe à la personne en mode `manual` ; tous ses membres sont épinglés à la personne."""
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        first = insert_publication(sa_sync_conn)
        first_group, first_hal = _orphan(sa_sync_conn, first, source_id="h-1")
        source_record_oa = _source_record(sa_sync_conn, first, source="openalex", source_id="W1")
        first_oa = _jean_dupont_source_contribution(
            sa_sync_conn, source_record_oa, source="openalex"
        )
        add_group_member(sa_sync_conn, first_group, first_oa, source_record_oa)
        second = insert_publication(sa_sync_conn)
        second_group, second_hal = _orphan(sa_sync_conn, second, source_id="h-2")

        assigned = batch_assign_orphan_contributions(
            person_id,
            [first_group, second_group],
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
            conn=sa_sync_conn,
        )

        assert assigned == 2
        assert _group_person(sa_sync_conn, first_group) == (person_id, "manual")
        assert _group_person(sa_sync_conn, second_group) == (person_id, "manual")
        members = [first_hal, first_oa, second_hal]
        assert _pinned_to(sa_sync_conn, members) == [person_id] * 3
        assert _publication_evidence(sa_sync_conn, first) == ["address"]

    def test_adds_name_forms_under_their_source(self, sa_sync_conn, repo, contribution_repo):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        group, _ = _orphan(
            sa_sync_conn,
            insert_publication(sa_sync_conn),
            source="openalex",
            source_id="W1",
            author_name_normalized="j dupont",
        )

        batch_assign_orphan_contributions(
            person_id,
            [group],
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
            conn=sa_sync_conn,
        )

        assert _scalar(
            sa_sync_conn,
            "SELECT sources FROM person_name_forms WHERE name_form = 'j dupont' AND person_id = :p",
            p=person_id,
        ) == ["openalex"]

    def test_skips_already_assigned(self, sa_sync_conn, repo, contribution_repo):
        """Un groupe déjà rattaché est écarté : ni épinglage, ni changement de personne ; le groupe orphelin du lot est rattaché."""
        insert_persons_perimeter(sa_sync_conn)
        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        owned_publication = insert_publication(sa_sync_conn)
        owned_group, owned = _orphan(sa_sync_conn, owned_publication)
        set_perimeter_author_group(sa_sync_conn, owned_group, person_id=p1, mode="name")
        orphan_group, orphan = _orphan(
            sa_sync_conn, insert_publication(sa_sync_conn), source_id="h-2"
        )

        assigned = batch_assign_orphan_contributions(
            p2,
            [owned_group, orphan_group],
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
            conn=sa_sync_conn,
        )

        assert assigned == 1
        assert _group_person(sa_sync_conn, owned_group) == (p1, "name")
        assert _pinned_to(sa_sync_conn, [owned, orphan]) == [None, p2]
        assert _group_person(sa_sync_conn, orphan_group) == (p2, "manual")


# ── detach_contributions ─────────────────────────────────────────────


class TestDetachContributions:
    def test_detaches_group(self, sa_sync_conn, repo, contribution_repo):
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        group_id = insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        source_contribution_id = _jean_dupont_source_contribution(sa_sync_conn, source_record_id)

        result = detach_contributions(
            person_id,
            contributions=[{"source": "hal", "source_contribution_id": source_contribution_id}],
            conn=sa_sync_conn,
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
        )

        assert result["detached"] == 1
        assert _group_person(sa_sync_conn, group_id) == (None, None)

    def test_detaches_all_sources_of_publication_from_single_ref(
        self, sa_sync_conn, repo, contribution_repo
    ):
        """Le rejet porte sur la publication entière : sélectionner une source
        détache le groupe de la paire et peuple le store."""
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        group_id = insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        source_record_hal = _source_record(sa_sync_conn, publication_id)
        source_record_oa = _source_record(
            sa_sync_conn, publication_id, source="openalex", source_id="oa-1"
        )
        source_contribution_hal = _jean_dupont_source_contribution(sa_sync_conn, source_record_hal)
        _jean_dupont_source_contribution(sa_sync_conn, source_record_oa, source="openalex")

        # Une seule source sélectionnée (la hal).
        result = detach_contributions(
            person_id,
            contributions=[{"source": "hal", "source_contribution_id": source_contribution_hal}],
            conn=sa_sync_conn,
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
        )

        assert result["detached"] == 1
        assert _group_person(sa_sync_conn, group_id) == (None, None)
        assert (
            _scalar(
                sa_sync_conn,
                f"SELECT DISTINCT 1 FROM ({REJECTED_PAIRS}) rp WHERE publication_id = :p AND person_id = :pid",
                p=publication_id,
                pid=person_id,
            )
            == 1
        )

    def test_cleans_orphan_source_name_form(self, sa_sync_conn, repo, contribution_repo):
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

        result = detach_contributions(
            person_id,
            contributions=[{"source": "hal", "source_contribution_id": source_contribution_id}],
            conn=sa_sync_conn,
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
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

    def test_preserves_rejected_orphan_name_form(self, sa_sync_conn, repo, contribution_repo):
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

        result = detach_contributions(
            person_id,
            contributions=[{"source": "hal", "source_contribution_id": source_contribution_id}],
            conn=sa_sync_conn,
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
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

    def test_preserves_computed_name_form(self, sa_sync_conn, repo, contribution_repo):
        """Les formes calculées depuis le nom de la personne (source `persons`)
        ne dépendent d'aucune source et survivent au détachement."""
        person_id = create_person("Dupont", "Jean", repo=repo)

        result = detach_contributions(
            person_id,
            contributions=[],
            conn=sa_sync_conn,
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
        )
        assert result["cleaned_forms"] == 0
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM person_name_forms WHERE name_form='jean dupont' AND person_id=:p",
                p=person_id,
            )
            == 1
        )

    def test_keeps_source_name_form_still_backed(self, sa_sync_conn, repo, contribution_repo):
        """Une forme encore portée par un membre d'un groupe de la personne, dans une autre publication, reste quand on détache une seule publication."""
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
        insert_person_group(sa_sync_conn, backing, person_id=person_id)
        repo.add_name_form(person_id, "Dupont Jean", source="hal")

        result = detach_contributions(
            person_id,
            contributions=[{"source": "hal", "source_contribution_id": sa1}],
            conn=sa_sync_conn,
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
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
    def test_raises_on_same_id(self, sa_sync_conn, repo):
        p = _person(sa_sync_conn)
        with pytest.raises(ValidationError, match="elle-même"):
            mark_distinct(p, p, repo=repo)

    def test_inserts_ordered_pair(self, sa_sync_conn, repo):
        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        mark_distinct(p2, p1, repo=repo)
        n = sa_sync_conn.execute(
            text(
                "SELECT COUNT(*) AS n FROM distinct_persons "
                "WHERE person_id_a = :a AND person_id_b = :b"
            ),
            {"a": min(p1, p2), "b": max(p1, p2)},
        ).scalar_one()
        assert n == 1

    def test_idempotent(self, sa_sync_conn, repo):
        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        mark_distinct(p1, p2, repo=repo)
        mark_distinct(p1, p2, repo=repo)
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
    def test_reject_keeps_row_and_sets_status(self, sa_sync_conn, repo, contribution_repo):
        """Rejeter une forme conserve la row (tombstone du verrou de non-retour)."""
        person_id = _person(sa_sync_conn, last_name="Unique", first_name="Name")
        _hal_name_form(sa_sync_conn, person_id, name_form="intrus unique")

        row = update_name_form_status(
            person_id,
            "intrus unique",
            "rejected",
            repo=repo,
            contribution_repo=contribution_repo,
        )

        assert row["status"] == "rejected"
        assert _name_form_status(sa_sync_conn, "intrus unique", person_id) == "rejected"

    def test_confirm_overrides_previous_status(self, sa_sync_conn, repo, contribution_repo):
        person_id = _person(sa_sync_conn, last_name="Alpha", first_name="Beta")
        _hal_name_form(sa_sync_conn, person_id, name_form="alpha b")

        update_name_form_status(
            person_id,
            "alpha b",
            "rejected",
            repo=repo,
            contribution_repo=contribution_repo,
        )
        row = update_name_form_status(
            person_id,
            "alpha b",
            "confirmed",
            repo=repo,
            contribution_repo=contribution_repo,
        )

        assert row["status"] == "confirmed"

    def test_derived_form_status_refused(self, sa_sync_conn, repo, contribution_repo):
        """Une forme dérivée du nom de la personne est confirmée d'office : son statut se refuse."""
        person_id = create_person("Gamma", "Delta", repo=repo)

        with pytest.raises(ConflictError):
            update_name_form_status(
                person_id,
                "delta gamma",
                "rejected",
                repo=repo,
                contribution_repo=contribution_repo,
            )

    def test_unknown_form_raises(self, sa_sync_conn, repo, contribution_repo):
        person_id = create_person("Gamma", "Delta", repo=repo)

        with pytest.raises(NotFoundError):
            update_name_form_status(
                person_id,
                "inexistante xyz",
                "rejected",
                repo=repo,
                contribution_repo=contribution_repo,
            )

    def test_reject_sets_the_lock(self, sa_sync_conn, repo, contribution_repo):
        """Rejeter une forme pose le verrou."""
        pid = _person(sa_sync_conn, last_name="Foreign", first_name="Form")
        _hal_name_form(sa_sync_conn, pid, name_form="intrus etranger")

        update_name_form_status(
            pid,
            "intrus etranger",
            "rejected",
            repo=repo,
            contribution_repo=contribution_repo,
        )

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


class TestNameFormRejectionOnGroups:
    """Le rejet d'une forme de nom détache de la personne les groupes rattachés par le nom dont un membre porte la forme."""

    def test_marks_groups_resolved_by_name(self, sa_sync_conn, repo, contribution_repo):
        p = _person(sa_sync_conn)
        form = {"author_name_normalized": "intrus unique"}
        by_name, name_group = _perimeter_group(sa_sync_conn, p, "name", source_id="hal-n", **form)
        by_initials, initials_group = _perimeter_group(
            sa_sync_conn, p, "compatible_name", source_id="hal-c", **form
        )
        by_orcid, orcid_group = _perimeter_group(
            sa_sync_conn, p, "orcid", source_id="hal-o", **form
        )
        manual, manual_group = _perimeter_group(
            sa_sync_conn, p, "manual", source_id="hal-m", **form
        )
        _hal_name_form(sa_sync_conn, p, name_form="intrus unique")

        update_name_form_status(
            p,
            "intrus unique",
            "rejected",
            repo=repo,
            contribution_repo=contribution_repo,
        )

        assert queued(sa_sync_conn, Queue.GROUP_RESOLUTION) == {name_group, initials_group}
        assert _group_person(sa_sync_conn, name_group) == (p, "name")

    def test_group_under_another_form_is_untouched(self, sa_sync_conn, repo, contribution_repo):
        p = _person(sa_sync_conn)
        _, group = _perimeter_group(
            sa_sync_conn, p, "name", source_id="hal-n", author_name_normalized="jean dupont"
        )
        _hal_name_form(sa_sync_conn, p, name_form="intrus unique")

        update_name_form_status(
            p,
            "intrus unique",
            "rejected",
            repo=repo,
            contribution_repo=contribution_repo,
        )

        assert _group_person(sa_sync_conn, group) == (p, "name")


# ── assign_orphan_contribution ───────────────────────────────────────


class TestAssignOrphanContribution:
    def test_attaches_group_and_pins_all_members(self, sa_sync_conn, repo, contribution_repo):
        """Le groupe passe à la personne en mode `manual` ; tous ses membres sont épinglés à la personne et la reçoivent dans `source_contributions`."""
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        group, hal = _orphan(sa_sync_conn, publication_id)
        source_record_oa = _source_record(
            sa_sync_conn, publication_id, source="openalex", source_id="W1"
        )
        openalex = _jean_dupont_source_contribution(
            sa_sync_conn, source_record_oa, source="openalex"
        )
        add_group_member(sa_sync_conn, group, openalex, source_record_oa)

        assign_orphan_contribution(
            person_id,
            group,
            conn=sa_sync_conn,
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
        )

        assert _group_person(sa_sync_conn, group) == (person_id, "manual")
        assert _pinned_to(sa_sync_conn, [hal, openalex]) == [person_id, person_id]
        assert _publication_evidence(sa_sync_conn, publication_id) == ["address"]
        assert _scalar(
            sa_sync_conn,
            "SELECT sources FROM person_name_forms WHERE name_form = 'jean dupont' AND person_id = :p",
            p=person_id,
        ) == ["hal", "openalex"]

    def test_raises_if_already_assigned(self, sa_sync_conn, repo, contribution_repo):
        """Un groupe déjà rattaché n'est pas repris : le refus nomme la détentrice."""
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        other_id = _person(sa_sync_conn, last_name="Other", first_name="Author")
        group, source_contribution_id = _orphan(sa_sync_conn, insert_publication(sa_sync_conn))
        set_perimeter_author_group(sa_sync_conn, group, person_id=other_id, mode="name")

        with pytest.raises(ContributionAlreadyAssignedError) as exc:
            assign_orphan_contribution(
                person_id,
                group,
                conn=sa_sync_conn,
                perimeter_recompute=_PERIMETER,
                repo=repo,
                contribution_repo=contribution_repo,
            )
        assert exc.value.owner_person_id == other_id
        assert _group_person(sa_sync_conn, group) == (other_id, "name")
        assert _pinned_to(sa_sync_conn, [source_contribution_id]) == [None]

    def test_raises_if_group_missing(self, sa_sync_conn, repo, contribution_repo):
        person_id = _person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            assign_orphan_contribution(
                person_id,
                999999,
                conn=sa_sync_conn,
                perimeter_recompute=_PERIMETER,
                repo=repo,
                contribution_repo=contribution_repo,
            )


class TestReassignRejectedPairUnit:
    """Pré-contrôle de rejet sur les chemins de réassignation orphan-contributions."""

    def test_assign_blocked_when_rejected(self, sa_sync_conn, repo, contribution_repo):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        group, source_contribution_id = _orphan(sa_sync_conn, publication_id)
        insert_rejected_contribution(sa_sync_conn, publication_id, person_id=person_id)

        with pytest.raises(RejectedPairError) as exc:
            assign_orphan_contribution(
                person_id,
                group,
                conn=sa_sync_conn,
                perimeter_recompute=_PERIMETER,
                repo=repo,
                contribution_repo=contribution_repo,
            )
        pair = exc.value.rejected_pairs[0]
        assert pair["publication_id"] == publication_id
        assert pair["person_id"] == person_id
        assert pair["rejected_at"]
        # Rien d'écrit : le pré-contrôle précède l'épinglage.
        assert _pinned_to(sa_sync_conn, [source_contribution_id]) == [None]
        assert _group_person(sa_sync_conn, group) == (None, None)

    def test_assign_forced_unrejects_and_attaches_group(
        self, sa_sync_conn, repo, contribution_repo
    ):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        group, source_contribution_id = _orphan(sa_sync_conn, publication_id)
        insert_rejected_contribution(sa_sync_conn, publication_id, person_id=person_id)

        assign_orphan_contribution(
            person_id,
            group,
            conn=sa_sync_conn,
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
            force=True,
        )

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
        assert _group_person(sa_sync_conn, group) == (person_id, "manual")

    def test_batch_blocked_lists_all_rejected(self, sa_sync_conn, repo, contribution_repo):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        pub1 = insert_publication(sa_sync_conn, "P1")
        pub2 = insert_publication(sa_sync_conn, "P2")
        group1, sa1 = _orphan(sa_sync_conn, pub1, source_id="h-1")
        group2, sa2 = _orphan(sa_sync_conn, pub2, source_id="h-2")
        insert_rejected_contribution(sa_sync_conn, pub1, person_id=person_id)

        with pytest.raises(RejectedPairError) as exc:
            batch_assign_orphan_contributions(
                person_id,
                [group1, group2],
                perimeter_recompute=_PERIMETER,
                repo=repo,
                contribution_repo=contribution_repo,
                conn=sa_sync_conn,
            )
        assert {p["publication_id"] for p in exc.value.rejected_pairs} == {pub1}
        # Rien d'écrit : le pré-contrôle précède l'épinglage.
        assert [_group_person(sa_sync_conn, g) for g in (group1, group2)] == [(None, None)] * 2
        assert _pinned_to(sa_sync_conn, [sa1, sa2]) == [None, None]

    def test_batch_forced_unrejects_all(self, sa_sync_conn, repo, contribution_repo):
        insert_persons_perimeter(sa_sync_conn)
        person_id = _person(sa_sync_conn)
        pub1 = insert_publication(sa_sync_conn, "P1")
        group, _ = _orphan(sa_sync_conn, pub1, source_id="h-1")
        insert_rejected_contribution(sa_sync_conn, pub1, person_id=person_id)

        assigned = batch_assign_orphan_contributions(
            person_id,
            [group],
            perimeter_recompute=_PERIMETER,
            repo=repo,
            contribution_repo=contribution_repo,
            conn=sa_sync_conn,
            force=True,
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
        assert _group_person(sa_sync_conn, group) == (person_id, "manual")


class TestMergePersonRejectedContributions:
    """La fusion transfère les rejets de l'absorbée vers l'absorbante (clé
    identique), avec dédoublonnage sur conflit de PK."""

    def test_transfers_and_dedups(self, sa_sync_conn, repo):
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

        merge_person(target, source, repo=repo)

        rows = sa_sync_conn.execute(
            text(f"SELECT DISTINCT publication_id, person_id FROM ({REJECTED_PAIRS}) rp")
        ).all()
        assert {(r.publication_id, r.person_id) for r in rows} == {
            (publication_shared, target),
            (publication_source_only, target),
        }

    def test_rejection_prevails_over_merged_contribution(self, sa_sync_conn, repo):
        """L'absorbée signe une publication où l'absorbante est rejetée : après fusion, le rejet l'emporte."""
        target = _person(sa_sync_conn, last_name="Cible", first_name="T")
        source = _person(sa_sync_conn, last_name="Source", first_name="S")
        publication = insert_publication(sa_sync_conn, "Conflit")
        _source_record(sa_sync_conn, publication)
        insert_contribution(sa_sync_conn, publication, person_id=source)
        insert_rejected_contribution(sa_sync_conn, publication, person_id=target)

        merge_person(target, source, repo=repo)

        groups_with_person = sa_sync_conn.execute(
            text(
                "SELECT count(*) FROM source_contribution_groups"
                " WHERE publication_id = :publication AND person_id IS NOT NULL"
            ),
            {"publication": publication},
        ).scalar_one()
        assert groups_with_person == 0
