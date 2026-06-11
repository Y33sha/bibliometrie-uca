"""Tests d'intégration — recalcul des métadonnées canoniques.

Couvre `refresh_from_sources` sur vraie base PostgreSQL (bibliometrie_test) :
recalcul des champs d'une publication depuis ses `source_publications` (priorité
par source, statut OA le plus ouvert, fusion des keywords/topics, etc.).

Chaque test tourne dans une transaction rollbackée (isolation complète). Les
publications sont semées directement via le repo (`create`) — pas de cascade de
matching : la déduplication est testée à l'unité
(`tests/unit/domain/publications/test_deduplication.py`) et sur la vraie entrée
pipeline (`tests/integration/infrastructure/queries/test_create_queries.py`).
"""

from sqlalchemy import text

from application.publications import refresh_from_sources
from domain.normalize import normalize_text
from infrastructure.repositories import publication_repository

# ── Helpers ──────────────────────────────────────────────────────


def _insert_pub(conn, **kwargs):
    """Sème une publication directement via le repo et retourne son id.

    Pas de cascade de matching : on veut juste une ligne à laquelle rattacher
    des `source_publications`.
    """
    title = kwargs.get("title", "Test Publication")
    return publication_repository(conn).create(
        title=title,
        title_normalized=kwargs.get("title_normalized") or normalize_text(title),
        doc_type=kwargs.get("doc_type", "article"),
        pub_year=kwargs.get("pub_year", 2024),
        doi=kwargs.get("doi"),
        oa_status=kwargs.get("oa_status", "unknown"),
        journal_id=kwargs.get("journal_id"),
        container_title=kwargs.get("container_title"),
        language=kwargs.get("language"),
    )


def _scalar(conn, sql, **binds):
    return conn.execute(text(sql), binds).scalar_one()


# ── Recalcul des métadonnées depuis source_publications ──────────


class TestRefreshFromSources:
    """Teste refresh_from_sources : recalcul des métadonnées depuis source_publications."""

    def _insert_sd(self, conn, pub_id, source, **kwargs):
        """Insère un source_document rattaché à pub_id."""
        conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year, publication_id,
                                              doc_type, oa_status, language, journal_id)
                VALUES (:source, :source_id, 'Test', 2024, :pub_id,
                        :doc_type, :oa_status, :language, :journal_id)
                """
            ),
            {
                "source": source,
                "source_id": f"{source}-{pub_id}-{kwargs.get('oa_status', '')}",
                "pub_id": pub_id,
                "doc_type": kwargs.get("doc_type"),
                "oa_status": kwargs.get("oa_status"),
                "language": kwargs.get("language"),
                "journal_id": kwargs.get("journal_id"),
            },
        )

    def test_language_from_source(self, sa_sync_conn):
        """refresh_from_sources propage les métadonnées des source_publications."""
        id1 = _insert_pub(
            sa_sync_conn,
            doi="10.1234/enrich",
            oa_status="closed",
            pub_year=2024,
            doc_type="article",
        )
        self._insert_sd(sa_sync_conn, id1, "hal", language="en", oa_status="closed")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "en"

    def test_oa_status_upgrade(self, sa_sync_conn):
        """Le statut OA le plus ouvert gagne (closed + green → green)."""
        id1 = _insert_pub(sa_sync_conn, doi="10.1234/oa", oa_status="closed")
        self._insert_sd(sa_sync_conn, id1, "hal", oa_status="closed")
        self._insert_sd(sa_sync_conn, id1, "openalex", oa_status="green")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "green"

    def test_diamond_always_wins(self, sa_sync_conn):
        """Diamond prime sur tout."""
        id1 = _insert_pub(sa_sync_conn, doi="10.1234/dia", oa_status="gold")
        self._insert_sd(sa_sync_conn, id1, "hal", oa_status="gold")
        self._insert_sd(sa_sync_conn, id1, "openalex", oa_status="diamond")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "diamond"

    def test_source_priority_hal_over_openalex(self, sa_sync_conn):
        """HAL est prioritaire sur OpenAlex pour les champs scalaires."""
        id1 = _insert_pub(sa_sync_conn, doi="10.1234/prio", pub_year=2024, doc_type="article")
        self._insert_sd(sa_sync_conn, id1, "openalex", language="en")
        self._insert_sd(sa_sync_conn, id1, "hal", language="fr")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "fr"

    def test_thesis_priority_theses_over_hal(self, sa_sync_conn):
        """Pour les thèses, theses.fr est prioritaire."""
        id1 = _insert_pub(sa_sync_conn, doi="10.1234/thesis-prio", pub_year=2024, doc_type="thesis")
        self._insert_sd(sa_sync_conn, id1, "hal", language="en", doc_type="THESE")
        self._insert_sd(sa_sync_conn, id1, "theses", language="fr", doc_type="thesis")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "fr"

    def test_source_priority_scanr_over_hal(self, sa_sync_conn):
        """Pour les non-thèses, ScanR est prioritaire sur HAL."""
        id1 = _insert_pub(sa_sync_conn, doi="10.1234/scanr-prio", pub_year=2024, doc_type="article")
        self._insert_sd(sa_sync_conn, id1, "hal", language="en", doc_type="ART")
        self._insert_sd(sa_sync_conn, id1, "scanr", language="fr", doc_type="article")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "fr"

    def test_doc_type_mapping(self, sa_sync_conn):
        """Les doc_types bruts sont mappés vers l'enum canonique."""
        id1 = _insert_pub(sa_sync_conn, pub_year=2024, doc_type="other")
        self._insert_sd(sa_sync_conn, id1, "hal", doc_type="ART")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        dt = _scalar(sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=id1)
        assert dt == "article"

    def test_ongoing_thesis_to_thesis(self, sa_sync_conn):
        """Un ongoing_thesis passe à thesis quand theses.fr le dit."""
        id1 = _insert_pub(sa_sync_conn, pub_year=2024, doc_type="ongoing_thesis")
        self._insert_sd(sa_sync_conn, id1, "theses", doc_type="thesis")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        dt = _scalar(sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=id1)
        assert dt == "thesis"

    def test_keywords_merged(self, sa_sync_conn):
        """Les keywords sont fusionnés sans doublons."""
        id1 = _insert_pub(sa_sync_conn, pub_year=2024, doc_type="article")
        sa_sync_conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, keywords)
                VALUES ('hal', 'hal-kw1', 'Test', 2024, :p, ARRAY['python', 'data']),
                       ('openalex', 'oa-kw1', 'Test', 2024, :p, ARRAY['Data', 'machine learning'])
                """
            ),
            {"p": id1},
        )
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        kw = _scalar(sa_sync_conn, "SELECT keywords FROM publications WHERE id = :id", id=id1)
        # 'data' et 'Data' sont dédupliqués (case-insensitive), 3 mots-clés
        assert len(kw) == 3
        lower_kw = [k.lower() for k in kw]
        assert "python" in lower_kw
        assert "data" in lower_kw
        assert "machine learning" in lower_kw

    def test_topics_composite_by_source(self, sa_sync_conn):
        """publications.topics est un composite {source: data}, chaque source
        garde sa forme native. Rien n'est perdu (même en cas de clés en
        conflit entre sources, avant le fix les données OpenAlex étaient
        silencieusement perdues si HAL était prioritaire)."""
        id1 = _insert_pub(sa_sync_conn, pub_year=2024, doc_type="article")
        sa_sync_conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, topics)
                VALUES ('hal', 'hal-tp1', 'Test', 2024, :p, '{"hal_domains": ["info"]}'),
                       ('openalex', 'oa-tp1', 'Test', 2024, :p,
                        '{"concepts": ["AI"], "hal_domains": ["math"]}')
                """
            ),
            {"p": id1},
        )
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        topics = _scalar(sa_sync_conn, "SELECT topics FROM publications WHERE id = :id", id=id1)
        # Chaque source garde sa forme sous sa propre clé
        assert topics["hal"] == {"hal_domains": ["info"]}
        assert topics["openalex"] == {"concepts": ["AI"], "hal_domains": ["math"]}

    def test_topics_composite_supports_openalex_list(self, sa_sync_conn):
        """OpenAlex stocke les topics en liste (hiérarchie domain/field/subfield/topic).
        Avant le fix, cette liste était silencieusement ignorée (isinstance dict check).
        Maintenant elle est conservée sous la clé 'openalex'."""
        id1 = _insert_pub(sa_sync_conn, pub_year=2024, doc_type="article")
        sa_sync_conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, topics)
                VALUES ('openalex', 'oa-tp2', 'Test', 2024, :p,
                        '[{"domain": "SS", "field": "Eco", "subfield": "Micro", "topic": "Behav", "score": 0.95}]'::jsonb),
                       ('theses', 'th-tp2', 'Test', 2024, :p,
                        '{"discipline": "Info", "rameau": ["Algo"]}')
                """
            ),
            {"p": id1},
        )
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        topics = _scalar(sa_sync_conn, "SELECT topics FROM publications WHERE id = :id", id=id1)
        # La liste OpenAlex est préservée telle quelle
        assert isinstance(topics["openalex"], list)
        assert topics["openalex"][0]["domain"] == "SS"
        # Et le dict theses.fr aussi
        assert topics["theses"]["discipline"] == "Info"

    def test_is_retracted_or(self, sa_sync_conn):
        """is_retracted = True si au moins une source le dit."""
        id1 = _insert_pub(sa_sync_conn, pub_year=2024, doc_type="article")
        sa_sync_conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, is_retracted)
                VALUES ('hal', 'hal-ret1', 'Test', 2024, :p, FALSE),
                       ('openalex', 'oa-ret1', 'Test', 2024, :p, TRUE)
                """
            ),
            {"p": id1},
        )
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        is_ret = _scalar(
            sa_sync_conn, "SELECT is_retracted FROM publications WHERE id = :id", id=id1
        )
        assert is_ret is True
