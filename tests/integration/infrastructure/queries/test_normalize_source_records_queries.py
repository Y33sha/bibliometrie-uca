"""Tests d'intégration pour `pipeline.ingestion.common.source_records`."""

from functools import partial

from sqlalchemy import text

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from infrastructure.db.queues import Queue
from pipeline.ingestion.common.source_records import (
    SourceRecordStore,
    SourceRecordUpsert,
)
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.serials import insert_publisher
from tests.integration.helpers.staging import insert_staging

# Ligne de staging theses.fr « t-stg ».
_thesis_staging = partial(insert_staging, source="theses", source_id="t-stg")


def _row(staging_id: int, **overrides) -> SourceRecordUpsert:
    defaults = {
        "source": "theses",
        "source_id": "2023ABC001",
        "staging_id": staging_id,
        "title": "Ma thèse",
        "publication_year": 2023,
        "raw_doc_type": "thesis",
    }
    return SourceRecordUpsert(**{**defaults, **overrides})


def _identifier(
    id_type: SourceIdentifierType,
    value: str,
    role: SourceIdentifierRole = SourceIdentifierRole.SECONDARY,
) -> SourceIdentifier:
    return SourceIdentifier(id_type, value, role)


def _identifiers(conn, source_record_id: int) -> list[tuple[str, str, str]]:
    """Renvoie les identifiants écrits de l'enregistrement source : type, valeur, rôle."""
    rows = conn.execute(
        text("""
            SELECT id_type::text, id_value, role::text FROM source_record_identifiers
            WHERE source_record_id = :id ORDER BY id_type, id_value
        """),
        {"id": source_record_id},
    )
    return [tuple(r) for r in rows]


class TestUpsertSourceRecord:
    def test_inserts_new(self, sa_sync_conn):
        staging_id = _thesis_staging(sa_sync_conn)
        source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(
            _row(staging_id, raw_language="fr")
        )
        row = sa_sync_conn.execute(
            text("SELECT title, language FROM source_records WHERE id = :id"),
            {"id": source_record_id},
        ).one()
        assert row.title == "Ma thèse"
        assert row.language == "fr"

    def test_translates_doc_type_and_language_and_keeps_source_values(self, sa_sync_conn):
        staging_id = insert_staging(sa_sync_conn, source="hal", source_id="hal-stg")
        source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(
            _row(
                staging_id,
                source="hal",
                source_id="hal-01",
                raw_doc_type="ART",
                raw_language="English",
            ),
        )
        row = sa_sync_conn.execute(
            text(
                "SELECT doc_type, raw_doc_type, language, raw_language FROM source_records WHERE id = :id"
            ),
            {"id": source_record_id},
        ).one()
        assert tuple(row) == ("article", "ART", "en", "English")

    def test_ebook_platform_is_no_container_title(self, sa_sync_conn):
        staging_id = _thesis_staging(sa_sync_conn)
        store = SourceRecordStore(sa_sync_conn)
        platform = store.upsert_source_record(
            _row(staging_id, container_title="ENS Éditions eBooks")
        )
        book = store.upsert_source_record(
            _row(staging_id, source_id="2023ABC002", container_title="Actes du colloque")
        )
        titles = dict(
            sa_sync_conn.execute(
                text("SELECT id, container_title FROM source_records WHERE id IN (:a, :b)"),
                {"a": platform, "b": book},
            ).all()
        )
        assert titles == {platform: None, book: "Actes du colloque"}

    def test_abstract_keeps_one_version_of_each_formula(self, sa_sync_conn):
        staging_id = _thesis_staging(sa_sync_conn)
        source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(
            _row(
                staging_id,
                abstract="at $$\\sqrt{s}$$ <mml:math><mml:msqrt>s</mml:msqrt></mml:math> = 13 TeV",
            )
        )
        abstract = sa_sync_conn.execute(
            text("SELECT abstract FROM source_records WHERE id = :id"), {"id": source_record_id}
        ).scalar_one()
        assert abstract == "at $$\\sqrt{s}$$ = 13 TeV"

    def test_abstract_loses_its_leading_label(self, sa_sync_conn):
        staging_id = _thesis_staging(sa_sync_conn)
        source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(
            _row(staging_id, abstract="Abstract. The aim of this study")
        )
        abstract = sa_sync_conn.execute(
            text("SELECT abstract FROM source_records WHERE id = :id"), {"id": source_record_id}
        ).scalar_one()
        assert abstract == "The aim of this study"

    def test_reimport_keeps_row_identity(self, sa_sync_conn):
        """La clé `(source, source_id)` traverse les imports : l'id reste stable pour les tables qui la référencent."""
        staging_id = _thesis_staging(sa_sync_conn)
        first = SourceRecordStore(sa_sync_conn).upsert_source_record(_row(staging_id))
        second = SourceRecordStore(sa_sync_conn).upsert_source_record(
            _row(staging_id, raw_language="fr")
        )
        assert first == second

    def test_reimport_overwrites_metadata(self, sa_sync_conn):
        staging_id = _thesis_staging(sa_sync_conn)
        source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(
            _row(staging_id, title="Titre initial", raw_language="en")
        )
        SourceRecordStore(sa_sync_conn).upsert_source_record(
            _row(staging_id, title="Titre corrigé", raw_language="fr")
        )
        row = sa_sync_conn.execute(
            text("SELECT title, language FROM source_records WHERE id = :id"),
            {"id": source_record_id},
        ).one()
        assert row.title == "Titre corrigé"
        assert row.language == "fr"

    def test_reimport_without_a_value_clears_it(self, sa_sync_conn):
        """Le dernier import fait autorité : une valeur absente de l'import courant est effacée."""
        staging_id = _thesis_staging(sa_sync_conn)
        source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(
            _row(
                staging_id, impact={"cited_by_count": 500}, abstract="Un résumé", raw_language="fr"
            ),
        )
        SourceRecordStore(sa_sync_conn).upsert_source_record(_row(staging_id))
        row = sa_sync_conn.execute(
            text("SELECT impact, abstract, language FROM source_records WHERE id = :id"),
            {"id": source_record_id},
        ).one()
        assert row.impact is None
        assert row.abstract is None
        assert row.language is None

    def test_reimport_marks_for_reconciliation(self, sa_sync_conn):
        """La file `source_record_keys_queue` signale la ligne à la phase `publications`, qui recalcule son rattachement."""
        staging_id = _thesis_staging(sa_sync_conn)
        source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(_row(staging_id))
        assert queued(sa_sync_conn, Queue.SOURCE_RECORD_KEYS) == {source_record_id}
        clear(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)
        SourceRecordStore(sa_sync_conn).upsert_source_record(_row(staging_id))
        assert queued(sa_sync_conn, Queue.SOURCE_RECORD_KEYS) == {source_record_id}

    def test_reimport_clears_the_original_values_of_corrections(self, sa_sync_conn):
        """Le réimport efface les valeurs d'origine des corrections : la correction suivante part de la valeur fraîche."""
        staging_id = _thesis_staging(sa_sync_conn)
        source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(_row(staging_id))
        sa_sync_conn.execute(
            text("UPDATE source_records SET corrections = CAST(:raw AS jsonb) WHERE id = :id"),
            {
                "raw": '{"doc_type": {"raw": "conference-paper", "corrected_by": "X"}}',
                "id": source_record_id,
            },
        )
        SourceRecordStore(sa_sync_conn).upsert_source_record(_row(staging_id))
        assert (
            sa_sync_conn.execute(
                text("SELECT corrections FROM source_records WHERE id = :id"),
                {"id": source_record_id},
            ).scalar_one()
            == {}
        )

    def test_unknown_doc_type_gives_other_and_is_logged(self, sa_sync_conn, caplog):
        staging_id = _thesis_staging(sa_sync_conn)
        source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(
            _row(staging_id, raw_doc_type="StudyRegistration")
        )
        assert (
            sa_sync_conn.execute(
                text("SELECT doc_type FROM source_records WHERE id = :id"),
                {"id": source_record_id},
            ).scalar_one()
            == "other"
        )
        assert [r.getMessage() for r in caplog.records if "Type de document" in r.getMessage()] == [
            "Type de document inconnu (theses 2023ABC001) : 'StudyRegistration'"
        ]

    def test_identifiers_normalized_and_rejections_logged(self, sa_sync_conn, caplog):
        """Chaque valeur passe par son value object. Une valeur invalide est écartée et journalisée."""
        staging_id = _thesis_staging(sa_sync_conn)
        source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(
            _row(
                staging_id,
                identifiers=(
                    _identifier(
                        SourceIdentifierType.NNT, "2023abc001", SourceIdentifierRole.PRIMARY
                    ),
                    _identifier(SourceIdentifierType.HAL_ID, "HAL-04123456v2"),
                    _identifier(SourceIdentifierType.HAL_ID, "10995/102143"),
                ),
            ),
        )
        assert _identifiers(sa_sync_conn, source_record_id) == [
            ("hal_id", "hal-04123456", "secondary"),
            ("nnt", "2023ABC001", "primary"),
        ]
        logged = [r.getMessage() for r in caplog.records if "Identifiant écarté" in r.getMessage()]
        assert logged == ["Identifiant écarté (theses 2023ABC001) : hal_id = '10995/102143'"]

    def test_reimport_replaces_identifiers(self, sa_sync_conn):
        """Le dernier import fait autorité. Un identifiant retiré par une règle de correction redevient actif."""
        staging_id = _thesis_staging(sa_sync_conn)
        store = SourceRecordStore(sa_sync_conn)
        source_record_id = store.upsert_source_record(
            _row(staging_id, identifiers=(_identifier(SourceIdentifierType.PMID, "1"),))
        )
        sa_sync_conn.execute(
            text(
                "UPDATE source_record_identifiers SET removed_by = 'X' WHERE source_record_id = :id"
            ),
            {"id": source_record_id},
        )
        store.upsert_source_record(
            _row(
                staging_id,
                identifiers=(
                    _identifier(SourceIdentifierType.PMID, "1"),
                    _identifier(SourceIdentifierType.PMID, "2"),
                ),
            )
        )
        assert sa_sync_conn.execute(
            text("""
                SELECT id_value, removed_by FROM source_record_identifiers
                WHERE source_record_id = :id ORDER BY id_value
            """),
            {"id": source_record_id},
        ).all() == [("1", None), ("2", None)]


class TestPublisher:
    """L'éditeur nommé par la source s'écrit, sauf pour une production hébergée sans être publiée."""

    def _publisher_of(self, conn, *, has_series: bool = False, **overrides) -> int | None:
        publisher_id = insert_publisher(conn, "Éditeur")
        staging_id = insert_staging(conn, source="datacite", source_id="dc-stg")
        defaults = {"source": "datacite", "source_id": "10.9/x", "publisher_id": publisher_id}
        source_record_id = SourceRecordStore(conn).upsert_source_record(
            _row(staging_id, **{**defaults, **overrides}), has_series=has_series
        )
        return conn.execute(
            text("SELECT publisher_id FROM source_records WHERE id = :id"),
            {"id": source_record_id},
        ).scalar_one()

    def test_article_datacite_dans_une_revue(self, sa_sync_conn):
        assert (
            self._publisher_of(sa_sync_conn, raw_doc_type="JournalArticle", has_series=True)
            is not None
        )

    def test_article_datacite_sans_conteneur_heberge_par_un_entrepot(self, sa_sync_conn):
        assert self._publisher_of(sa_sync_conn, raw_doc_type="JournalArticle") is None

    def test_jeu_de_donnees(self, sa_sync_conn):
        assert self._publisher_of(sa_sync_conn, raw_doc_type="Dataset", has_series=True) is None
