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
    JournalByDoiRow,
    JournalCorrectionUpdate,
    JournalDoiPrefixRow,
    MetadataCorrectionQueries,
    UnaryCorrectionRow,
)
from domain.source_publications.correction import DoiClusterCase

# Projection partagée. Chaque colonne porte le nom du champ d'`UnaryCorrectionRow` qu'elle
# alimente : les lignes sont construites par appariement de noms. Contenu : SP + champs joints
# `journals` (règles journal-dépendantes) + `raw_metadata` (reconstruction du brut) + deux
# booléens calculés ici pour garder `effective_metadata` pure : `embargo_expired`
# (date-dépendant ; la règle d'embargo lit le booléen, pas la date) et `self_declared_preprint`
# (la SP déclare `is-preprint-of`, sans lire `meta` dans le domaine). Le `WHERE` est ajouté par
# chaque variante.
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
    """Toutes les `source_publications`, LEFT JOIN `journals` pour les champs des règles
    journal-dépendantes (`journal_type`, `oa_model`), `raw_metadata` inclus pour la
    reconstruction du brut."""
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
    return [JournalByDoiRow(*row) for row in rows]


def persist_journal_corrections(conn: Connection, updates: list[JournalCorrectionUpdate]) -> int:
    """UPDATE en lot de la colonne `journal_id` + `raw_metadata`, bump `updated_at`, marque
    `keys_dirty` : `journal_id` n'est pas une clé de matching, mais la réconciliation est le
    seul chemin vers `refresh_from_sources`, donc le rattachement doit la déclencher pour
    propager au `journal_id` canonique."""
    if not updates:
        return 0
    stmt = text("""
        UPDATE source_publications
        SET journal_id = :journal_id,
            raw_metadata = :raw_metadata,
            keys_dirty = true,
            updated_at = clock_timestamp()
        WHERE id = :id
    """).bindparams(bindparam("raw_metadata", type_=JSONB))
    conn.execute(stmt, [u._asdict() for u in updates])
    return len(updates)


def _cluster_case(value: str | None) -> DoiClusterCase | None:
    """Convertit le cas rendu par le `CASE` SQL, dont les littéraux sont ceux de l'enum."""
    return DoiClusterCase(value) if value is not None else None


def fetch_doi_cluster_candidates(conn: Connection) -> list[DoiClusterRow]:
    """Membres des groupes-DOI candidats à la correction par cluster.

    `same_work` dérive le mapping forme secondaire DataCite → DOI de l'œuvre canonique depuis
    les `meta.related_identifiers` des SP `datacite` (clé = DOI **brut** reconstruit, stable
    après substitution) : version → concept (`IsVersionOf`), forme variante → version publiée
    (`IsVariantFormOf`), et pièce d'un dataset → dataset parent (`IsPartOf` vers un DOI présent
    en base **comme dataset** — le parent doit être moissonné pour absorber ses pièces, ce qui
    écarte aussi bien un parent article qu'un parent absent ; la forme du DOI est indifférente).
    `candidate_dois` réunit les DOI à examiner : formes secondaires, portés par un
    `book`/`book_chapter`, ou déjà corrigés (`raw_metadata.doi`, pour l'auto-cicatrisation).
    On renvoie **tous** les membres de ces DOI (toutes sources)."""
    rows = conn.execute(
        text(f"""
            WITH dataset_dois AS (
                SELECT DISTINCT lower(COALESCE(raw_metadata->'doi'->>'raw', doi)) AS d
                FROM source_publications
                WHERE doc_type = 'dataset'
                  AND COALESCE(raw_metadata->'doi'->>'raw', doi) IS NOT NULL
            ),
            same_work AS (
                SELECT DISTINCT ON (secondary_doi) secondary_doi, canonical_doi, same_work_case
                FROM (
                    SELECT
                        lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi)) AS secondary_doi,
                        lower(rel->>'doi') AS canonical_doi,
                        CASE rel->>'relation_type'
                            WHEN 'IsVersionOf'
                                THEN '{DoiClusterCase.DATACITE_VERSION_TO_CONCEPT.value}'
                            WHEN 'IsVariantFormOf'
                                THEN '{DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY.value}'
                        END AS same_work_case
                    FROM source_publications sp
                    CROSS JOIN LATERAL jsonb_array_elements(sp.meta->'related_identifiers') rel
                    WHERE sp.source = 'datacite'
                      AND rel->>'relation_type' IN ('IsVersionOf', 'IsVariantFormOf')
                      AND rel->>'doi' IS NOT NULL
                      AND lower(rel->>'doi')
                          <> lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi))
                    UNION ALL
                    -- Pièce d'un dataset → dataset parent : le parent doit être présent en base
                    -- comme dataset pour absorber ses pièces (`IN dataset_dois`). Ça exclut le
                    -- parent article (un dataset supplémentaire d'un article ne s'y fond pas) et
                    -- le parent absent (les pièces attendent son moissonnage). La forme du DOI
                    -- n'intervient pas : les pièces portent souvent un DOI frère, pas suffixé.
                    SELECT
                        lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi)) AS secondary_doi,
                        lower(rel->>'doi') AS canonical_doi,
                        '{DoiClusterCase.DATACITE_PACKAGE_PIECE.value}' AS same_work_case
                    FROM source_publications sp
                    CROSS JOIN LATERAL jsonb_array_elements(sp.meta->'related_identifiers') rel
                    WHERE sp.source = 'datacite'
                      AND sp.doc_type = 'dataset'
                      AND rel->>'relation_type' = 'IsPartOf'
                      AND rel->>'doi' IS NOT NULL
                      AND lower(rel->>'doi')
                          <> lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi))
                      AND lower(rel->>'doi') IN (SELECT d FROM dataset_dois)
                ) s
                ORDER BY secondary_doi
            ),
            candidate_dois AS (
                SELECT secondary_doi AS d FROM same_work
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
                   sw.canonical_doi, sw.same_work_case
            FROM source_publications sp
            JOIN candidate_dois c
              ON c.d = lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi))
            LEFT JOIN same_work sw
              ON sw.secondary_doi = lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi))
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
