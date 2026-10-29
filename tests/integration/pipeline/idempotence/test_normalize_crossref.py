"""Idempotence de la normalisation Crossref.

Crossref est moissonné par DOI (`fetch_missing_doi`), puis normalisé en enregistrements sources et contributions sources. Les affiliations textuelles deviennent des adresses (`addresses`, `source_contribution_addresses`), d'où la phase `affiliations` tire les indices de périmètre des contributions sources Crossref.

Le module vérifie qu'une seconde normalisation laisse les comptes inchangés, liens aux adresses compris, et qu'un document sans contenu, sans DOI, ou sans titre ni année est marqué traité sans insertion.
"""

from __future__ import annotations

from functools import partial

from tests.integration.helpers.publications_phase import create_all_publications
from tests.integration.helpers.staging import insert_staging, normalize_pending

# Ligne de staging Crossref à traiter.
_crossref_staging = partial(insert_staging, source="crossref", processed=False)

CROSSREF_STAGING_DOCS = [
    {
        # Cas nominal : article avec DOI, titre, année, auteurs avec ORCID et affiliations textuelles.
        "source_id": "10.9999/cr-test-001",
        "doi": "10.9999/cr-test-001",
        "raw_data": {
            "DOI": "10.9999/cr-test-001",
            "title": ["A CrossRef Article on Topology"],
            "published": {"date-parts": [[2024]]},
            "container-title": ["Topology Quarterly"],
            "ISSN": ["1111-2222"],
            "publisher": "Topology Press",
            "language": "EN",
            "abstract": "<jats:p>Abstract <jats:bold>text</jats:bold>.</jats:p>",
            "subject": ["mathematics", "topology"],
            "is-referenced-by-count": 7,
            "volume": "5",
            "issue": "2",
            "page": "100-120",
            "author": [
                {
                    "given": "Alice",
                    "family": "Curie",
                    "ORCID": "http://orcid.org/0000-0002-1825-0097",
                    "affiliation": [{"name": "UCA"}],
                    "sequence": "first",
                },
                {
                    "given": "Bob",
                    "family": "Pasteur",
                    "affiliation": [{"name": "CNRS"}],
                    "sequence": "additional",
                },
            ],
        },
    },
    {
        # Cas minimal : DOI, titre et année, sans auteurs ni revue.
        "source_id": "10.9999/cr-test-002",
        "doi": "10.9999/cr-test-002",
        "raw_data": {
            "DOI": "10.9999/cr-test-002",
            "title": ["A Minimal CrossRef Record"],
            "published": {"date-parts": [[2023]]},
        },
    },
]


def _insert_crossref_staging(conn, docs):
    for doc in docs:
        insert_staging(
            conn,
            "crossref",
            source_id=doc["source_id"],
            doi=doc["doi"],
            raw_data=doc["raw_data"],
            processed=False,
            upsert="raw_data",
        )


def _run_normalize_crossref(conn):
    return normalize_pending(conn, "crossref")


def _count_crossref(conn) -> dict[str, int]:
    from sqlalchemy import text

    counts: dict[str, int] = {}
    counts["sp"] = conn.execute(
        text("SELECT COUNT(*) AS n FROM source_records WHERE source = 'crossref'")
    ).scalar_one()
    counts["sa"] = conn.execute(
        text("SELECT COUNT(*) AS n FROM source_contributions WHERE source = 'crossref'")
    ).scalar_one()
    counts["sca"] = conn.execute(
        text("""
            SELECT COUNT(*) AS n
            FROM source_contribution_addresses sca
            JOIN source_contributions sc ON sc.id = sca.source_contribution_id
            WHERE sc.source = 'crossref'
        """)
    ).scalar_one()
    counts["publications"] = conn.execute(
        text("SELECT COUNT(*) AS n FROM publications")
    ).scalar_one()
    counts["serials"] = conn.execute(text("SELECT COUNT(*) AS n FROM serials")).scalar_one()
    counts["publishers"] = conn.execute(text("SELECT COUNT(*) AS n FROM publishers")).scalar_one()
    return counts


class TestNormalizeCrossrefIdempotence:
    def test_double_run_same_counts(self, sa_sync_conn):
        _insert_crossref_staging(sa_sync_conn, CROSSREF_STAGING_DOCS)

        processed_1 = _run_normalize_crossref(sa_sync_conn)
        create_all_publications(sa_sync_conn)
        counts_1 = _count_crossref(sa_sync_conn)
        assert processed_1 == 2
        assert counts_1["sp"] == 2
        # Deux auteurs dans le premier document, aucun dans le second.
        assert counts_1["sa"] == 2
        # Deux affiliations distinctes (UCA, CNRS), liées par leurs adresses.
        assert counts_1["sca"] == 2

        # La normalisation vide `raw_data` : le test réinsère le contenu pour relancer.
        _insert_crossref_staging(sa_sync_conn, CROSSREF_STAGING_DOCS)
        _run_normalize_crossref(sa_sync_conn)
        create_all_publications(sa_sync_conn)
        counts_2 = _count_crossref(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )

    def test_authors_persisted_with_orcid_and_affiliations(self, sa_sync_conn):
        from sqlalchemy import text

        _insert_crossref_staging(sa_sync_conn, [CROSSREF_STAGING_DOCS[0]])
        _run_normalize_crossref(sa_sync_conn)

        rows = sa_sync_conn.execute(
            text("""
                SELECT sc.raw_author_name, sc.raw_last_name, sc.raw_first_name,
                       ci.last_name_normalized, ci.identifiers
                FROM source_contributions sc
                JOIN contributor_information ci ON ci.id = sc.contributor_information_id
                WHERE sc.source = 'crossref'
                ORDER BY sc.author_position
            """)
        ).all()
        assert len(rows) == 2

        # Premier auteur : nom et prénom séparés par Crossref, ORCID.
        assert (rows[0].raw_author_name, rows[0].raw_last_name, rows[0].raw_first_name) == (
            None,
            "Curie",
            "Alice",
        )
        assert rows[0].last_name_normalized == "curie"
        assert rows[0].identifiers is not None
        assert rows[0].identifiers.get("orcid") == "0000-0002-1825-0097"

        # Deuxième auteur : sans ORCID.
        assert (rows[1].raw_last_name, rows[1].raw_first_name) == ("Pasteur", "Bob")
        assert rows[1].identifiers is None

        # Les affiliations deviennent des adresses liées aux contributions sources.
        addr_rows = sa_sync_conn.execute(
            text("""
                SELECT a.raw_text
                FROM source_contribution_addresses sca
                JOIN source_contributions sc ON sc.id = sca.source_contribution_id
                JOIN addresses a ON a.id = sca.address_id
                WHERE sc.source = 'crossref'
                ORDER BY a.raw_text
            """)
        ).all()
        assert [r.raw_text for r in addr_rows] == ["CNRS", "UCA"]


class TestNormalizeCrossrefSkipBranches:
    def test_skips_when_raw_data_empty(self, sa_sync_conn):
        # `raw_data` vide : rien d'inséré, ligne marquée traitée.
        from sqlalchemy import text

        _crossref_staging(sa_sync_conn, source_id="10.9999/cr-empty", doi="10.9999/cr-empty")

        processed = _run_normalize_crossref(sa_sync_conn)
        assert processed == 0
        # Marquée traitée, la ligne est laissée de côté au passage suivant.
        row = sa_sync_conn.execute(
            text(
                "SELECT processed FROM staging WHERE source = 'crossref' "
                "AND source_id = '10.9999/cr-empty'"
            )
        ).one()
        assert row.processed is True

    def test_skips_when_no_doi(self, sa_sync_conn):
        # `raw_data` sans DOI : rien d'inséré, ligne marquée traitée.
        from sqlalchemy import text

        _crossref_staging(sa_sync_conn, source_id="no-doi-001", raw_data={"title": ["Untitled"]})

        processed = _run_normalize_crossref(sa_sync_conn)
        assert processed == 0
        row = sa_sync_conn.execute(
            text(
                "SELECT processed FROM staging WHERE source = 'crossref' "
                "AND source_id = 'no-doi-001'"
            )
        ).one()
        assert row.processed is True

    def test_skips_when_no_title_or_year(self, sa_sync_conn):
        # `raw_data` avec DOI, sans titre ni année : rien d'inséré.
        from sqlalchemy import text

        _crossref_staging(
            sa_sync_conn,
            source_id="10.9999/no-title",
            doi="10.9999/no-title",
            raw_data={"DOI": "10.9999/no-title"},
        )

        processed = _run_normalize_crossref(sa_sync_conn)
        assert processed == 0
        row = sa_sync_conn.execute(
            text(
                "SELECT processed FROM staging WHERE source = 'crossref' "
                "AND source_id = '10.9999/no-title'"
            )
        ).one()
        assert row.processed is True
