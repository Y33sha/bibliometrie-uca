"""SQL de la phase `metadata_correction`, et du recalcul ciblé des corrections d'une revue.

La phase persiste sur `source_publications` les valeurs corrigées par les règles de `domain.source_publications.metadata_correction`, pour que le matching aval lise des colonnes déjà corrigées. Trois sous-étapes s'appuient sur ce module : la correction unaire, qui traite chaque `source_publication` isolément ; le rattachement d'un journal par préfixe de DOI ; et la correction de DOI par groupe de `source_publications` partageant un même DOI.
"""

from typing import NamedTuple

from sqlalchemy import Connection, bindparam, text

from domain.journals.doi_namespaces import DoiNamespace
from domain.publications.doc_types import DocType
from domain.source_publications.metadata_correction.rules import MetadataForCorrection
from domain.source_publications.metadata_correction.shared_doi import (
    DATACITE_DIRECT_CONVERGENCE,
    DATACITE_PACKAGE_PIECE_RELATION,
    REMOVED_EXTERNAL_IDS,
    DoiClusterCase,
)
from domain.sources.registry import DOI_ORG, Source
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.rows import rows_as
from infrastructure.db.tables import source_publications
from infrastructure.sql_fragments import diamond_journal_sql


class UnaryCorrectionRow(NamedTuple):
    """Une `source_publication` candidate à la correction unaire, jointe à son journal.

    Contient les champs du contrat des règles (`for_correction`) et ceux dont la phase seule se sert : `id` pour persister, `source` pour `map_doc_type`, `source_id` pour retrouver le dépôt HAL d'une notice ScanR, `language` pour sa correspondance avec le référentiel des langues, `external_ids` et `raw_metadata` pour le stash et la reconstruction du brut.

    L'adapter construit les lignes par appariement de noms : chaque champ a le nom de la colonne qui l'alimente.
    """

    id: int
    source: str
    source_id: str
    title: str
    doc_type: str | None
    doi: str | None
    journal_id: int | None
    oa_status: str | None
    language: str | None
    urls: list[str] | None
    external_ids: dict[str, JsonValue]
    journal_type: str | None
    oa_model: str | None
    raw_metadata: dict[str, JsonValue]
    embargo_expired: bool
    self_declared_preprint: bool
    declares_conference: bool
    registrant_publisher_type: str | None
    in_proceedings_volume: bool
    group_title: str | None
    journal_diamond: bool
    author_count: int

    def for_correction(self) -> MetadataForCorrection:
        """Projette la ligne vers le contrat d'entrée des règles."""
        return MetadataForCorrection(
            title=self.title,
            doc_type=self.doc_type,
            doi=self.doi,
            journal_id=self.journal_id,
            oa_status=self.oa_status,
            urls=self.urls,
            journal_type=self.journal_type,
            oa_model=self.oa_model,
            embargo_expired=self.embargo_expired,
            self_declared_preprint=self.self_declared_preprint,
            declares_conference=self.declares_conference,
            registrant_publisher_type=self.registrant_publisher_type,
            in_proceedings_volume=self.in_proceedings_volume,
            group_title=self.group_title,
            journal_diamond=self.journal_diamond,
            source=self.source,
            author_count=self.author_count,
        )


class CorrectionUpdate(NamedTuple):
    """Une mise à jour à persister : colonnes effectives + `external_ids` + sidecar `raw_metadata`."""

    id: int
    doc_type: str | None
    oa_status: str | None
    language: str | None
    external_ids: dict[str, JsonValue]
    raw_metadata: dict[str, JsonValue]


class JournalCorrectionRow(NamedTuple):
    """Une `source_publication` candidate au rattachement de la revue par l'espace de noms de son DOI : son id, sa source, son type brut, son DOI courant, son `journal_id` courant et `raw_metadata` (reconstruction du brut `journal_id` et garde « ne corriger que le manquant »)."""

    id: int
    source: str
    raw_doc_type: str | None
    doi: str | None
    journal_id: int | None
    raw_metadata: dict[str, JsonValue]


class JournalCorrectionUpdate(NamedTuple):
    """Une mise à jour de rattachement : colonne `journal_id` (posée ou restaurée à NULL) + sidecar `raw_metadata`. Produite par la sous-étape `journal_by_doi`, persistée via `persist_journal_corrections`."""

    id: int
    journal_id: int | None
    raw_metadata: dict[str, JsonValue]


class DoiClusterRow(NamedTuple):
    """Une `source_publication` candidate à la correction de DOI par cluster.

    `raw_doi` est le DOI **source reconstruit** (`raw_metadata.doi.raw` ou colonne `doi`), en minuscules — clé de regroupement par DOI. `title_normalized` sert à la comparaison chapitre/chapitre. `canonical_doi` est le DOI de l'œuvre de référence quand `raw_doi` est une **forme secondaire** DataCite (version, forme variante, ou fichier de package), sinon `None` ; `same_work_case` donne alors le cas correspondant."""

    id: int
    doc_type: str | None
    doi: str | None
    title_normalized: str | None
    raw_metadata: dict[str, JsonValue]
    raw_doi: str
    canonical_doi: str | None
    same_work_case: DoiClusterCase | None
    # `raw_doi` est inconnu de doi.org (`failed_lookups`, source `doi_org`).
    unresolved: bool = False
    external_ids: dict[str, JsonValue] = {}
    source: str = ""
    source_id: str = ""


class DoiCorrectionUpdate(NamedTuple):
    """Une mise à jour de la correction par cluster : colonne `doi` (nullée, restaurée ou substituée), sidecar, et identifiants externes (clés partagées avec une autre œuvre retirées ou restaurées). Persistée via `persist_doi_corrections`."""

    id: int
    doi: str | None
    raw_metadata: dict[str, JsonValue]
    external_ids: dict[str, JsonValue]


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
# alimente (appariement par nom). Les booléens `embargo_expired`, `self_declared_preprint` et `declares_conference`
# sont calculés en SQL pour garder `effective_metadata` pure. `registrant_publisher_type` est le type de
# l'éditeur qui a déposé le préfixe du DOI, `in_proceedings_volume` la nature de sa monographie, `group_title` la forme de présentation lue dans `meta`, `journal_diamond` le caractère diamant de la revue, `author_count` le nombre de signatures. Chaque
# variante ajoute son `WHERE`.
_SELECT = f"""
    SELECT sp.id, sp.source::text AS source, sp.source_id,
           sp.title, sp.doc_type, sp.doi,
           sp.journal_id, sp.oa_status, sp.language,
           sp.urls, sp.external_ids,
           j.journal_type::text AS journal_type, j.oa_model,
           sp.raw_metadata,
           (sp.embargo_until IS NOT NULL AND sp.embargo_until <= current_date) AS embargo_expired,
           COALESCE(jsonb_exists(sp.meta->'relation', 'is-preprint-of'), false)
               AS self_declared_preprint,
           COALESCE(sp.meta ? 'conference', false) AS declares_conference,
           rp.publisher_type::text AS registrant_publisher_type,
           COALESCE(m.proceedings, false) AS in_proceedings_volume,
           sp.meta->>'group_title' AS group_title,
           COALESCE({diamond_journal_sql("j")}, false) AS journal_diamond,
           (SELECT count(*) FROM source_authorships sa
            WHERE sa.source_publication_id = sp.id) AS author_count
    FROM source_publications sp
    LEFT JOIN journals j ON j.id = sp.journal_id
    LEFT JOIN monographs m ON m.id = sp.monograph_id
    LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(sp.doi, '/', 1)
    LEFT JOIN publishers rp ON rp.id = dp.publisher_id
"""


# Colonnes que les corrections de métadonnées ont le droit de poser. Un nom de colonne
# s'interpole dans le SQL — un paramètre lié ne peut porter qu'une valeur, jamais un
# identifiant —, donc il ne vient d'aucune autre origine que cette liste.
_CORRECTABLE_COLUMNS: frozenset[str] = frozenset(
    {"doc_type", "oa_status", "language", "external_ids", "raw_metadata", "journal_id", "doi"}
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
        stmt = stmt.bindparams(*(bindparam(p, type_=Jsonb) for p in jsonb_params))
    conn.execute(stmt, rows)
    return len(rows)


def _cluster_case(value: str | None) -> DoiClusterCase | None:
    """Convertit le cas rendu par le `CASE` SQL, dont les littéraux sont ceux de l'enum."""
    return DoiClusterCase(value) if value is not None else None


class PgMetadataCorrectionQueries:
    """Requêtes de la phase `metadata_correction`."""

    def fetch_for_unary_correction(self, conn: Connection) -> list[UnaryCorrectionRow]:
        """Toutes les `source_publications`, avec join `journals` et `raw_metadata`.

        Pas de pré-filtre par règle : certaines règles sont inconditionnelles sur `doc_type` (URL theses.fr/DUMAS), et une `source_publication` sans `doc_type` reste candidate. La cascade `effective_metadata` fait le filtrage fin.
        """
        rows = conn.execute(text(_SELECT))
        return rows_as(UnaryCorrectionRow, rows)

    def fetch_for_unary_correction_by_journal(
        self, conn: Connection, journal_id: int
    ) -> list[UnaryCorrectionRow]:
        """Les `source_publications` rattachées à un journal (`journal_id = :jid`).

        Recompute ciblé après un changement de `journal_type` (hook admin) : seules ces `source_publications` voient leur correction journal-dépendante bouger."""
        rows = conn.execute(text(_SELECT + " WHERE sp.journal_id = :jid"), {"jid": journal_id})
        return rows_as(UnaryCorrectionRow, rows)

    def fetch_for_unary_correction_by_hal_ids(
        self, conn: Connection, hal_ids: list[str]
    ) -> list[UnaryCorrectionRow]:
        """Les `source_publications` HAL dont l'identifiant figure dans `hal_ids` : dépôts d'origine des notices ScanR d'une correction ciblée."""
        if not hal_ids:
            return []
        rows = conn.execute(
            text(_SELECT + " WHERE sp.source = 'hal' AND sp.source_id = ANY(:ids)"),
            {"ids": hal_ids},
        )
        return rows_as(UnaryCorrectionRow, rows)

    def fetch_language_forms(self, conn: Connection) -> dict[str, str]:
        """Formes de `language_forms`, chacune associée au code de sa langue."""
        rows = conn.execute(text("SELECT form_normalized, language_code FROM language_forms"))
        return {r.form_normalized: r.language_code for r in rows}

    def persist_corrections(self, conn: Connection, updates: list[CorrectionUpdate]) -> int:
        """UPDATE en lot des colonnes effectives + `raw_metadata`, bump `updated_at`, marque `keys_dirty` — `doc_type` et `external_ids` sont des clés de matching, dont la mutation appelle une réconciliation ; celle-ci recalcule aussi la langue de la publication. Retourne le nombre de lignes mises à jour."""
        return _persist_updates(
            conn,
            [u._asdict() for u in updates],
            set_columns=("doc_type", "oa_status", "language", "external_ids", "raw_metadata"),
            jsonb_params=("external_ids", "raw_metadata"),
        )

    def fetch_journal_doi_namespaces(self, conn: Connection) -> list[DoiNamespace]:
        """Le contenu de `journal_doi_namespaces`."""
        rows = conn.execute(
            text("SELECT namespace, journal_id, dois, share FROM journal_doi_namespaces")
        )
        return rows_as(DoiNamespace, rows)

    def fetch_journal_by_doi_candidates(self, conn: Connection) -> list[JournalCorrectionRow]:
        """`source_publications` candidates au rattachement : orphelines à DOI (`journal_id IS NULL AND doi IS NOT NULL`) et déjà rattachées par espace de noms (`raw_metadata ? 'journal_id'`, pour la ré-évaluation auto-cicatrisante)."""
        rows = conn.execute(
            text("""
                SELECT id, source::text AS source,
                       coalesce(raw_metadata->'doc_type'->>'raw', doc_type) AS raw_doc_type,
                       doi, journal_id, raw_metadata
                FROM source_publications
                WHERE (journal_id IS NULL AND doi IS NOT NULL)
                   OR raw_metadata ? 'journal_id'
            """)
        )
        return rows_as(JournalCorrectionRow, rows)

    def persist_journal_corrections(
        self, conn: Connection, updates: list[JournalCorrectionUpdate]
    ) -> int:
        """UPDATE en lot de la colonne `journal_id` + `raw_metadata`, bump `updated_at`, marque `keys_dirty` (pour que la réconciliation rafraîchisse le `journal_id` de la publication — bien que `journal_id` ne soit pas une clé de matching). Retourne le nombre de lignes."""
        return _persist_updates(
            conn,
            [u._asdict() for u in updates],
            set_columns=("journal_id", "raw_metadata"),
            jsonb_params=("raw_metadata",),
        )

    def fetch_doi_cluster_candidates(self, conn: Connection) -> list[DoiClusterRow]:
        """Les membres des groupes-DOI candidats à la correction par cluster, avec leur `canonical_doi` éventuel : groupes contenant un `book`/`book_chapter`/`proceedings`, groupes dont le DOI est un DOI de version DataCite (`IsVersionOf`), groupes dont le DOI est inconnu de doi.org, et `source_publications` déjà corrigées (`raw_metadata.doi` ou `raw_metadata.removed_external_ids`) pour la ré-évaluation auto-cicatrisante."""
        rows = conn.execute(
            text(f"""
                WITH sp_eff AS (
                    SELECT id, source, source_id, doc_type, doi, title_normalized, raw_metadata,
                           meta, external_ids,
                           lower(COALESCE(raw_metadata->'doi'->>'raw', doi)) AS eff_doi
                    FROM source_publications
                ),
                dataset_dois AS (
                    SELECT DISTINCT eff_doi AS d
                    FROM sp_eff
                    WHERE doc_type = '{DocType.DATASET.value}' AND eff_doi IS NOT NULL
                ),
                -- La cible reste attachée à la notice DataCite dont les `related_identifiers`
                -- la mentionnent : la règle de même œuvre lit le type de cette notice, et les
                -- autres notices au même DOI suivent la décision du groupe. Quand une notice
                -- mentionne plusieurs cibles, la version (concept) prime sur la variante.
                same_work AS (
                    SELECT DISTINCT ON (declarant_id)
                           declarant_id, secondary_doi, canonical_doi, same_work_case
                    FROM (
                        SELECT
                            sp.id AS declarant_id,
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
                            sp.id AS declarant_id,
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
                    ORDER BY declarant_id,
                             same_work_case = '{DoiClusterCase.DATACITE_VERSION_TO_CONCEPT.value}' DESC,
                             canonical_doi
                ),
                unresolved_dois AS (
                    SELECT id_value AS d FROM failed_lookups
                    WHERE source = '{DOI_ORG}' AND id_type = 'doi'
                ),
                candidate_dois AS (
                    SELECT secondary_doi AS d FROM same_work
                    UNION
                    SELECT eff_doi AS d FROM sp_eff
                    WHERE doc_type IN ('{DocType.BOOK.value}', '{DocType.BOOK_CHAPTER.value}', '{DocType.PROCEEDINGS.value}')
                      AND eff_doi IS NOT NULL
                    UNION
                    SELECT eff_doi AS d FROM sp_eff
                    WHERE raw_metadata ?| ARRAY['doi', '{REMOVED_EXTERNAL_IDS}']
                    UNION
                    SELECT d FROM unresolved_dois
                )
                SELECT sp.id, sp.doc_type, sp.doi, sp.title_normalized, sp.raw_metadata,
                       sp.external_ids, sp.source::text AS source, sp.source_id,
                       sp.eff_doi AS raw_doi,
                       sw.canonical_doi, sw.same_work_case,
                       sp.eff_doi IN (SELECT d FROM unresolved_dois) AS unresolved
                FROM sp_eff sp
                JOIN candidate_dois c ON c.d = sp.eff_doi
                LEFT JOIN same_work sw ON sw.declarant_id = sp.id
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
                unresolved=row.unresolved,
                external_ids=row.external_ids,
                source=row.source,
                source_id=row.source_id,
            )
            for row in rows
        ]

    def persist_doi_corrections(self, conn: Connection, updates: list[DoiCorrectionUpdate]) -> int:
        """UPDATE en lot des colonnes `doi`, `external_ids` et `raw_metadata`, bump `updated_at`, marque `keys_dirty` — DOI et identifiants externes sont des clés de confirmation, dont la mutation appelle une réconciliation. Retourne le nombre de lignes mises à jour."""
        return _persist_updates(
            conn,
            [u._asdict() for u in updates],
            set_columns=("doi", "external_ids", "raw_metadata"),
            jsonb_params=("external_ids", "raw_metadata"),
        )
