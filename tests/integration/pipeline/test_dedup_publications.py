"""Tests d'intégration — recalcul des métadonnées des publications.

Couvre `refresh_from_sources` sur vraie base PostgreSQL (bibliometrie_test) :
recalcul des champs d'une publication depuis ses `source_records` (priorité
par source, statut OA le plus ouvert, fusion des keywords/topics, etc.).

Chaque test tourne dans une transaction rollbackée (isolation complète). Les
publications sont semées directement via le repo (`create`) — pas de clustering :
la décision d'assignation + réconciliation est testée à l'unité
(`tests/unit/domain/publications/test_reconciliation.py`) et de bout en bout sur
la vraie passe pipeline (`tests/integration/pipeline/test_reprocessing.py`).
"""

from functools import partial

import pytest
from sqlalchemy import text

from domain.normalize import normalize_text
from pipeline.transformation.publications.consolidation import RefreshVerdict, refresh_from_sources
from pipeline.transformation.publications.lifecycle import refresh
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.serials import insert_doi_prefix, insert_publisher
from tests.integration.helpers.sources import insert_source_record

# Enregistrement source de 2024, de titre « Test ».
_source_record = partial(insert_source_record, title="Test", publication_year=2024)

# ── Helpers ──────────────────────────────────────────────────────


def _insert_publication(conn, **kwargs):
    """Sème une publication directement via le repo et retourne son id.

    Pas de cascade de matching : on veut juste une ligne à laquelle rattacher des `source_records`.
    """
    title = kwargs.get("title", "Test Publication")
    return PublicationStore(conn).create(
        title=title,
        title_normalized=kwargs.get("title_normalized") or normalize_text(title),
        doc_type=kwargs.get("doc_type", "article"),
        publication_year=kwargs.get("publication_year", 2024),
        doi=kwargs.get("doi"),
        oa_status=kwargs.get("oa_status", "unknown"),
    )


def _scalar(conn, sql, **binds):
    return conn.execute(text(sql), binds).scalar_one()


# ── Recalcul des métadonnées depuis source_records ──────────


class TestRefreshFromSources:
    """Teste refresh_from_sources : recalcul des métadonnées depuis source_records."""

    def test_language_from_source(self, sa_sync_conn):
        """refresh_from_sources propage les métadonnées des source_records."""
        id1 = _insert_publication(
            sa_sync_conn,
            doi="10.1234/enrich",
            oa_status="closed",
            publication_year=2024,
            doc_type="article",
        )
        _source_record(
            sa_sync_conn, id1, source_id=f"hal-{id1}-closed", language="en", oa_status="closed"
        )
        refresh_from_sources(sa_sync_conn, id1)

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "en"

    def test_editeur_titulaire_du_prefixe_crossref(self, sa_sync_conn):
        """Le titulaire du préfixe l'emporte sur l'éditeur actuel que nomme Crossref."""
        origin = insert_publisher(sa_sync_conn, "Cambridge")
        current = insert_publisher(sa_sync_conn, "Elsevier")
        insert_doi_prefix(sa_sync_conn, "10.1017", ra="Crossref", publisher_id=origin)
        id1 = _insert_publication(sa_sync_conn, doi="10.1017/abc")
        _source_record(
            sa_sync_conn,
            id1,
            source="crossref",
            source_id="10.1017/abc",
            doi="10.1017/abc",
            doc_type="article",
            publisher_id=current,
        )
        refresh_from_sources(sa_sync_conn, id1)

        assert (
            _scalar(sa_sync_conn, "SELECT publisher_id FROM publications WHERE id = :id", id=id1)
            == origin
        )

    def test_editeur_des_sources_sans_prefixe_crossref(self, sa_sync_conn):
        publisher = insert_publisher(sa_sync_conn, "Armand Colin")
        id1 = _insert_publication(sa_sync_conn)
        _source_record(
            sa_sync_conn, id1, source_id=f"hal-{id1}", doc_type="article", publisher_id=publisher
        )
        refresh_from_sources(sa_sync_conn, id1)

        assert (
            _scalar(sa_sync_conn, "SELECT publisher_id FROM publications WHERE id = :id", id=id1)
            == publisher
        )

    def test_oa_status_upgrade(self, sa_sync_conn):
        """Le statut OA le plus ouvert gagne (closed + green → green)."""
        id1 = _insert_publication(sa_sync_conn, doi="10.1234/oa", oa_status="closed")
        _source_record(sa_sync_conn, id1, source_id=f"hal-{id1}-closed", oa_status="closed")
        _source_record(
            sa_sync_conn,
            id1,
            source="openalex",
            source_id=f"openalex-{id1}-green",
            oa_status="green",
        )
        refresh_from_sources(sa_sync_conn, id1)

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "green"

    def test_diamond_always_wins(self, sa_sync_conn):
        """Diamond prime sur tout."""
        id1 = _insert_publication(sa_sync_conn, doi="10.1234/dia", oa_status="gold")
        _source_record(sa_sync_conn, id1, source_id=f"hal-{id1}-gold", oa_status="gold")
        _source_record(
            sa_sync_conn,
            id1,
            source="openalex",
            source_id=f"openalex-{id1}-diamond",
            oa_status="diamond",
        )
        refresh_from_sources(sa_sync_conn, id1)

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "diamond"

    def test_converged_piece_title_deferred_to_parent(self, sa_sync_conn):
        """Pièce convergée (`corrected_by = DATACITE_PACKAGE_PIECE`) : le titre vient du parent
        dataset, pas de la pièce — même quand la pièce précède le parent et partage sa source."""
        conn = sa_sync_conn
        publication = _insert_publication(
            conn, doi="10.9001/set", doc_type="dataset", title="obsolète"
        )
        # Pièce convergée, insérée en premier : sans dépriorisation son titre gagnerait.
        insert_source_record(
            conn,
            publication,
            source="datacite",
            source_id="dc-piece",
            title="README_data.txt",
            doi="10.9001/set",
            publication_year=2024,
            doc_type="dataset",
            corrections={"doi": {"raw": "10.9002/file", "corrected_by": "DATACITE_PACKAGE_PIECE"}},
        )
        # Parent dataset, DOI non corrigé.
        insert_source_record(
            conn,
            publication,
            source="datacite",
            source_id="dc-parent",
            title="Jeu de données phénotypiques",
            doi="10.9001/set",
            publication_year=2024,
            doc_type="dataset",
        )
        refresh_from_sources(conn, publication)
        title = _scalar(conn, "SELECT title FROM publications WHERE id = :id", id=publication)
        assert title == "Jeu de données phénotypiques"

    def test_le_verdict_d_unpaywall_sur_le_doi_l_emporte_sur_les_sources(self, sa_sync_conn):
        id1 = _insert_publication(sa_sync_conn, doi="10.1234/upw", oa_status="unknown")
        sa_sync_conn.execute(
            text(
                "INSERT INTO unpaywall (doi, oa_status, checked_at) VALUES ('10.1234/upw', 'closed', now())"
            )
        )
        _source_record(
            sa_sync_conn,
            id1,
            source="openalex",
            source_id=f"openalex-{id1}-gold",
            doi="10.1234/upw",
            oa_status="gold",
        )
        refresh_from_sources(sa_sync_conn, id1)

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "closed"

    def test_sans_verdict_l_oa_suit_les_sources(self, sa_sync_conn):
        id1 = _insert_publication(sa_sync_conn, doi="10.1234/agg", oa_status="closed")
        _source_record(
            sa_sync_conn,
            id1,
            source="openalex",
            source_id=f"openalex-{id1}-gold",
            doi="10.1234/agg",
            oa_status="gold",
        )
        refresh_from_sources(sa_sync_conn, id1)

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "gold"

    def test_source_priority_hal_over_openalex(self, sa_sync_conn):
        """HAL est prioritaire sur OpenAlex pour les champs scalaires."""
        id1 = _insert_publication(
            sa_sync_conn, doi="10.1234/prio", publication_year=2024, doc_type="article"
        )
        _source_record(
            sa_sync_conn, id1, source="openalex", source_id=f"openalex-{id1}-", language="en"
        )
        _source_record(sa_sync_conn, id1, source_id=f"hal-{id1}-", language="fr")
        refresh_from_sources(sa_sync_conn, id1)

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "fr"

    def test_thesis_priority_theses_over_hal(self, sa_sync_conn):
        """Pour les thèses, theses.fr est prioritaire."""
        id1 = _insert_publication(
            sa_sync_conn, doi="10.1234/thesis-prio", publication_year=2024, doc_type="thesis"
        )
        _source_record(sa_sync_conn, id1, source_id=f"hal-{id1}-", doc_type="thesis", language="en")
        _source_record(
            sa_sync_conn,
            id1,
            source="theses",
            source_id=f"theses-{id1}-",
            doc_type="thesis",
            language="fr",
        )
        refresh_from_sources(sa_sync_conn, id1)

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "fr"

    def test_source_priority_hal_over_scanr(self, sa_sync_conn):
        """Pour les non-thèses, HAL est prioritaire sur ScanR (cf. SOURCE_PRIORITY)."""
        id1 = _insert_publication(
            sa_sync_conn, doi="10.1234/hal-prio", publication_year=2024, doc_type="article"
        )
        _source_record(
            sa_sync_conn, id1, source_id=f"hal-{id1}-", doc_type="article", language="en"
        )
        _source_record(
            sa_sync_conn,
            id1,
            source="scanr",
            source_id=f"scanr-{id1}-",
            doc_type="article",
            language="fr",
        )
        refresh_from_sources(sa_sync_conn, id1)

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "en"

    def test_ongoing_thesis_to_thesis(self, sa_sync_conn):
        """Un ongoing_thesis passe à thesis quand theses.fr le dit."""
        id1 = _insert_publication(sa_sync_conn, publication_year=2024, doc_type="ongoing_thesis")
        _source_record(
            sa_sync_conn, id1, source="theses", source_id=f"theses-{id1}-", doc_type="thesis"
        )
        refresh_from_sources(sa_sync_conn, id1)

        dt = _scalar(sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=id1)
        assert dt == "thesis"

    @pytest.mark.parametrize("out_of_scope_type", ["peer_review", "memoir"])
    def test_out_of_scope_doc_type_dematerializes(self, sa_sync_conn, out_of_scope_type):
        """Un type résolu non admissible supprime la publication ; ses source_records
        sont détachées (FK ON DELETE SET NULL), pas supprimées."""
        conn = sa_sync_conn
        pid = _insert_publication(conn, doc_type="article", publication_year=2024)
        _source_record(
            conn, pid, source="openalex", source_id=f"openalex-{pid}-", doc_type=out_of_scope_type
        )
        assert refresh(conn, pid) == RefreshVerdict.INADMISSIBLE_TYPE

        assert _scalar(conn, "SELECT count(*) FROM publications WHERE id = :id", id=pid) == 0
        source_record_publication = _scalar(
            conn,
            "SELECT publication_id FROM source_records WHERE source_id = :sid",
            sid=f"openalex-{pid}-",
        )
        assert source_record_publication is None

    def test_out_of_scope_deletion_cascades_contributions(self, sa_sync_conn):
        """La suppression d'un type non admissible emporte les groupes de contributions sources (FK ON DELETE CASCADE) ; la personne, elle, survit."""
        conn = sa_sync_conn
        pid = _insert_publication(conn, doc_type="article", publication_year=2024)
        _source_record(
            conn, pid, source="openalex", source_id=f"openalex-{pid}-", doc_type="peer_review"
        )
        person_id = insert_person(conn, "Testauthor", first_name="A", normalizer="lower")
        insert_contribution(conn, pid, person_id=person_id, author_position=1)
        refresh(conn, pid)

        assert _scalar(conn, "SELECT count(*) FROM publications WHERE id = :id", id=pid) == 0
        assert (
            _scalar(
                conn,
                "SELECT count(*) FROM contributions WHERE publication_id = :id",
                id=pid,
            )
            == 0
        )
        assert _scalar(conn, "SELECT count(*) FROM persons WHERE id = :id", id=person_id) == 1

    def test_keywords_merged(self, sa_sync_conn):
        """Les keywords sont fusionnés sans doublons."""
        id1 = _insert_publication(sa_sync_conn, publication_year=2024, doc_type="article")
        _source_record(sa_sync_conn, id1, source_id="hal-kw1", keywords=["python", "data"])
        _source_record(
            sa_sync_conn,
            id1,
            source="openalex",
            source_id="oa-kw1",
            keywords=["Data", "machine learning"],
        )
        refresh_from_sources(sa_sync_conn, id1)

        kw = _scalar(
            sa_sync_conn,
            "SELECT keywords FROM publications_detail WHERE publication_id = :id",
            id=id1,
        )
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
        id1 = _insert_publication(sa_sync_conn, publication_year=2024, doc_type="article")
        _source_record(
            sa_sync_conn,
            id1,
            source_id="hal-tp1",
            topics={"hal_domains": ["info_FacetSep_Informatique [cs]"]},
        )
        _source_record(
            sa_sync_conn,
            id1,
            source="openalex",
            source_id="oa-tp1",
            topics={"concepts": ["AI"], "hal_domains": ["math"]},
        )
        refresh_from_sources(sa_sync_conn, id1)

        topics = _scalar(
            sa_sync_conn,
            "SELECT topics FROM publications_detail WHERE publication_id = :id",
            id=id1,
        )
        # Chaque source garde sa forme sous sa propre clé
        assert topics["hal"] == {"hal_domains": ["info_FacetSep_Informatique [cs]"]}
        assert topics["openalex"] == {"concepts": ["AI"], "hal_domains": ["math"]}

    def test_topics_composite_supports_openalex_list(self, sa_sync_conn):
        """OpenAlex stocke les topics en liste (hiérarchie domain/field/subfield/topic).
        Avant le fix, cette liste était silencieusement ignorée (isinstance dict check).
        Maintenant elle est conservée sous la clé 'openalex'."""
        id1 = _insert_publication(sa_sync_conn, publication_year=2024, doc_type="article")
        _source_record(
            sa_sync_conn,
            id1,
            source="openalex",
            source_id="oa-tp2",
            topics=[
                {
                    "domain": "SS",
                    "field": "Eco",
                    "subfield": "Micro",
                    "topic": "Behav",
                    "score": 0.95,
                }
            ],
        )
        _source_record(
            sa_sync_conn,
            id1,
            source="theses",
            source_id="th-tp2",
            topics={"discipline": "Info", "rameau": ["Algo"]},
        )
        refresh_from_sources(sa_sync_conn, id1)

        topics = _scalar(
            sa_sync_conn,
            "SELECT topics FROM publications_detail WHERE publication_id = :id",
            id=id1,
        )
        # La liste OpenAlex est préservée telle quelle
        assert isinstance(topics["openalex"], list)
        assert topics["openalex"][0]["domain"] == "SS"
        # Et le dict theses.fr aussi
        assert topics["theses"]["discipline"] == "Info"

    def test_is_retracted_or(self, sa_sync_conn):
        """is_retracted = True si au moins une source le dit."""
        id1 = _insert_publication(sa_sync_conn, publication_year=2024, doc_type="article")
        _source_record(sa_sync_conn, id1, source_id="hal-ret1", is_retracted=False)
        _source_record(sa_sync_conn, id1, source="openalex", source_id="oa-ret1", is_retracted=True)
        refresh_from_sources(sa_sync_conn, id1)

        is_ret = _scalar(
            sa_sync_conn, "SELECT is_retracted FROM publications WHERE id = :id", id=id1
        )
        assert is_ret is True
