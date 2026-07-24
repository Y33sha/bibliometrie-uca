"""Query service : SQL de la phase `metadata_correction`.

Appelé par `application/pipeline/metadata_correction/`. Implémente le port `application.ports.pipeline.metadata_correction.MetadataCorrectionQueries`.
"""

from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.metadata_correction import (
    CorrectionUpdate,
    DoiClusterRow,
    DoiCorrectionUpdate,
    JournalByDoiRow,
    JournalCorrectionUpdate,
    JournalDoiPrefixRow,
    MetadataCorrectionQueries,
    UnaryCorrectionRow,
)
from domain.publications.doc_types import DocType
from domain.source_publications.correction import DoiClusterCase

# Projection partagée : chaque colonne porte le nom du champ d'`UnaryCorrectionRow` qu'elle
# alimente (appariement par nom). Les booléens `embargo_expired` et `self_declared_preprint`
# sont calculés en SQL pour garder `effective_metadata` pure. Chaque variante ajoute son `WHERE`.
_SELECT = """
    SELECT sp.id, sp.source::text AS source,
           sp.title, sp.doc_type, sp.doi,
           sp.journal_id, sp.oa_status,
           sp.urls, sp.external_ids,
           j.journal_type::text AS journal_type, j.oa_model,
           sp.raw_metadata,
           (sp.embargo_until IS NOT NULL AND sp.embargo_until <= current_date) AS embargo_expired,
           COALESCE(jsonb_exists(sp.meta->'relation', 'is-preprint-of'), false)
               AS self_declared_preprint
    FROM source_publications sp
    LEFT JOIN journals j ON j.id = sp.journal_id
"""


def fetch_for_unary_correction(conn: Connection) -> list[UnaryCorrectionRow]:
    """Toutes les `source_publications`, LEFT JOIN `journals` pour les champs des règles journal-dépendantes (`journal_type`, `oa_model`), `raw_metadata` inclus pour la reconstruction du brut."""
    rows = conn.execute(text(_SELECT)).all()
    return [UnaryCorrectionRow(**row._mapping) for row in rows]


def fetch_for_unary_correction_by_journal(
    conn: Connection, journal_id: int
) -> list[UnaryCorrectionRow]:
    """Les `source_publications` d'un journal (`journal_id = :jid`) — recompute ciblé."""
    rows = conn.execute(text(_SELECT + " WHERE sp.journal_id = :jid"), {"jid": journal_id}).all()
    return [UnaryCorrectionRow(**row._mapping) for row in rows]


def fetch_journal_doi_prefixes(conn: Connection) -> list[JournalDoiPrefixRow]:
    """Toutes les revues portant un `doi_prefix`."""
    rows = conn.execute(
        text("SELECT doi_prefix, id AS journal_id FROM journals WHERE doi_prefix IS NOT NULL")
    ).all()
    return [JournalDoiPrefixRow(**row._mapping) for row in rows]


def fetch_journal_by_doi_candidates(conn: Connection) -> list[JournalByDoiRow]:
    """SP orphelines à DOI, plus celles déjà rattachées par préfixe (auto-cicatrisation)."""
    rows = conn.execute(
        text("""
            SELECT id, doi, journal_id, raw_metadata
            FROM source_publications
            WHERE (journal_id IS NULL AND doi IS NOT NULL)
               OR raw_metadata ? 'journal_id'
        """)
    ).all()
    return [JournalByDoiRow(**row._mapping) for row in rows]


def _persist_updates(
    conn: Connection,
    rows: list[dict[str, Any]],
    *,
    set_columns: tuple[str, ...],
    jsonb_params: tuple[str, ...] = (),
) -> int:
    """UPDATE en lot sur `source_publications` : pose les `set_columns` de chaque row (avec sa clé `id`), marque `keys_dirty`, bump `updated_at`. Retourne le nombre de lignes."""
    if not rows:
        return 0
    assignments = [f"{c} = :{c}" for c in set_columns]
    assignments += ["keys_dirty = true", "updated_at = clock_timestamp()"]
    sql = f"UPDATE source_publications SET {', '.join(assignments)} WHERE id = :id"  # noqa: S608
    stmt = text(sql)
    if jsonb_params:
        stmt = stmt.bindparams(*(bindparam(p, type_=JSONB) for p in jsonb_params))
    conn.execute(stmt, rows)
    return len(rows)


def persist_journal_corrections(conn: Connection, updates: list[JournalCorrectionUpdate]) -> int:
    """UPDATE en lot de la colonne `journal_id` + `raw_metadata`, bump `updated_at`, marque `keys_dirty` : `journal_id` n'est pas une clé de matching, mais la réconciliation est le seul chemin vers `refresh_from_sources`, et le rattachement doit la déclencher pour propager au `journal_id` canonique."""
    return _persist_updates(
        conn,
        [u._asdict() for u in updates],
        set_columns=("journal_id", "raw_metadata"),
        jsonb_params=("raw_metadata",),
    )


def _cluster_case(value: str | None) -> DoiClusterCase | None:
    """Convertit le cas rendu par le `CASE` SQL, dont les littéraux sont ceux de l'enum."""
    return DoiClusterCase(value) if value is not None else None


def fetch_doi_cluster_candidates(conn: Connection) -> list[DoiClusterRow]:
    """Membres des groupes-DOI candidats à la correction par cluster.

    `same_work` dérive le mapping forme secondaire DataCite → DOI de l'œuvre canonique depuis les `meta.related_identifiers` des `source_publications` `datacite` (clé = DOI **brut** reconstruit, stable après substitution) : version → concept (`IsVersionOf`), forme variante → version publiée (`IsVariantFormOf`), et pièce d'un dataset → dataset parent (`IsPartOf` vers un DOI présent en base **comme dataset** — le parent doit être moissonné pour absorber ses pièces, ce qui écarte aussi bien un parent article qu'un parent absent ; la forme du DOI est indifférente). `candidate_dois` réunit les DOI à examiner : formes secondaires, portés par un `book`/`book_chapter`, ou déjà corrigés (`raw_metadata.doi`, pour l'auto-cicatrisation). On renvoie **tous** les membres de ces DOI (toutes sources)."""
    rows = conn.execute(
        text(f"""
            WITH sp_eff AS (
                SELECT id, source, doc_type, doi, title_normalized, raw_metadata, meta,
                       lower(COALESCE(raw_metadata->'doi'->>'raw', doi)) AS eff_doi
                FROM source_publications
            ),
            dataset_dois AS (
                SELECT DISTINCT eff_doi AS d
                FROM sp_eff
                WHERE doc_type = '{DocType.DATASET.value}' AND eff_doi IS NOT NULL
            ),
            same_work AS (
                SELECT DISTINCT ON (secondary_doi) secondary_doi, canonical_doi, same_work_case
                FROM (
                    SELECT
                        sp.eff_doi AS secondary_doi,
                        lower(rel->>'doi') AS canonical_doi,
                        CASE rel->>'relation_type'
                            WHEN 'IsVersionOf'
                                THEN '{DoiClusterCase.DATACITE_VERSION_TO_CONCEPT.value}'
                            WHEN 'IsVariantFormOf'
                                THEN '{DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY.value}'
                        END AS same_work_case
                    FROM sp_eff sp
                    CROSS JOIN LATERAL jsonb_array_elements(sp.meta->'related_identifiers') rel
                    WHERE sp.source = 'datacite'
                      AND rel->>'relation_type' IN ('IsVersionOf', 'IsVariantFormOf')
                      AND rel->>'doi' IS NOT NULL
                      AND lower(rel->>'doi') <> sp.eff_doi
                    UNION ALL
                    -- Pièce d'un dataset → dataset parent : le parent doit être présent en base
                    -- comme dataset pour absorber ses pièces (`IN dataset_dois`). Ça exclut le
                    -- parent article (un dataset supplémentaire d'un article ne s'y fond pas) et
                    -- le parent absent (les pièces attendent son moissonnage). La forme du DOI
                    -- n'intervient pas : les pièces portent souvent un DOI frère, pas suffixé.
                    SELECT
                        sp.eff_doi AS secondary_doi,
                        lower(rel->>'doi') AS canonical_doi,
                        '{DoiClusterCase.DATACITE_PACKAGE_PIECE.value}' AS same_work_case
                    FROM sp_eff sp
                    CROSS JOIN LATERAL jsonb_array_elements(sp.meta->'related_identifiers') rel
                    WHERE sp.source = 'datacite'
                      AND sp.doc_type = '{DocType.DATASET.value}'
                      AND rel->>'relation_type' = 'IsPartOf'
                      AND rel->>'doi' IS NOT NULL
                      AND lower(rel->>'doi') <> sp.eff_doi
                      AND lower(rel->>'doi') IN (SELECT d FROM dataset_dois)
                ) s
                ORDER BY secondary_doi
            ),
            candidate_dois AS (
                SELECT secondary_doi AS d FROM same_work
                UNION
                SELECT eff_doi AS d FROM sp_eff
                WHERE doc_type IN ('{DocType.BOOK.value}', '{DocType.BOOK_CHAPTER.value}') AND eff_doi IS NOT NULL
                UNION
                SELECT eff_doi AS d FROM sp_eff WHERE raw_metadata ? 'doi'
            )
            SELECT sp.id, sp.doc_type, sp.doi, sp.title_normalized, sp.raw_metadata,
                   sp.eff_doi AS raw_doi,
                   sw.canonical_doi, sw.same_work_case
            FROM sp_eff sp
            JOIN candidate_dois c ON c.d = sp.eff_doi
            LEFT JOIN same_work sw ON sw.secondary_doi = sp.eff_doi
        """)
    ).all()
    return [
        DoiClusterRow(
            id=row.id,
            doc_type=row.doc_type,
            doi=row.doi,
            title_normalized=row.title_normalized,
            raw_metadata=row.raw_metadata,
            raw_doi=row.raw_doi,
            canonical_doi=row.canonical_doi,
            same_work_case=_cluster_case(row.same_work_case),
        )
        for row in rows
    ]


def persist_doi_corrections(conn: Connection, updates: list[DoiCorrectionUpdate]) -> int:
    """UPDATE en lot de la colonne `doi` + `raw_metadata`, bump `updated_at`, marque `keys_dirty` (le DOI est une clé de confirmation : mutation ⇒ réconciliation)."""
    return _persist_updates(
        conn,
        [u._asdict() for u in updates],
        set_columns=("doi", "raw_metadata"),
        jsonb_params=("raw_metadata",),
    )


def persist_corrections(conn: Connection, updates: list[CorrectionUpdate]) -> int:
    """UPDATE en lot des colonnes effectives + `raw_metadata`, bump `updated_at`, marque `keys_dirty` (`doc_type`/`external_ids` sont des clés : mutation ⇒ réconciliation)."""
    return _persist_updates(
        conn,
        [u._asdict() for u in updates],
        set_columns=("doc_type", "oa_status", "external_ids", "raw_metadata"),
        jsonb_params=("external_ids", "raw_metadata"),
    )


class PgMetadataCorrectionQueries(MetadataCorrectionQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.metadata_correction.MetadataCorrectionQueries`."""

    def fetch_for_unary_correction(self, conn: Connection) -> list[UnaryCorrectionRow]:
        return fetch_for_unary_correction(conn)

    def fetch_for_unary_correction_by_journal(
        self, conn: Connection, journal_id: int
    ) -> list[UnaryCorrectionRow]:
        return fetch_for_unary_correction_by_journal(conn, journal_id)

    def persist_corrections(self, conn: Connection, updates: list[CorrectionUpdate]) -> int:
        return persist_corrections(conn, updates)

    def fetch_journal_doi_prefixes(self, conn: Connection) -> list[JournalDoiPrefixRow]:
        return fetch_journal_doi_prefixes(conn)

    def fetch_journal_by_doi_candidates(self, conn: Connection) -> list[JournalByDoiRow]:
        return fetch_journal_by_doi_candidates(conn)

    def persist_journal_corrections(
        self, conn: Connection, updates: list[JournalCorrectionUpdate]
    ) -> int:
        return persist_journal_corrections(conn, updates)

    def fetch_doi_cluster_candidates(self, conn: Connection) -> list[DoiClusterRow]:
        return fetch_doi_cluster_candidates(conn)

    def persist_doi_corrections(self, conn: Connection, updates: list[DoiCorrectionUpdate]) -> int:
        return persist_doi_corrections(conn, updates)
