"""Query service : SQL de la phase `metadata_correction`.

Appelé par `application/pipeline/metadata_correction/`. Implémente le port `application.ports.pipeline.metadata_correction.MetadataCorrectionQueries`.
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
from domain.publications.doc_types import DocType
from domain.source_publications.metadata_correction.shared_doi import (
    DATACITE_DIRECT_CONVERGENCE,
    DATACITE_PACKAGE_PIECE_RELATION,
    DoiClusterCase,
)
from domain.sources.registry import Source
from infrastructure.db.tables import source_publications

# Bras du `CASE` et liste `IN` des relations DataCite à convergence directe, dérivés du mapping
# métier `DATACITE_DIRECT_CONVERGENCE`.
_DATACITE_CASE_SQL = (
    "CASE rel->>'relation_type' "
    + " ".join(
        f"WHEN '{relation}' THEN '{case.value}'"
        for relation, case in DATACITE_DIRECT_CONVERGENCE.items()
    )
    + " END"
)
_DATACITE_DIRECT_RELATIONS_SQL = (
    "(" + ", ".join(f"'{relation}'" for relation in DATACITE_DIRECT_CONVERGENCE) + ")"
)

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


# Colonnes que les corrections de métadonnées ont le droit de poser. Un nom de colonne
# s'interpole dans le SQL — un paramètre lié ne peut porter qu'une valeur, jamais un
# identifiant —, donc il ne vient d'aucune autre origine que cette liste.
_CORRECTABLE_COLUMNS: frozenset[str] = frozenset(
    {"doc_type", "oa_status", "external_ids", "raw_metadata", "journal_id", "doi"}
)

# Garde-fou de dérive : une colonne renommée dans le schéma fait échouer l'import, plutôt que
# de laisser la liste désigner un nom qui n'existe plus.
assert _CORRECTABLE_COLUMNS <= {c.name for c in source_publications.c}, (
    "liste des colonnes corrigibles désynchronisée de la table source_publications"
)


def _persist_updates(
    conn: Connection,
    rows: list[dict[str, object]],
    *,
    set_columns: tuple[str, ...],
    jsonb_params: tuple[str, ...] = (),
) -> int:
    """UPDATE en lot sur `source_publications` : pose les `set_columns` de chaque row (avec sa clé `id`), marque `keys_dirty`, bump `updated_at`. Retourne le nombre de lignes.

    `set_columns` est confronté à `_CORRECTABLE_COLUMNS` avant toute composition : le nom d'une colonne s'écrit dans le texte de la requête, et cette liste est la seule origine qu'il puisse avoir.
    """
    inconnues = sorted(set(set_columns) - _CORRECTABLE_COLUMNS)
    if inconnues:
        raise ValueError(f"Colonnes non corrigibles : {', '.join(inconnues)}")
    if not rows:
        return 0
    assignments = [f"{c} = :{c}" for c in set_columns]
    assignments += ["keys_dirty = true", "updated_at = clock_timestamp()"]
    # noqa S608 : requête composée, dont les seuls identifiants viennent de la liste blanche.
    sql = f"UPDATE source_publications SET {', '.join(assignments)} WHERE id = :id"  # noqa: S608
    stmt = text(sql)
    if jsonb_params:
        stmt = stmt.bindparams(*(bindparam(p, type_=JSONB) for p in jsonb_params))
    conn.execute(stmt, rows)
    return len(rows)


def _cluster_case(value: str | None) -> DoiClusterCase | None:
    """Convertit le cas rendu par le `CASE` SQL, dont les littéraux sont ceux de l'enum."""
    return DoiClusterCase(value) if value is not None else None


class PgMetadataCorrectionQueries(MetadataCorrectionQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.metadata_correction.MetadataCorrectionQueries`."""

    def fetch_for_unary_correction(self, conn: Connection) -> list[UnaryCorrectionRow]:
        rows = conn.execute(text(_SELECT)).all()
        return [UnaryCorrectionRow(**row._mapping) for row in rows]

    def fetch_for_unary_correction_by_journal(
        self, conn: Connection, journal_id: int
    ) -> list[UnaryCorrectionRow]:
        rows = conn.execute(
            text(_SELECT + " WHERE sp.journal_id = :jid"), {"jid": journal_id}
        ).all()
        return [UnaryCorrectionRow(**row._mapping) for row in rows]

    def persist_corrections(self, conn: Connection, updates: list[CorrectionUpdate]) -> int:
        return _persist_updates(
            conn,
            [u._asdict() for u in updates],
            set_columns=("doc_type", "oa_status", "external_ids", "raw_metadata"),
            jsonb_params=("external_ids", "raw_metadata"),
        )

    def fetch_journal_doi_prefixes(self, conn: Connection) -> list[JournalDoiPrefixRow]:
        rows = conn.execute(
            text("SELECT doi_prefix, id AS journal_id FROM journals WHERE doi_prefix IS NOT NULL")
        ).all()
        return [JournalDoiPrefixRow(**row._mapping) for row in rows]

    def fetch_journal_by_doi_candidates(self, conn: Connection) -> list[JournalByDoiRow]:
        rows = conn.execute(
            text("""
                SELECT id, doi, journal_id, raw_metadata
                FROM source_publications
                WHERE (journal_id IS NULL AND doi IS NOT NULL)
                   OR raw_metadata ? 'journal_id'
            """)
        ).all()
        return [JournalByDoiRow(**row._mapping) for row in rows]

    def persist_journal_corrections(
        self, conn: Connection, updates: list[JournalCorrectionUpdate]
    ) -> int:
        return _persist_updates(
            conn,
            [u._asdict() for u in updates],
            set_columns=("journal_id", "raw_metadata"),
            jsonb_params=("raw_metadata",),
        )

    def fetch_doi_cluster_candidates(self, conn: Connection) -> list[DoiClusterRow]:
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
                            {_DATACITE_CASE_SQL} AS same_work_case
                        FROM sp_eff sp
                        CROSS JOIN LATERAL jsonb_array_elements(sp.meta->'related_identifiers') rel
                        WHERE sp.source = '{Source.DATACITE.value}'
                          AND rel->>'relation_type' IN {_DATACITE_DIRECT_RELATIONS_SQL}
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
                        WHERE sp.source = '{Source.DATACITE.value}'
                          AND sp.doc_type = '{DocType.DATASET.value}'
                          AND rel->>'relation_type' = '{DATACITE_PACKAGE_PIECE_RELATION}'
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

    def persist_doi_corrections(self, conn: Connection, updates: list[DoiCorrectionUpdate]) -> int:
        return _persist_updates(
            conn,
            [u._asdict() for u in updates],
            set_columns=("doi", "raw_metadata"),
            jsonb_params=("raw_metadata",),
        )
