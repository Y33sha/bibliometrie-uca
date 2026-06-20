"""Query service : SQL de la phase `metadata_correction`.

Appelé par `application/pipeline/metadata_correction/`. Implémente le port
`application.ports.pipeline.metadata_correction.MetadataCorrectionQueries`.
"""

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.metadata_correction import (
    CorrectionUpdate,
    DoiClusterRow,
    DoiCorrectionUpdate,
    MetadataCorrectionQueries,
)
from domain.source_publications.correction import SourcePublicationForCorrection

# Projection partagée : SP + champs joints `journals` (règles journal-dépendantes)
# + `raw_metadata` (reconstruction du brut) + `embargo_expired` (calculé ici, seule
# donnée date-dépendante : la règle de promotion d'embargo lit ce booléen, pas la date,
# pour garder `effective_metadata` pure). Le `WHERE` est ajouté par chaque variante.
_SELECT = """
    SELECT sp.id, sp.source::text AS source, sp.source_id,
           sp.title, sp.pub_year, sp.doc_type, sp.doi,
           sp.journal_id, sp.oa_status, sp.container_title, sp.language,
           sp.urls, sp.external_ids,
           j.journal_type::text AS journal_type, j.oa_model, j.apc_amount,
           sp.raw_metadata,
           (sp.embargo_until IS NOT NULL AND sp.embargo_until <= current_date) AS embargo_expired
    FROM source_publications sp
    LEFT JOIN journals j ON j.id = sp.journal_id
"""


def fetch_for_unary_correction(conn: Connection) -> list[SourcePublicationForCorrection]:
    """Toutes les `source_publications`, LEFT JOIN `journals` pour les champs des règles
    journal-dépendantes (`journal_type`, `oa_model`, `apc_amount`), `raw_metadata` inclus
    pour la reconstruction du brut."""
    rows = conn.execute(text(_SELECT)).all()
    return [SourcePublicationForCorrection(*row) for row in rows]


def fetch_for_unary_correction_by_journal(
    conn: Connection, journal_id: int
) -> list[SourcePublicationForCorrection]:
    """Les `source_publications` d'un journal (`journal_id = :jid`) — recompute ciblé."""
    rows = conn.execute(text(_SELECT + " WHERE sp.journal_id = :jid"), {"jid": journal_id}).all()
    return [SourcePublicationForCorrection(*row) for row in rows]


def fetch_doi_cluster_candidates(conn: Connection) -> list[DoiClusterRow]:
    """Membres des groupes-DOI candidats à la correction par cluster, avec leur `concept_doi`.

    `version_map` dérive le mapping DOI de version → DOI concept depuis les
    `meta.related_identifiers` (`IsVersionOf`) des SP `datacite` (clé = DOI **brut**
    reconstruit, stable après substitution). `candidate_dois` réunit les DOI à examiner :
    versionnés, portés par un `book`/`book_chapter`, ou déjà corrigés (`raw_metadata.doi`,
    pour l'auto-cicatrisation). On renvoie **tous** les membres de ces DOI (toutes sources)."""
    rows = conn.execute(
        text("""
            WITH version_map AS (
                SELECT DISTINCT
                    lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi)) AS version_doi,
                    lower(rel->>'doi') AS concept_doi
                FROM source_publications sp
                CROSS JOIN LATERAL jsonb_array_elements(sp.meta->'related_identifiers') rel
                WHERE sp.source = 'datacite'
                  AND rel->>'relation_type' = 'IsVersionOf'
                  AND rel->>'doi' IS NOT NULL
                  AND lower(rel->>'doi')
                      <> lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi))
            ),
            candidate_dois AS (
                SELECT version_doi AS d FROM version_map
                UNION
                SELECT lower(COALESCE(raw_metadata->'doi'->>'raw', doi)) AS d
                FROM source_publications
                WHERE doc_type IN ('book', 'book_chapter')
                  AND COALESCE(raw_metadata->'doi'->>'raw', doi) IS NOT NULL
                UNION
                SELECT lower(COALESCE(raw_metadata->'doi'->>'raw', doi)) AS d
                FROM source_publications
                WHERE raw_metadata ? 'doi'
            )
            SELECT sp.id, sp.doc_type, sp.doi, sp.title_normalized, sp.raw_metadata,
                   lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi)) AS raw_doi,
                   vm.concept_doi
            FROM source_publications sp
            JOIN candidate_dois c
              ON c.d = lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi))
            LEFT JOIN version_map vm
              ON vm.version_doi = lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi))
        """)
    ).all()
    return [DoiClusterRow(*row) for row in rows]


def persist_doi_corrections(conn: Connection, updates: list[DoiCorrectionUpdate]) -> int:
    """UPDATE en lot de la colonne `doi` + `raw_metadata`, bump `updated_at`, marque
    `keys_dirty` (le DOI est une clé de confirmation : mutation ⇒ réconciliation)."""
    if not updates:
        return 0
    stmt = text("""
        UPDATE source_publications
        SET doi = :doi,
            raw_metadata = :raw_metadata,
            keys_dirty = true,
            updated_at = clock_timestamp()
        WHERE id = :id
    """).bindparams(bindparam("raw_metadata", type_=JSONB))
    conn.execute(stmt, [u._asdict() for u in updates])
    return len(updates)


def persist_corrections(conn: Connection, updates: list[CorrectionUpdate]) -> int:
    """UPDATE en lot des colonnes effectives + `raw_metadata`, bump `updated_at`, marque
    `keys_dirty` (`doc_type`/`external_ids` sont des clés : mutation ⇒ réconciliation)."""
    if not updates:
        return 0
    stmt = text("""
        UPDATE source_publications
        SET doc_type = :doc_type,
            journal_id = :journal_id,
            oa_status = :oa_status,
            external_ids = :external_ids,
            raw_metadata = :raw_metadata,
            keys_dirty = true,
            updated_at = clock_timestamp()
        WHERE id = :id
    """).bindparams(bindparam("external_ids", type_=JSONB), bindparam("raw_metadata", type_=JSONB))
    conn.execute(stmt, [u._asdict() for u in updates])
    return len(updates)


class PgMetadataCorrectionQueries(MetadataCorrectionQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.metadata_correction.MetadataCorrectionQueries`."""

    def fetch_for_unary_correction(self, conn: Connection) -> list[SourcePublicationForCorrection]:
        return fetch_for_unary_correction(conn)

    def fetch_for_unary_correction_by_journal(
        self, conn: Connection, journal_id: int
    ) -> list[SourcePublicationForCorrection]:
        return fetch_for_unary_correction_by_journal(conn, journal_id)

    def persist_corrections(self, conn: Connection, updates: list[CorrectionUpdate]) -> int:
        return persist_corrections(conn, updates)

    def fetch_doi_cluster_candidates(self, conn: Connection) -> list[DoiClusterRow]:
        return fetch_doi_cluster_candidates(conn)

    def persist_doi_corrections(self, conn: Connection, updates: list[DoiCorrectionUpdate]) -> int:
        return persist_doi_corrections(conn, updates)
