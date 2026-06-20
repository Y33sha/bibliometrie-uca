"""Idempotence : combinatoire multi-sources (HAL + OpenAlex)."""

from tests.integration.helpers.publications_phase import create_all_publications
from tests.integration.pipeline.idempotence.test_normalize_hal import (
    insert_hal_staging,
    run_normalize_hal,
)
from tests.integration.pipeline.idempotence.test_normalize_openalex import (
    insert_oa_staging,
    run_normalize_oa,
)

SHARED_DOI = "10.9999/shared-article-001"

INTER_HAL_DOCS = [
    {
        "halid": "hal-99100001",
        "doi": SHARED_DOI,
        "raw_data": {
            "docType_s": "ART",
            "title_s": ["Shared Article on Geochemistry"],
            "producedDateY_i": 2024,
            "doiId_s": SHARED_DOI,
            "journalTitle_s": "Geochemistry International",
            "journalIssn_s": "5555-6666",
            "journalPublisher_s": "Geochem Press",
            "authFullNameFormIDPersonIDIDHal_fs": [
                "Alice Dupont_FacetSep_0-0_FacetSep_",
                "Bob Martin_FacetSep_0-0_FacetSep_",
            ],
            "openAccess_bool": True,
        },
    },
    {
        "halid": "hal-99100002",
        "doi": None,
        "raw_data": {
            "docType_s": "REPORT",
            "title_s": ["Un rapport sans DOI"],
            "producedDateY_i": 2024,
            "authFullNameFormIDPersonIDIDHal_fs": ["Alice Dupont_FacetSep_0-0_FacetSep_"],
        },
    },
]

INTER_OA_DOCS = [
    {
        "openalex_id": "W9910000001",
        "doi": SHARED_DOI,
        "raw_data": {
            "id": "https://openalex.org/W9910000001",
            "doi": f"https://doi.org/{SHARED_DOI}",
            "title": "Shared Article on Geochemistry",
            "display_name": "Shared Article on Geochemistry",
            "publication_year": 2024,
            "type": "article",
            "language": "en",
            "primary_location": {
                "source": {
                    "display_name": "Geochemistry International",
                    "type": "journal",
                    "issn": ["5555-6666"],
                    "host_organization_name": "Geochem Press",
                },
            },
            "authorships": [
                {
                    "author": {
                        "id": "https://openalex.org/A991001",
                        "display_name": "Alice Dupont",
                    },
                    "raw_author_name": "Alice Dupont",
                    "author_position": "first",
                    "institutions": [],
                    "raw_affiliation_strings": [],
                },
                {
                    "author": {"id": "https://openalex.org/A991002", "display_name": "Bob Martin"},
                    "raw_author_name": "Bob Martin",
                    "author_position": "last",
                    "institutions": [],
                    "raw_affiliation_strings": [],
                },
            ],
            "open_access": {"oa_status": "gold", "is_oa": True},
            "cited_by_count": 3,
        },
    },
    {
        "openalex_id": "W9910000002",
        "doi": None,
        "raw_data": {
            "id": "https://openalex.org/W9910000002",
            "title": "Another OA-only Article",
            "display_name": "Another OA-only Article",
            "publication_year": 2024,
            "type": "article",
            "primary_location": {"source": None},
            "authorships": [
                {
                    "author": {
                        "id": "https://openalex.org/A991003",
                        "display_name": "Charlie Noid",
                    },
                    "raw_author_name": "Charlie Noid",
                    "author_position": "first",
                    "institutions": [],
                    "raw_affiliation_strings": [],
                },
            ],
            "open_access": {"oa_status": "closed", "is_oa": False},
        },
    },
]


class TestNormalizeInterSourceIdempotence:
    """Normaliser HAL puis OA puis relancer HAL ne crée pas de doublons."""

    def test_hal_then_oa_then_hal_again(self, sa_sync_conn):
        from sqlalchemy import text

        insert_hal_staging(sa_sync_conn, INTER_HAL_DOCS)
        insert_oa_staging(sa_sync_conn, INTER_OA_DOCS)

        # Passe 1 : HAL
        run_normalize_hal(sa_sync_conn)
        create_all_publications(sa_sync_conn)
        pubs_after_hal = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS cnt FROM publications")
        ).scalar_one()

        # Passe 2 : OA
        run_normalize_oa(sa_sync_conn)
        create_all_publications(sa_sync_conn)
        pubs_after_oa = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS cnt FROM publications")
        ).scalar_one()

        # L'article partagé ne doit pas être dupliqué (même DOI)
        cnt = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS cnt FROM publications WHERE lower(doi) = lower(:doi)"),
            {"doi": SHARED_DOI},
        ).scalar_one()
        assert cnt == 1, "L'article partagé ne doit exister qu'une fois"

        # Le rapport HAL sans DOI + l'article OA-only = 2 pubs de plus
        assert pubs_after_oa == pubs_after_hal + 1, (
            f"OA devrait ajouter 1 pub (OA-only), pas plus. "
            f"HAL={pubs_after_hal}, après OA={pubs_after_oa}"
        )

        # Passe 3 : relancer HAL
        insert_hal_staging(sa_sync_conn, INTER_HAL_DOCS)
        run_normalize_hal(sa_sync_conn)
        pubs_after_hal2 = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS cnt FROM publications")
        ).scalar_one()

        assert pubs_after_hal2 == pubs_after_oa, (
            f"Relancer HAL ne devrait rien créer. Avant={pubs_after_oa}, après={pubs_after_hal2}"
        )

    def test_shared_doi_same_journal(self, sa_sync_conn):
        """L'article partagé pointe vers le même journal, pas un doublon."""
        from sqlalchemy import text

        insert_hal_staging(sa_sync_conn, INTER_HAL_DOCS)
        insert_oa_staging(sa_sync_conn, INTER_OA_DOCS)

        run_normalize_hal(sa_sync_conn)
        run_normalize_oa(sa_sync_conn)

        cnt = sa_sync_conn.execute(
            text("""
                SELECT COUNT(*) AS cnt FROM journals
                WHERE title_normalized LIKE '%geochemistry international%'
            """)
        ).scalar_one()
        assert cnt == 1, "Le journal partagé ne doit exister qu'une fois"
