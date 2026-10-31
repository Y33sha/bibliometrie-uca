"""Recalcul des métadonnées d'une publication depuis ses enregistrements sources (`refresh_from_sources`) : priorité par source, statut open access tiré des copies, fusion des mots-clés et des topics.

Les publications sont semées par `PublicationStore.create`, sans réconciliation. La réconciliation est testée dans `tests/unit/domain/publications/test_reconciliation.py` et `tests/integration/pipeline/test_reprocessing.py`.
"""

from functools import partial

import pytest
from sqlalchemy import text

from domain.normalize import normalize_text
from domain.publications.licenses import License
from pipeline.ingestion.common.locations import LocationFacts, LocationStore
from pipeline.transformation.publications.consolidation import RefreshVerdict, refresh_from_sources
from pipeline.transformation.publications.lifecycle import refresh
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.serials import insert_doi_prefix, insert_publisher, insert_serial
from tests.integration.helpers.sources import insert_source_record

# Enregistrement source de 2024, de titre « Test ».
_source_record = partial(insert_source_record, title="Test", publication_year=2024)


def _insert_publication(conn, **kwargs):
    """Sème une publication sans réconciliation et renvoie son `id`."""
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


class TestRefreshFromSources:
    def test_language_from_source(self, sa_sync_conn):
        """La langue de la publication est celle de son enregistrement source."""
        id1 = _insert_publication(
            sa_sync_conn,
            doi="10.1234/enrich",
            oa_status="closed",
            publication_year=2024,
            doc_type="article",
        )
        _source_record(sa_sync_conn, id1, source_id=f"hal-{id1}-closed", language="en")
        refresh_from_sources(sa_sync_conn, id1)

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "en"

    def test_editeur_titulaire_du_prefixe_crossref(self, sa_sync_conn):
        """Le titulaire du préfixe l'emporte sur l'éditeur actuel nommé par Crossref."""
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

    def test_oa_status_tire_des_copies(self, sa_sync_conn):
        """Une copie d'archive ouverte donne green."""
        id1 = _insert_publication(sa_sync_conn, doi="10.1234/oa", oa_status="closed")
        hal = _source_record(sa_sync_conn, id1, source_id=f"hal-{id1}")
        LocationStore(sa_sync_conn).replace_locations(
            hal, [LocationFacts("https://hal.science/hal-01607327", is_oa=True)]
        )
        refresh_from_sources(sa_sync_conn, id1)

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "green"

    def test_copie_editeur_sous_licence_dans_une_revue_diamant(self, sa_sync_conn):
        serial = insert_serial(sa_sync_conn, "Revue diamant", oa_model="diamond")
        id1 = _insert_publication(sa_sync_conn, doi="10.1234/dia", oa_status="gold")
        record = _source_record(
            sa_sync_conn, id1, source="crossref", source_id="10.1234/dia", serial_id=serial
        )
        LocationStore(sa_sync_conn).replace_locations(
            record,
            [LocationFacts("https://doi.org/10.1234/dia", license=License.CC_BY, is_oa=True)],
        )
        refresh_from_sources(sa_sync_conn, id1)

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "diamond"

    def test_verdict_d_unpaywall_sans_copie(self, sa_sync_conn):
        id1 = _insert_publication(sa_sync_conn, doi="10.1234/upw", oa_status="unknown")
        sa_sync_conn.execute(
            text(
                "INSERT INTO dois (doi, unpaywall_oa_status, unpaywall_checked_at)"
                " VALUES ('10.1234/upw', 'closed', now())"
            )
        )
        _source_record(
            sa_sync_conn,
            id1,
            source="openalex",
            source_id=f"openalex-{id1}",
            doi="10.1234/upw",
        )
        refresh_from_sources(sa_sync_conn, id1)

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "closed"

    def test_sans_copie_ni_verdict_inconnu(self, sa_sync_conn):
        id1 = _insert_publication(sa_sync_conn, doi="10.1234/agg", oa_status="closed")
        _source_record(
            sa_sync_conn,
            id1,
            source="openalex",
            source_id=f"openalex-{id1}",
            doi="10.1234/agg",
        )
        refresh_from_sources(sa_sync_conn, id1)

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "unknown"

    def test_la_meilleure_copie_ouverte_des_sources(self, sa_sync_conn):
        """La copie de la version éditeur l'emporte sur un dépôt, quelle que soit sa source ; une copie fermée est écartée."""
        id1 = _insert_publication(sa_sync_conn)
        store = LocationStore(sa_sync_conn)
        hal = _source_record(sa_sync_conn, id1, source="hal", source_id=f"hal-{id1}")
        store.replace_locations(
            hal, [LocationFacts("https://hal.science/hal-1", version="acceptedVersion", is_oa=True)]
        )
        openalex = _source_record(sa_sync_conn, id1, source="openalex", source_id=f"W{id1}")
        store.replace_locations(
            openalex,
            [
                LocationFacts("https://closed.org/1", version="publishedVersion", is_oa=False),
                LocationFacts("https://open.org/1", version="publishedVersion", is_oa=True),
            ],
        )
        refresh_from_sources(sa_sync_conn, id1)

        url = _scalar(sa_sync_conn, "SELECT best_copy_url FROM publications WHERE id = :id", id=id1)
        assert url == "https://open.org/1"

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
        """Hors thèses, HAL est prioritaire sur ScanR."""
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
        """Une thèse en cours devient une thèse soutenue quand theses.fr la type `thesis`."""
        id1 = _insert_publication(sa_sync_conn, publication_year=2024, doc_type="ongoing_thesis")
        _source_record(
            sa_sync_conn, id1, source="theses", source_id=f"theses-{id1}-", doc_type="thesis"
        )
        refresh_from_sources(sa_sync_conn, id1)

        dt = _scalar(sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=id1)
        assert dt == "thesis"

    @pytest.mark.parametrize("out_of_scope_type", ["peer_review", "memoir"])
    def test_out_of_scope_doc_type_dematerializes(self, sa_sync_conn, out_of_scope_type):
        """Un type résolu non admissible supprime la publication. Ses enregistrements sources restent, sans publication."""
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
        """La suppression pour type non admissible supprime les contributions de la publication ; la personne reste."""
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
        """Les mots-clés des sources sont fusionnés sans doublon."""
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
        # « data » et « Data » comptent pour un mot-clé, sans distinction de casse.
        assert len(kw) == 3
        lower_kw = [k.lower() for k in kw]
        assert "python" in lower_kw
        assert "data" in lower_kw
        assert "machine learning" in lower_kw

    def test_topics_composite_by_source(self, sa_sync_conn):
        """Les topics de la publication sont rangés par source, chacun sous sa forme d'origine, même quand deux sources utilisent la même clé."""
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
        assert topics["hal"] == {"hal_domains": ["info_FacetSep_Informatique [cs]"]}
        assert topics["openalex"] == {"concepts": ["AI"], "hal_domains": ["math"]}

    def test_topics_composite_supports_openalex_list(self, sa_sync_conn):
        """Les topics OpenAlex, une liste (hiérarchie domain/field/subfield/topic), sont gardés tels quels sous la clé `openalex`, à côté du dictionnaire de theses.fr."""
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
        assert isinstance(topics["openalex"], list)
        assert topics["openalex"][0]["domain"] == "SS"
        assert topics["theses"]["discipline"] == "Info"

    def test_is_retracted_or(self, sa_sync_conn):
        """La publication est rétractée dès qu'une source la déclare rétractée."""
        id1 = _insert_publication(sa_sync_conn, publication_year=2024, doc_type="article")
        _source_record(sa_sync_conn, id1, source_id="hal-ret1", is_retracted=False)
        _source_record(sa_sync_conn, id1, source="openalex", source_id="oa-ret1", is_retracted=True)
        refresh_from_sources(sa_sync_conn, id1)

        is_ret = _scalar(
            sa_sync_conn, "SELECT is_retracted FROM publications WHERE id = :id", id=id1
        )
        assert is_ret is True
