"""Tests d'intégration — nécessitent la base bibliometrie_test."""

from functools import partial

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.exc import IntegrityError

from application.services.persons.core import merge_person
from domain.errors import ConflictError
from infrastructure.db.tables import metadata
from infrastructure.repositories import person_repository
from pipeline.transformation.publications.consolidation import refresh_from_sources
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.journals import insert_journal
from tests.integration.helpers.persons import (
    insert_hr_record,
    insert_person,
    insert_person_name_form,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record

# Fiche RH du département « Test » par défaut.
_rh = partial(insert_hr_record, department_name="Test")

# Personne normalisée par `lower`.
_person = partial(insert_person, normalizer="lower")

# Publication sans titre normalisé ni type.
_publication = partial(insert_publication, normalize_title=False, doc_type=None)


@pytest.fixture
def person_repo(sa_sync_conn):
    return person_repository(sa_sync_conn)


@pytest.fixture
def publication_repo(sa_sync_conn):
    return PublicationStore(sa_sync_conn)


# ── Helpers ──


# ── DOI case-insensitive (bug corrigé 2026-03-31) ──


class TestDoiCaseInsensitive:
    """La contrainte unique sur DOI est case-insensitive (lower(doi)).
    Les lookups doivent aussi être case-insensitive."""

    def test_unique_constraint_blocks_case_variant(self, sa_sync_conn):
        _publication(sa_sync_conn, "Pub A", doi="10.1103/PhysRevC.111.024905")
        with pytest.raises(IntegrityError):
            _publication(sa_sync_conn, "Pub B", doi="10.1103/physrevc.111.024905")

    def test_lookup_finds_case_variant(self, sa_sync_conn):
        _publication(sa_sync_conn, "Pub A", doi="10.1103/PhysRevC.111.024905")
        result = sa_sync_conn.execute(
            text("SELECT id FROM publications WHERE lower(doi) = lower(:doi)"),
            {"doi": "10.1103/physrevc.111.024905"},
        ).first()
        assert result is not None


# ── Service publications ──


def _seed_publication(
    repo,
    title: str,
    *,
    publication_year: int = 2024,
    doi: str | None = None,
    doc_type: str = "article",
    oa_status: str = "unknown",
) -> int:
    """Sème une publication directement via le repo (sans cascade de matching)."""
    return repo.create(
        title=title,
        title_normalized=title.lower(),
        doc_type=doc_type,
        publication_year=publication_year,
        doi=doi,
        oa_status=oa_status,
    )


class TestRefreshFromSources:
    def test_enrich_via_refresh(self, sa_sync_conn, publication_repo):
        """refresh_from_sources enrichit les métadonnées depuis les source_records."""
        journal_id = insert_journal(sa_sync_conn, "Science")
        publication_id = _seed_publication(publication_repo, "Pub", doi="10.5555/enrich-test")
        insert_source_record(
            sa_sync_conn,
            publication_id,
            source="openalex",
            source_id="W999enrich",
            title="Pub",
            publication_year=2024,
            journal_id=journal_id,
            oa_status="gold",
        )
        refresh_from_sources(sa_sync_conn, publication_id)
        row = sa_sync_conn.execute(
            text("SELECT oa_status, journal_id FROM publications WHERE id = :id"),
            {"id": publication_id},
        ).one()
        assert row.journal_id == journal_id
        assert row.oa_status == "gold"


# ── Cohérence des enums Postgres ──


class TestPgEnumsMatchDb:
    def test_declared_values_match_db(self, sa_sync_conn):
        """Chaque enum Postgres porté par `infrastructure/db/tables.py` déclare le vocabulaire de son type en base.

        Les valeurs viennent du domaine et le type est créé par migration : ce test ferme la boucle entre les trois. `alembic check` ne l'ouvre pas — il compare les colonnes, pas le contenu des types.

        Une valeur en base et non déclarée casse la lecture de la colonne par SQLAlchemy (`LookupError`) ; une valeur déclarée et absente de la base casse l'écriture.
        """
        declared = {
            col.type.name: set(col.type.enums)
            for table in metadata.tables.values()
            for col in table.columns
            if isinstance(col.type, PgEnum) and col.type.name
        }
        assert declared, "Aucun enum trouvé dans la MetaData : le relevé ne mesure plus rien."

        divergent = {}
        for name, values in declared.items():
            in_db = set(
                sa_sync_conn.execute(
                    text(f"SELECT unnest(enum_range(NULL::{name}))::text")
                ).scalars()
            )
            if values != in_db:
                divergent[name] = (sorted(values - in_db), sorted(in_db - values))

        assert not divergent, "Désynchronisation tables.py/DB :\n" + "\n".join(
            f"  {name} : déclaré et absent de la base {missing}, en base et non déclaré {extra}"
            for name, (missing, extra) in divergent.items()
        )


# ── Merge persons ──


class TestMergePersons:
    def test_merge_transfers_name_forms(self, sa_sync_conn, person_repo):
        target = _person(sa_sync_conn, "Dupont", first_name="Jean")
        source = _person(sa_sync_conn, "Dupont", first_name="J.")

        insert_person_name_form(sa_sync_conn, target, name_form="jean dupont", sources=["persons"])
        insert_person_name_form(sa_sync_conn, source, name_form="j dupont", sources=["hal"])

        merge_person(target, source, repo=person_repo)

        # Source supprimée
        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM persons WHERE id = :id"), {"id": source}
            ).first()
            is None
        )

        # Name forms transférées : la source 'hal' attachée à `source` est
        # remontée sur la row `(j dupont, target)` après merge ; plus aucune
        # row ne référence l'id `source`.
        row = sa_sync_conn.execute(
            text(
                "SELECT sources FROM person_name_forms "
                "WHERE name_form = 'j dupont' AND person_id = :pid"
            ),
            {"pid": target},
        ).one()
        assert "hal" in row.sources
        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM person_name_forms WHERE person_id = :pid"),
                {"pid": source},
            ).first()
            is None
        )

    def test_merge_transfers_contributions_one_per_publication(self, sa_sync_conn, person_repo):
        """Régression : les groupes de contributions sources référencent la personne. Dans une publication où la conservée a déjà un groupe, le groupe de l'absorbée perd sa personne et garde ses contributions sources."""
        conn = sa_sync_conn
        target = _person(conn, "Dupont", first_name="Jean")
        source = _person(conn, "Dupont", first_name="J.")
        shared, alone = insert_publication(conn), insert_publication(conn)
        groups = {}
        for key, publication, person in (
            ("target", shared, target),
            ("source_shared", shared, source),
            ("source_alone", alone, source),
        ):
            groups[key] = conn.execute(
                text(
                    "INSERT INTO contributions (publication_id, person_id, resolution_mode)"
                    " VALUES (:p, :person, 'name') RETURNING id"
                ),
                {"p": publication, "person": person},
            ).scalar_one()

        merge_person(target, source, repo=person_repo)

        persons = dict(conn.execute(text("SELECT id, person_id FROM contributions")).all())
        assert persons[groups["target"]] == target
        assert persons[groups["source_shared"]] is None
        assert persons[groups["source_alone"]] == target

    def test_merge_blocked_if_both_rh(self, sa_sync_conn, person_repo):
        target = _person(sa_sync_conn, "Dupont", first_name="Jean")
        source = _person(sa_sync_conn, "Dupont", first_name="J.")
        _rh(sa_sync_conn, target)
        _rh(sa_sync_conn, source)

        with pytest.raises(ConflictError, match="REFUS de fusion"):
            merge_person(target, source, repo=person_repo)

        # Les deux personnes existent toujours
        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM persons WHERE id = :id"), {"id": source}
            ).first()
            is not None
        )

    def test_merge_allowed_if_only_target_has_rh(self, sa_sync_conn, person_repo):
        target = _person(sa_sync_conn, "Dupont", first_name="Jean")
        source = _person(sa_sync_conn, "Dupont", first_name="J.")
        _rh(sa_sync_conn, target)

        merge_person(target, source, repo=person_repo)

        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM persons WHERE id = :id"), {"id": source}
            ).first()
            is None
        )

    def test_person_with_rh_absorbs_when_requested_as_source(self, sa_sync_conn, person_repo):
        """La personne qui a une fiche RH est conservée, même demandée comme absorbée."""
        requested_target = _person(sa_sync_conn, "Dupont", first_name="J.")
        with_rh = _person(sa_sync_conn, "Dupont", first_name="Jean")
        _rh(sa_sync_conn, with_rh)

        assert merge_person(requested_target, with_rh, repo=person_repo) == (
            with_rh,
            requested_target,
        )

        remaining = sa_sync_conn.execute(
            text("SELECT id FROM persons WHERE id = ANY(:ids)"),
            {"ids": [requested_target, with_rh]},
        ).scalars()
        assert list(remaining) == [with_rh]
        assert (
            sa_sync_conn.execute(
                text("SELECT person_id FROM hr_records WHERE person_id = :id"), {"id": with_rh}
            ).scalar()
            == with_rh
        )
