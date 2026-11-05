"""Scénarios d'intégration : casse des identifiants, consolidation d'une publication, types énumérés PostgreSQL, fusion de personnes."""

from functools import partial

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.exc import IntegrityError

from domain.documents.licenses import License
from domain.errors import ConflictError
from infrastructure.db.tables import metadata
from interfaces.api.deps import person_service
from pipeline.ingestion.common.locations import LocationFacts, LocationStore
from pipeline.transformation.publications.lifecycle import refresh
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.persons import (
    insert_hr_record,
    insert_person,
    insert_person_name_form,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.serials import insert_serial
from tests.integration.helpers.sources import insert_source_record

# Fiche RH du département « Test » par défaut.
_rh = insert_hr_record

# Personne normalisée par `lower`.
_person = partial(insert_person, normalizer="lower")

# Publication sans titre normalisé ni type.
_publication = partial(insert_publication, normalize_title=False, doc_type=None)


@pytest.fixture
def service(sa_sync_conn):
    return person_service(sa_sync_conn)


@pytest.fixture
def publication_repo(sa_sync_conn):
    return PublicationStore(sa_sync_conn)


# ── Casse des identifiants de publication ──


def _check_insert(conn, sql: str, params: dict[str, object], *, accepted: bool) -> None:
    """Exécute l'insertion `sql`, acceptée ou refusée par une contrainte selon `accepted`."""
    insert = partial(conn.execute, text(sql), params)
    if accepted:
        insert()
    else:
        with pytest.raises(IntegrityError):
            insert()


class TestIdentifierCase:
    """Un identifiant a la casse de sa forme normalisée : DOI et idHAL en minuscules ; NNT, ORCID et IdRef en majuscules."""

    def test_un_doi_de_publication_en_majuscules_est_refuse(self, sa_sync_conn):
        with pytest.raises(IntegrityError):
            _publication(sa_sync_conn, "Pub A", doi="10.1103/PhysRevC.111.024905")

    @pytest.mark.parametrize(
        ("id_type", "id_value", "accepted"),
        [
            ("nnt", "2021UCFAC022", True),
            ("nnt", "2021ucfac022", False),
            ("patent_publication_number", "WO2011107710", True),
            ("patent_publication_number", "wo2011107710", False),
            ("patent_application_number", "SG11201701523V", True),
            ("patent_application_number", "sg11201701523v", False),
            ("doi", "10.1103/physrevc.111.024905", True),
            ("doi", "10.1103/PhysRevC.111.024905", False),
        ],
    )
    def test_casse_d_un_identifiant_d_enregistrement_source(
        self, sa_sync_conn, id_type, id_value, accepted
    ):
        _check_insert(
            sa_sync_conn,
            """
                INSERT INTO source_record_identifiers (source_record_id, id_type, id_value, role)
                VALUES (:record, CAST(:id_type AS source_identifier_type), :id_value, 'secondary')
            """,
            {
                "record": insert_source_record(sa_sync_conn),
                "id_type": id_type,
                "id_value": id_value,
            },
            accepted=accepted,
        )

    @pytest.mark.parametrize(
        ("id_type", "id_value", "accepted"),
        [
            ("orcid", "0000-0001-2345-678X", True),
            ("orcid", "0000-0001-2345-678x", False),
            ("idref", "05547854X", True),
            ("idref", "05547854x", False),
            ("idhal", "jean-dupont", True),
            ("idhal", "Jean-Dupont", False),
        ],
    )
    def test_casse_d_un_identifiant_de_personne(self, sa_sync_conn, id_type, id_value, accepted):
        _check_insert(
            sa_sync_conn,
            """
                INSERT INTO person_identifiers (person_id, id_type, id_value, source)
                VALUES (:person, :id_type, :id_value, 'manual')
            """,
            {"person": _person(sa_sync_conn), "id_type": id_type, "id_value": id_value},
            accepted=accepted,
        )

    @pytest.mark.parametrize(
        ("identifiers", "accepted"),
        [
            ('{"orcid": "0000-0001-2345-678X", "idhal": "jdupont"}', True),
            ('{"orcid": "0000-0001-2345-678x"}', False),
            ('{"idref": "05547854x"}', False),
            ('{"idhal": "JDupont"}', False),
        ],
    )
    def test_casse_des_identifiants_d_un_contributeur(self, sa_sync_conn, identifiers, accepted):
        _check_insert(
            sa_sync_conn,
            """
                INSERT INTO contributor_information (last_name_normalized, identifiers)
                VALUES ('dupont', CAST(:identifiers AS jsonb))
            """,
            {"identifiers": identifiers},
            accepted=accepted,
        )


# ── Consolidation des publications ──


def _seed_publication(
    repo,
    title: str,
    *,
    publication_year: int = 2024,
    doi: str | None = None,
    doc_type: str = "article",
    oa_status: str = "unknown",
) -> int:
    """Crée une publication par le store, sans matching."""
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
        """`lifecycle.refresh` reprend les métadonnées des enregistrements sources (revue) et déduit le statut open access de leurs copies."""
        serial_id = insert_serial(sa_sync_conn, "Science", oa_model="full_oa")
        publication_id = _seed_publication(publication_repo, "Pub", doi="10.5555/enrich-test")
        record = insert_source_record(
            sa_sync_conn,
            publication_id,
            source="openalex",
            source_id="W999enrich",
            title="Pub",
            publication_year=2024,
            serial_id=serial_id,
        )
        LocationStore(sa_sync_conn).replace_locations(
            record,
            [
                LocationFacts(
                    "https://doi.org/10.5555/enrich-test", license=License.CC_BY, is_oa=True
                )
            ],
        )
        refresh(sa_sync_conn, [publication_id])
        row = sa_sync_conn.execute(
            text("SELECT oa_status, serial_id FROM publications WHERE id = :id"),
            {"id": publication_id},
        ).one()
        assert row.serial_id == serial_id
        assert row.oa_status == "gold"


# ── Types énumérés PostgreSQL ──


class TestPgEnumsMatchDb:
    def test_declared_values_match_db(self, sa_sync_conn):
        """Chaque type énuméré déclaré dans `infrastructure/db/tables.py` a les mêmes valeurs que son type en base.

        Les valeurs viennent du domaine et le type est créé par migration. `alembic check` compare les colonnes, sans le contenu des types.

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


# ── Fusion de personnes ──


class TestMergePersons:
    def test_merge_transfers_name_forms(self, sa_sync_conn, service):
        target = _person(sa_sync_conn, "Dupont", first_name="Jean")
        source = _person(sa_sync_conn, "Dupont", first_name="J.")

        insert_person_name_form(sa_sync_conn, target, name_form="jean dupont", sources=["persons"])
        insert_person_name_form(sa_sync_conn, source, name_form="j dupont", sources=["hal"])

        service.merge_person(target, source)

        # Personne absorbée supprimée.
        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM persons WHERE id = :id"), {"id": source}
            ).first()
            is None
        )

        # La source 'hal' de la forme 'j dupont' passe à la conservée ; aucune forme ne reste à l'absorbée.
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

    def test_merge_transfers_contributions_one_per_publication(self, sa_sync_conn, service):
        """La fusion passe les contributions de l'absorbée à la conservée. Dans une publication où la conservée a déjà une contribution, celle de l'absorbée reste sans personne."""
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

        service.merge_person(target, source)

        persons = dict(conn.execute(text("SELECT id, person_id FROM contributions")).all())
        assert persons[groups["target"]] == target
        assert persons[groups["source_shared"]] is None
        assert persons[groups["source_alone"]] == target

    def test_merge_blocked_if_both_rh(self, sa_sync_conn, service):
        target = _person(sa_sync_conn, "Dupont", first_name="Jean")
        source = _person(sa_sync_conn, "Dupont", first_name="J.")
        _rh(sa_sync_conn, target)
        _rh(sa_sync_conn, source)

        with pytest.raises(ConflictError, match="REFUS de fusion"):
            service.merge_person(target, source)

        # La personne absorbée reste en base.
        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM persons WHERE id = :id"), {"id": source}
            ).first()
            is not None
        )

    def test_merge_allowed_if_only_target_has_rh(self, sa_sync_conn, service):
        target = _person(sa_sync_conn, "Dupont", first_name="Jean")
        source = _person(sa_sync_conn, "Dupont", first_name="J.")
        _rh(sa_sync_conn, target)

        service.merge_person(target, source)

        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM persons WHERE id = :id"), {"id": source}
            ).first()
            is None
        )

    def test_person_with_rh_absorbs_when_requested_as_source(self, sa_sync_conn, service):
        """La personne qui a une fiche RH est conservée, même demandée comme absorbée."""
        requested_target = _person(sa_sync_conn, "Dupont", first_name="J.")
        with_rh = _person(sa_sync_conn, "Dupont", first_name="Jean")
        _rh(sa_sync_conn, with_rh)

        assert service.merge_person(requested_target, with_rh) == (
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
