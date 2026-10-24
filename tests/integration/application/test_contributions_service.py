"""Tests de caractérisation pour application/contributions.py.

Documentent le comportement actuel des fonctions du service pour protéger
contre les régressions lors de refactos ultérieurs.
"""

from functools import partial

import pytest
from sqlalchemy import text

from application.services.contributions.core import (
    delete_orphan_contributions,
    exclude_contribution,
    propagate_in_perimeter_for_addresses,
    reject_pair,
)
from domain.errors import NotFoundError
from infrastructure.repositories import contribution_repository
from infrastructure.sql_fragments import REJECTED_PAIRS
from pipeline.transformation.publications.contributions.build_contributions import (
    insert_missing_contributions,
    prune_orphan_contributions,
)
from pipeline.transformation.publications.contributions.contributions import (
    propagate_contribution_attributes,
)
from pipeline.transformation.structures.perimeter import PerimeterStructures
from pipeline.transformation.structures.perimeter_evidence import (
    SourceContributionPerimeterRecompute,
)
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.config import set_config
from tests.integration.helpers.contributions import (
    group_id_of,
    insert_confirmed_source_contribution,
    insert_contribution,
)
from tests.integration.helpers.groups import add_group_member, insert_group
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


@pytest.fixture
def perimeter_structures():
    return PerimeterStructures()


@pytest.fixture
def repo(sa_sync_conn):
    return contribution_repository(sa_sync_conn)


# ── Helpers (SQLAlchemy text, paramstyle nommé) ───────────────────


# ── exclude_contribution ────────────────────────────────────────


class TestExcludeContribution:
    """exclude_contribution enregistre le rejet dans `rejected_contributions`,
    détache toutes les sources de la paire et supprime la canonique orpheline
    (cœur partagé `reject_pair`)."""

    def test_rejects_deletes_row_and_detaches_source(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        contribution_id = insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        source_contribution_id = insert_source_contribution(
            sa_sync_conn, source_record_id, person_id=person_id
        )

        exclude_contribution(group_id_of(sa_sync_conn, publication_id, person_id), repo=repo)

        # Row contributions supprimée
        assert (
            sa_sync_conn.execute(
                text("SELECT id FROM contributions WHERE id = :id"), {"id": contribution_id}
            ).first()
            is None
        )
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

    def test_rebuild_does_not_recreate_rejected_pair(self, sa_sync_conn, repo):
        """Après rejet, l'insertion canonique re-skippe la paire (anti-join)."""
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        insert_source_contribution(sa_sync_conn, source_record_id, person_id=person_id)

        exclude_contribution(group_id_of(sa_sync_conn, publication_id, person_id), repo=repo)
        # La source est détachée, mais même réattribuée l'anti-join skippe l'INSERT.
        insert_missing_contributions(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text("SELECT id FROM contributions WHERE publication_id = :p AND person_id = :pid"),
                {"p": publication_id, "pid": person_id},
            ).first()
            is None
        )

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            exclude_contribution(999999, repo=repo)

    def test_raises_not_found_for_group_without_person(self, sa_sync_conn, repo):
        """Un groupe sans personne n'est pas une contribution."""
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        source_contribution_id = insert_source_contribution(sa_sync_conn, source_record_id)
        group_id = insert_group(
            sa_sync_conn, publication_id, [(source_contribution_id, source_record_id)]
        )

        with pytest.raises(NotFoundError):
            exclude_contribution(group_id, repo=repo)

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

        exclude_contribution(group_id_of(sa_sync_conn, publication_id, p1), repo=repo)

        # a2 toujours là
        assert (
            sa_sync_conn.execute(
                text("SELECT id FROM contributions WHERE id = :id"), {"id": a2}
            ).first()
            is not None
        )
        # sa2 intacte
        row2 = sa_sync_conn.execute(
            text("SELECT person_id FROM source_contributions WHERE id = :id"), {"id": sa2}
        ).one()
        assert row2.person_id == p2


# ── reject_pair ───────────────────────────────────────────────


class TestRejectPair:
    """reject_pair : cœur partagé — store peuplé, TOUTES les sources de la
    paire détachées, canonique orpheline supprimée, non recréée au rerun."""

    def test_detaches_all_sources_of_pair_and_deletes_canonical(self, sa_sync_conn, repo):
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

        result = reject_pair(publication_id, person_id, repo=repo)

        assert result["detached"] == 2
        assert result["deleted_contributions"] == 1
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
        # Canonique supprimée
        assert (
            sa_sync_conn.execute(
                text("SELECT id FROM contributions WHERE id = :i"), {"i": contribution_id}
            ).first()
            is None
        )

    def test_not_recreated_on_rerun(self, sa_sync_conn, repo):
        """Même si une source ressuscite person_id, l'anti-join skippe l'INSERT."""
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        source_contribution_id = insert_source_contribution(
            sa_sync_conn, source_record_id, person_id=person_id
        )

        reject_pair(publication_id, person_id, repo=repo)
        # Resurrection simulée du lien source (matching non gardé d'un run antérieur).
        sa_sync_conn.execute(
            text("UPDATE source_contributions SET person_id = :pid WHERE id = :i"),
            {"pid": person_id, "i": source_contribution_id},
        )
        insert_missing_contributions(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text("SELECT id FROM contributions WHERE publication_id = :p AND person_id = :pid"),
                {"p": publication_id, "pid": person_id},
            ).first()
            is None
        )

    def test_does_not_touch_other_persons_sources(self, sa_sync_conn, repo):
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        p1 = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        p2 = insert_person(sa_sync_conn, "Martin", first_name="Sophie")
        sa1 = insert_source_contribution(sa_sync_conn, source_record_id, person_id=p1)
        sa2 = insert_source_contribution(
            sa_sync_conn, source_record_id, author_position=1, person_id=p2
        )

        reject_pair(publication_id, p1, repo=repo)

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


# ── delete_orphan_contributions ─────────────────────────────────


class TestDeleteOrphanContributions:
    """delete_orphan_contributions supprime les contributions vérité d'une
    personne qui ne sont attestées par aucune source_contribution active."""

    def test_deletes_contribution_without_source(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        insert_contribution(sa_sync_conn, publication_id, person_id=person_id)

        n = delete_orphan_contributions(person_id, repo=repo)

        assert n == 1
        rows = sa_sync_conn.execute(
            text("SELECT id FROM contributions WHERE person_id = :pid"), {"pid": person_id}
        ).all()
        assert rows == []

    def test_keeps_contribution_with_attesting_source(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        contribution_id = insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        insert_source_contribution(sa_sync_conn, source_record_id, person_id=person_id)

        n = delete_orphan_contributions(person_id, repo=repo)

        assert n == 0
        row = sa_sync_conn.execute(
            text("SELECT id FROM contributions WHERE id = :id"), {"id": contribution_id}
        ).first()
        assert row is not None

    def test_returns_zero_when_no_contributions(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        assert delete_orphan_contributions(person_id, repo=repo) == 0

    def test_scoped_to_person(self, sa_sync_conn, repo):
        """Ne touche que les contributions de la personne demandée."""
        p1 = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        p2 = insert_person(sa_sync_conn, "Martin", first_name="Sophie")
        publication_id = _publication(sa_sync_conn)
        insert_contribution(sa_sync_conn, publication_id, person_id=p1)
        pub2 = _publication(sa_sync_conn, title="Autre")
        insert_contribution(sa_sync_conn, pub2, person_id=p2)

        n = delete_orphan_contributions(p1, repo=repo)

        assert n == 1
        row = sa_sync_conn.execute(
            text("SELECT id FROM contributions WHERE person_id = :pid"), {"pid": p2}
        ).first()
        assert row is not None


# ── prune_orphan_contributions (build, global) ──────────────────


class TestPruneOrphanContributions:
    """`prune_orphan_contributions` (prune de l'étape 1 du build) supprime, toutes
    personnes confondues, les contributions canoniques que plus aucune
    source_contribution n'atteste — inverse d'`insert_missing_contributions`."""

    def test_deletes_orphan(self, sa_sync_conn):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        insert_contribution(sa_sync_conn, publication_id, person_id=person_id)

        n = prune_orphan_contributions(sa_sync_conn)

        assert n == 1
        assert sa_sync_conn.execute(text("SELECT id FROM contributions")).first() is None

    def test_keeps_attested_pair(self, sa_sync_conn):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        contribution_id = insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        insert_source_contribution(sa_sync_conn, source_record_id, person_id=person_id)

        n = prune_orphan_contributions(sa_sync_conn)

        assert n == 0
        assert (
            sa_sync_conn.execute(
                text("SELECT id FROM contributions WHERE id = :id"), {"id": contribution_id}
            ).first()
            is not None
        )

    def test_global_scope_across_persons(self, sa_sync_conn):
        """Prune toutes les orphelines, pas seulement celles d'une personne ;
        une contribution attestée (autre personne, même publication) est préservée."""
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        p_attested = insert_person(sa_sync_conn, "Martin", first_name="Sophie")
        p_orphan1 = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        p_orphan2 = insert_person(sa_sync_conn, "Durand", first_name="Alice")

        insert_contribution(sa_sync_conn, publication_id, person_id=p_attested)
        insert_source_contribution(sa_sync_conn, source_record_id, person_id=p_attested)
        # Deux orphelines sur deux personnes distinctes (aucune source ne les atteste).
        insert_contribution(sa_sync_conn, publication_id, person_id=p_orphan1)
        pub2 = _publication(sa_sync_conn, title="Autre")
        insert_contribution(sa_sync_conn, pub2, person_id=p_orphan2)

        n = prune_orphan_contributions(sa_sync_conn)

        assert n == 2
        rows = sa_sync_conn.execute(text("SELECT person_id FROM contributions")).all()
        assert [r.person_id for r in rows] == [p_attested]


# ── propagate_contribution_attributes (build, passe convergente) ─


class TestPropagateContributionAttributes:
    """La passe unique recompose les attributs depuis les sources et CONVERGE :
    une valeur que plus aucune source n'atteste retombe (le garde `IS NULL`
    historique la figeait). `is_corresponding` est un `bool_or`, sans priorité."""

    @staticmethod
    def _attrs(conn, aid):
        return conn.execute(
            text("SELECT is_corresponding, in_perimeter, roles FROM contributions WHERE id = :id"),
            {"id": aid},
        ).one()

    def test_is_corresponding_is_bool_or(self, sa_sync_conn):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        aid = insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        # Une source dit TRUE (wos), une dit FALSE (hal) → bool_or = TRUE,
        # quelle que soit la « priorité » des sources.
        source_contribution_wos = insert_source_contribution(
            sa_sync_conn, source_record_id, source="wos", person_id=person_id
        )
        source_contribution_hal = insert_source_contribution(
            sa_sync_conn, source_record_id, author_position=1, person_id=person_id
        )
        sa_sync_conn.execute(
            text(
                "UPDATE source_contributions SET is_corresponding = (id = :w) WHERE id IN (:w, :h)"
            ),
            {"w": source_contribution_wos, "h": source_contribution_hal},
        )

        propagate_contribution_attributes(sa_sync_conn)
        assert self._attrs(sa_sync_conn, aid).is_corresponding is True

    def test_converges_when_sources_drop_signal(self, sa_sync_conn):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        aid = insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        source_contribution_id = insert_source_contribution(
            sa_sync_conn, source_record_id, person_id=person_id, in_perimeter=True
        )
        sa_sync_conn.execute(
            text(
                "UPDATE source_contributions "
                "SET is_corresponding = TRUE, roles = ARRAY['author', 'editor'] WHERE id = :id"
            ),
            {"id": source_contribution_id},
        )

        propagate_contribution_attributes(sa_sync_conn)
        before = self._attrs(sa_sync_conn, aid)
        assert (before.is_corresponding, before.in_perimeter, before.roles) == (
            True,
            True,
            ["author", "editor"],
        )

        # Réimport : la source retire corresponding, le périmètre et le rôle editor.
        sa_sync_conn.execute(
            text(
                "UPDATE source_contributions SET is_corresponding = FALSE, perimeter_evidence = '{}', "
                "roles = ARRAY['author'] WHERE id = :id"
            ),
            {"id": source_contribution_id},
        )
        propagate_contribution_attributes(sa_sync_conn)
        after = self._attrs(sa_sync_conn, aid)
        # Convergence : tout retombe (le garde `IS NULL` historique figeait ces valeurs).
        assert (after.is_corresponding, after.in_perimeter, after.roles) == (
            False,
            False,
            ["author"],
        )


# ── propagate_in_perimeter_for_addresses ───────────────────────────────


class TestPropagateUcaForAddresses:
    """propagate_in_perimeter_for_addresses rafraîchit `source_contribution_structures`, puis recalcule les indices du périmètre des contributions sources, de leurs contributions et de leurs publications, après une modification de address_structures.

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

    def _has_contribution(self, conn, publication_id, person_id) -> bool:
        return (
            conn.execute(
                text(
                    "SELECT 1 FROM contributions WHERE publication_id = :publication AND person_id = :pid"
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

    def test_confirmed_source_contribution_prevails_over_rejection_of_another_source_record(
        self, sa_sync_conn
    ):
        """Un enregistrement source rejeté pour P, un autre dont la contribution source est confirmée à P, dans la même publication : la contribution existe."""
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        rejected_source_record = _source_record(sa_sync_conn, publication_id, source_id="hal-rejet")
        confirmed_source_record = _source_record(
            sa_sync_conn, publication_id, source="openalex", source_id="W1"
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO rejected_contributions (source_record_id, person_id) VALUES (:n, :p)"
            ),
            {"n": rejected_source_record, "p": person_id},
        )
        confirmed = insert_source_contribution(
            sa_sync_conn, confirmed_source_record, person_id=person_id
        )
        insert_confirmed_source_contribution(sa_sync_conn, confirmed, person_id=person_id)

        insert_missing_contributions(sa_sync_conn)

        assert self._has_contribution(sa_sync_conn, publication_id, person_id)

    def test_unconfirmed_source_contribution_blocked_by_rejection_of_another_source_record(
        self, sa_sync_conn
    ):
        """Un enregistrement source qui rejoint une publication rejetée pour P ne la rattache pas à P."""
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        rejected_source_record = _source_record(sa_sync_conn, publication_id, source_id="hal-rejet")
        new_source_record = _source_record(
            sa_sync_conn, publication_id, source="openalex", source_id="W2"
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO rejected_contributions (source_record_id, person_id) VALUES (:n, :p)"
            ),
            {"n": rejected_source_record, "p": person_id},
        )
        insert_source_contribution(sa_sync_conn, new_source_record, person_id=person_id)

        insert_missing_contributions(sa_sync_conn)

        assert not self._has_contribution(sa_sync_conn, publication_id, person_id)


# ── Groupes des décisions humaines ──────────────────────────────


def _group_person(conn, group_id):
    return conn.execute(
        text(
            "SELECT person_id, resolution_mode::text AS mode FROM source_contribution_groups WHERE id = :g"
        ),
        {"g": group_id},
    ).one()


class TestHumanDecisionsOnGroups:
    """Les décisions humaines écrivent aussi le groupe, que les lecteurs affichent sans attendre le run suivant."""

    def test_le_rejet_detache_le_groupe(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        insert_source_contribution(sa_sync_conn, source_record_id, person_id=person_id)
        insert_contribution(sa_sync_conn, publication_id, person_id=person_id)
        group_id = group_id_of(sa_sync_conn, publication_id, person_id)

        reject_pair(publication_id, person_id, repo=repo)

        assert _group_person(sa_sync_conn, group_id) == (None, None)

    def test_la_consolidation_rattache_le_groupe_sans_personne(self, sa_sync_conn, repo):
        person_id = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        publication_id = _publication(sa_sync_conn)
        source_record_id = _source_record(sa_sync_conn, publication_id)
        source_contribution_id = insert_source_contribution(
            sa_sync_conn, source_record_id, person_id=person_id
        )
        group_id = insert_group(
            sa_sync_conn, publication_id, [(source_contribution_id, source_record_id)]
        )

        repo.consolidate_contributions(person_id, [publication_id])

        assert _group_person(sa_sync_conn, group_id) == (person_id, "manual")

    def test_la_consolidation_garde_le_groupe_existant_de_la_personne(self, sa_sync_conn, repo):
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

        repo.consolidate_contributions(person_id, [publication_id])

        assert _group_person(sa_sync_conn, other_group) == (None, None)
