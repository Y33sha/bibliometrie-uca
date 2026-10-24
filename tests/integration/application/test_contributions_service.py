"""Tests de caractérisation pour application/contributions.py.

Documentent le comportement actuel des fonctions du service pour protéger
contre les régressions lors de refactos ultérieurs.
"""

from functools import partial

import pytest
from sqlalchemy import text

from application.services.contributions.assign_orphans import (
    assign_orphan_contribution,
    batch_assign_orphan_contributions,
)
from application.services.contributions.core import (
    exclude_contribution,
    propagate_in_perimeter_for_addresses,
    reject_pair,
)
from domain.errors import NotFoundError
from infrastructure.repositories import contribution_repository, person_repository
from infrastructure.sql_fragments import REJECTED_PAIRS
from pipeline.transformation.publications.publication_perimeter import (
    PublicationPerimeterRecompute,
)
from pipeline.transformation.structures.perimeter import PerimeterStructures
from pipeline.transformation.structures.perimeter_evidence import (
    SourceContributionPerimeterRecompute,
)
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.config import set_config
from tests.integration.helpers.contributions import group_id_of, insert_contribution
from tests.integration.helpers.groups import (
    add_group_member,
    insert_group,
    set_perimeter_author_group,
)
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)
from tests.integration.helpers.structures import (
    insert_persons_perimeter,
    refresh_structure_matviews,
)

# Publication « Test Article » sans titre normalisé ni type.
_publication = partial(
    insert_publication, title="Test Article", normalize_title=False, doc_type=None
)

# Enregistrement source de titre « Test », d'identifiant « hal-1 » par défaut.
_source_record = partial(insert_source_record, source_id="hal-1", title="Test")

_PERIMETER_RECOMPUTE = SourceContributionPerimeterRecompute()
_PUBLICATION_PERIMETER_RECOMPUTE = PublicationPerimeterRecompute()


@pytest.fixture
def perimeter_structures():
    return PerimeterStructures()


@pytest.fixture
def repo(sa_sync_conn):
    return contribution_repository(sa_sync_conn)


# ── Helpers (SQLAlchemy text, paramstyle nommé) ───────────────────


# ── exclude_contribution ────────────────────────────────────────


def _group_person(conn, group_id):
    return conn.execute(
        text(
            "SELECT person_id, resolution_mode::text AS mode FROM source_contribution_groups WHERE id = :g"
        ),
        {"g": group_id},
    ).one()


class TestExcludeContribution:
    """exclude_contribution enregistre le rejet dans `rejected_contributions`, puis détache le groupe et toutes les sources de la paire (cœur partagé `reject_pair`)."""

    def test_rejects_and_detaches_group_and_source(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        contribution_id = insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        source_contribution_id = insert_source_contribution(
            sa_sync_conn, source_record_id, person_id=person_id
        )

        exclude_contribution(
            contribution_id,
            conn=sa_sync_conn,
            perimeter_recompute=_PUBLICATION_PERIMETER_RECOMPUTE,
            repo=repo,
        )

        assert _group_person(sa_sync_conn, contribution_id) == (None, None)
        # Rejet enregistré dans le sidecar
        assert (
            sa_sync_conn.execute(
                text(
                    f"SELECT 1 FROM ({REJECTED_PAIRS}) rp "
                    "WHERE publication_id = :publication AND person_id = :pid"
                ),
                {"publication": publication_id, "pid": person_id},
            ).first()
            is not None
        )
        # Vérité source détachée (zombie supprimé) — durabilité en amont
        row = sa_sync_conn.execute(
            text("SELECT person_id FROM source_contributions WHERE id = :id"),
            {"id": source_contribution_id},
        ).one()
        assert row.person_id is None

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            exclude_contribution(
                999999,
                conn=sa_sync_conn,
                perimeter_recompute=_PUBLICATION_PERIMETER_RECOMPUTE,
                repo=repo,
            )

    def test_raises_not_found_for_group_without_person(self, sa_sync_conn, repo):
        """Un groupe sans personne n'est pas une contribution."""
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        source_contribution_id = insert_source_contribution(sa_sync_conn, source_record_id)
        group_id = insert_group(
            sa_sync_conn, publication_id, [(source_contribution_id, source_record_id)]
        )

        with pytest.raises(NotFoundError):
            exclude_contribution(
                group_id,
                conn=sa_sync_conn,
                perimeter_recompute=_PUBLICATION_PERIMETER_RECOMPUTE,
                repo=repo,
            )

    def test_does_not_touch_other_contributions(self, sa_sync_conn, repo):
        """Rejeter une contribution ne touche ni les autres paires ni leurs sources."""
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)

        p1 = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        p2 = insert_person(sa_sync_conn, "Martin", first_name="Sophie")
        insert_contribution(sa_sync_conn, publication_id, person_id=p1)
        a2 = insert_contribution(sa_sync_conn, publication_id, person_id=p2)
        insert_source_contribution(sa_sync_conn, source_record_id, person_id=p1)
        sa2 = insert_source_contribution(
            sa_sync_conn, source_record_id, author_position=1, person_id=p2
        )

        exclude_contribution(
            group_id_of(sa_sync_conn, publication_id, p1),
            conn=sa_sync_conn,
            perimeter_recompute=_PUBLICATION_PERIMETER_RECOMPUTE,
            repo=repo,
        )

        # a2 toujours rattachée
        assert _group_person(sa_sync_conn, a2) == (p2, "manual")
        # sa2 intacte
        row2 = sa_sync_conn.execute(
            text("SELECT person_id FROM source_contributions WHERE id = :id"), {"id": sa2}
        ).one()
        assert row2.person_id == p2


# ── reject_pair ───────────────────────────────────────────────


class TestRejectPair:
    """reject_pair : cœur partagé — store peuplé, groupe et TOUTES les sources de la paire détachés."""

    def test_detaches_group_and_all_sources_of_pair(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        contribution_id = insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        # Deux sources (hal + openalex) attestent la même paire.
        source_record_hal = _source_record(sa_sync_conn, publication_id)
        source_record_oa = _source_record(
            sa_sync_conn, publication_id, source="openalex", source_id="oa-1"
        )
        source_contribution_hal = insert_source_contribution(
            sa_sync_conn, source_record_hal, person_id=person_id
        )
        source_contribution_oa = insert_source_contribution(
            sa_sync_conn, source_record_oa, source="openalex", person_id=person_id
        )

        result = reject_pair(
            publication_id,
            person_id,
            conn=sa_sync_conn,
            perimeter_recompute=_PUBLICATION_PERIMETER_RECOMPUTE,
            repo=repo,
        )

        assert result == {"detached": 2}
        # Store peuplé
        assert (
            sa_sync_conn.execute(
                text(
                    f"SELECT 1 FROM ({REJECTED_PAIRS}) rp "
                    "WHERE publication_id = :publication AND person_id = :pid"
                ),
                {"publication": publication_id, "pid": person_id},
            ).first()
            is not None
        )
        # Toutes les sources détachées
        for source_contribution_id in (source_contribution_hal, source_contribution_oa):
            assert (
                sa_sync_conn.execute(
                    text("SELECT person_id FROM source_contributions WHERE id = :i"),
                    {"i": source_contribution_id},
                ).scalar_one()
                is None
            )
        assert _group_person(sa_sync_conn, contribution_id) == (None, None)

    def test_does_not_touch_other_persons_sources(self, sa_sync_conn, repo):
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        p1 = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        p2 = insert_person(sa_sync_conn, "Martin", first_name="Sophie")
        sa1 = insert_source_contribution(sa_sync_conn, source_record_id, person_id=p1)
        sa2 = insert_source_contribution(
            sa_sync_conn, source_record_id, author_position=1, person_id=p2
        )

        reject_pair(
            publication_id,
            p1,
            conn=sa_sync_conn,
            perimeter_recompute=_PUBLICATION_PERIMETER_RECOMPUTE,
            repo=repo,
        )

        assert (
            sa_sync_conn.execute(
                text("SELECT person_id FROM source_contributions WHERE id = :i"), {"i": sa1}
            ).scalar_one()
            is None
        )
        assert (
            sa_sync_conn.execute(
                text("SELECT person_id FROM source_contributions WHERE id = :i"), {"i": sa2}
            ).scalar_one()
            == p2
        )


# ── propagate_in_perimeter_for_addresses ───────────────────────────────


class TestPropagateUcaForAddresses:
    """propagate_in_perimeter_for_addresses rafraîchit `source_contribution_structures`, puis recalcule les indices du périmètre des contributions sources, de leurs groupes et de leurs publications, après une modification de address_structures.

    `group_structures` est rafraîchie par le pipeline : les tests qui la lisent la rafraîchissent par `refresh_structure_matviews`."""

    def _setup_uca(self, conn):
        """Monte un périmètre UCA minimal + config perimeter_persons/extraction.

        `perimeter_extraction` + `perimeter_structures` sont requis pour que la
        matview `source_contribution_structures` rattache les structures du périmètre.
        """
        from pipeline.transformation.structures.perimeter import refresh_perimeter_structures

        uca_id = insert_persons_perimeter(conn)
        set_config(conn, "perimeter_extraction", "uca")
        refresh_perimeter_structures(conn)
        return uca_id

    def test_noop_on_empty_address_ids(self, sa_sync_conn, repo, perimeter_structures):
        self._setup_uca(sa_sync_conn)
        propagate_in_perimeter_for_addresses(
            sa_sync_conn,
            [],
            repo=repo,
            perimeter_structures=perimeter_structures,
            perimeter_recompute=_PERIMETER_RECOMPUTE,
        )
        # Pas d'assertion négative utile : on vérifie juste qu'aucune exception

    def test_noop_if_no_perimeter_configured(self, sa_sync_conn, repo, perimeter_structures):
        """Si aucun périmètre configuré, la fonction sort sans rien faire."""
        addr_id = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        # Aucun set_config perimeter_persons
        propagate_in_perimeter_for_addresses(
            sa_sync_conn,
            [addr_id],
            repo=repo,
            perimeter_structures=perimeter_structures,
            perimeter_recompute=_PERIMETER_RECOMPUTE,
        )

    def test_sets_in_perimeter_when_address_confirmed(
        self, sa_sync_conn, repo, perimeter_structures
    ):
        uca_id = self._setup_uca(sa_sync_conn)
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        insert_contribution(sa_sync_conn, publication_id, person_id=person_id, roles=["author"])
        source_contribution_id = insert_source_contribution(
            sa_sync_conn, source_record_id, person_id=person_id
        )
        add_group_member(
            sa_sync_conn,
            group_id_of(sa_sync_conn, publication_id, person_id),
            source_contribution_id,
            source_record_id,
        )
        addr_id = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        insert_address_structure(sa_sync_conn, addr_id, structure_id=uca_id, is_confirmed=True)
        insert_source_contribution_address(sa_sync_conn, source_contribution_id, address_id=addr_id)

        propagate_in_perimeter_for_addresses(
            sa_sync_conn,
            [addr_id],
            repo=repo,
            perimeter_structures=perimeter_structures,
            perimeter_recompute=_PERIMETER_RECOMPUTE,
        )
        refresh_structure_matviews(sa_sync_conn)

        sa = sa_sync_conn.execute(
            text(
                "SELECT sc.in_perimeter, "
                "       (SELECT array_agg(structure_id ORDER BY structure_id) "
                "        FROM source_contribution_structures "
                "        WHERE source_contribution_id = sc.id) AS structure_ids "
                "FROM source_contributions sc WHERE sc.id = :id"
            ),
            {"id": source_contribution_id},
        ).one()
        assert sa.in_perimeter is True
        assert sa.structure_ids == [uca_id]

        a = sa_sync_conn.execute(
            text(
                "SELECT a.in_perimeter, "
                "       (SELECT array_agg(structure_id ORDER BY structure_id) "
                "        FROM group_structures "
                "        WHERE group_id = a.id) AS structure_ids "
                "FROM source_contribution_groups a WHERE a.id = :id"
            ),
            {"id": group_id_of(sa_sync_conn, publication_id, person_id)},
        ).one()
        assert a.in_perimeter is True
        assert a.structure_ids == [uca_id]
        assert sa_sync_conn.execute(
            text("SELECT perimeter_evidence::text[] FROM publications WHERE id = :id"),
            {"id": publication_id},
        ).scalar_one() == ["address"]

    def test_unsets_in_perimeter_when_address_rejected(
        self, sa_sync_conn, repo, perimeter_structures
    ):
        """Si l'adresse est rejetée (is_confirmed=False), la structure ne compte pas."""
        uca_id = self._setup_uca(sa_sync_conn)
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        # source_contribution avec un flag in_perimeter déjà TRUE (état avant review)
        source_contribution_id = insert_source_contribution(
            sa_sync_conn, source_record_id, person_id=person_id, in_perimeter=True
        )
        addr_id = insert_address(sa_sync_conn, "Université Clermont Auvergne")
        insert_address_structure(sa_sync_conn, addr_id, structure_id=uca_id, is_confirmed=False)
        insert_source_contribution_address(sa_sync_conn, source_contribution_id, address_id=addr_id)

        propagate_in_perimeter_for_addresses(
            sa_sync_conn,
            [addr_id],
            repo=repo,
            perimeter_structures=perimeter_structures,
            perimeter_recompute=_PERIMETER_RECOMPUTE,
        )
        refresh_structure_matviews(sa_sync_conn)

        sa = sa_sync_conn.execute(
            text(
                "SELECT sc.in_perimeter, "
                "       (SELECT array_agg(structure_id ORDER BY structure_id) "
                "        FROM source_contribution_structures "
                "        WHERE source_contribution_id = sc.id) AS structure_ids "
                "FROM source_contributions sc WHERE sc.id = :id"
            ),
            {"id": source_contribution_id},
        ).one()
        assert sa.in_perimeter is False
        assert sa.structure_ids is None


class TestRejectionAnchoredOnSourceRecords:
    """Un rejet vise les enregistrements sources : il suit leurs regroupements, et une publication est rejetée dès qu'une de ses enregistrements sources l'est."""

    def _rejected(self, conn, publication_id, person_id) -> bool:
        return (
            conn.execute(
                text(
                    f"SELECT 1 FROM ({REJECTED_PAIRS}) rp "
                    "WHERE publication_id = :publication AND person_id = :pid LIMIT 1"
                ),
                {"publication": publication_id, "pid": person_id},
            ).first()
            is not None
        )

    def test_rejection_follows_its_source_record_into_another_publication(self, sa_sync_conn, repo):
        """L'enregistrement source rejeté rejoint une autre publication, qui devient rejetée ; l'ancienne publication peut disparaître sans emporter le rejet."""
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_a = _publication(sa_sync_conn)
        publication_b = _publication(sa_sync_conn)
        source_record_b = _source_record(sa_sync_conn, publication_b, source_id="hal-b")
        repo.reject_contribution(publication_b, person_id)

        sa_sync_conn.execute(
            text("UPDATE source_records SET publication_id = :a WHERE id = :n"),
            {"a": publication_a, "n": source_record_b},
        )
        sa_sync_conn.execute(text("DELETE FROM publications WHERE id = :b"), {"b": publication_b})

        assert self._rejected(sa_sync_conn, publication_a, person_id)


# ── Groupes des décisions humaines ──────────────────────────────


class TestHumanDecisionsOnGroups:
    """Les décisions humaines écrivent aussi le groupe, que les lecteurs affichent sans attendre le run suivant."""

    def test_le_rejet_detache_le_groupe(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        insert_source_contribution(sa_sync_conn, source_record_id, person_id=person_id)
        insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        group_id = group_id_of(sa_sync_conn, publication_id, person_id)

        reject_pair(
            publication_id,
            person_id,
            conn=sa_sync_conn,
            perimeter_recompute=_PUBLICATION_PERIMETER_RECOMPUTE,
            repo=repo,
        )

        assert _group_person(sa_sync_conn, group_id) == (None, None)

    def test_l_epinglage_rattache_le_groupe_sans_personne(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        source_contribution_id = insert_source_contribution(
            sa_sync_conn, source_record_id, person_id=person_id
        )
        group_id = insert_group(
            sa_sync_conn, publication_id, [(source_contribution_id, source_record_id)]
        )

        repo.pin_contributions([source_contribution_id], person_id)

        assert _group_person(sa_sync_conn, group_id) == (person_id, "manual")

    def test_l_epinglage_cede_devant_un_groupe_manuel_de_la_personne(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        source_contribution_id = insert_source_contribution(
            sa_sync_conn, source_record_id, person_id=person_id
        )
        other_group = insert_group(
            sa_sync_conn, publication_id, [(source_contribution_id, source_record_id)]
        )

        repo.pin_contributions([source_contribution_id], person_id)

        assert _group_person(sa_sync_conn, other_group) == (None, None)


def _publication_evidence(conn, publication_id):
    return conn.execute(
        text("SELECT perimeter_evidence::text[] FROM publications WHERE id = :p"),
        {"p": publication_id},
    ).scalar_one()


class TestHumanDecisionsOnPublicationPerimeter:
    """Les décisions humaines recalculent l'appartenance au périmètre des publications dont elles changent les groupes."""

    def test_le_rejet_sort_la_publication_du_perimetre(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = insert_publication(sa_sync_conn, in_perimeter=True)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        insert_source_contribution(sa_sync_conn, source_record_id, person_id=person_id)
        insert_contribution(
            sa_sync_conn, publication_id, person_id=person_id, in_perimeter=True, roles=["author"]
        )

        reject_pair(
            publication_id,
            person_id,
            conn=sa_sync_conn,
            perimeter_recompute=_PUBLICATION_PERIMETER_RECOMPUTE,
            repo=repo,
        )

        assert _publication_evidence(sa_sync_conn, publication_id) == []

    def _orphan(self, conn, source_id):
        """Publication hors périmètre dont le seul groupe, sans personne, est un groupe d'auteur du périmètre. Rend (publication, groupe)."""
        publication_id = insert_publication(conn)
        source_record_id = _source_record(conn, publication_id, source_id=source_id)
        source_contribution_id = insert_source_contribution(
            conn, source_record_id, author_name_normalized="jean dupont"
        )
        group_id = insert_group(conn, publication_id, [(source_contribution_id, source_record_id)])
        set_perimeter_author_group(conn, group_id)
        return publication_id, group_id

    def test_l_attribution_fait_entrer_la_publication(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id, group_id = self._orphan(sa_sync_conn, "hal-orphan")

        assign_orphan_contribution(
            person_id,
            group_id,
            conn=sa_sync_conn,
            perimeter_recompute=_PUBLICATION_PERIMETER_RECOMPUTE,
            repo=person_repository(sa_sync_conn),
            contribution_repo=repo,
        )

        assert _publication_evidence(sa_sync_conn, publication_id) == ["address"]

    def test_l_attribution_en_lot_fait_entrer_les_publications(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        first, first_group = self._orphan(sa_sync_conn, "hal-a")
        second, second_group = self._orphan(sa_sync_conn, "hal-b")

        batch_assign_orphan_contributions(
            person_id,
            [first_group, second_group],
            conn=sa_sync_conn,
            perimeter_recompute=_PUBLICATION_PERIMETER_RECOMPUTE,
            repo=person_repository(sa_sync_conn),
            contribution_repo=repo,
        )

        assert _publication_evidence(sa_sync_conn, first) == ["address"]
        assert _publication_evidence(sa_sync_conn, second) == ["address"]
