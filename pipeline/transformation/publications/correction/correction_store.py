"""SQL de la phase `metadata_correction`, et du recalcul ciblé des corrections d'une revue.

La phase persiste sur `source_records` les valeurs corrigées par les règles de `domain.source_records.metadata_correction`, pour que le matching aval lise des colonnes déjà corrigées. Trois sous-étapes s'appuient sur ce module : la correction unaire, qui traite chaque `source_record` isolément ; le rattachement d'un journal par préfixe de DOI ; et la correction de DOI par groupe de `source_records` partageant un même DOI.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import fields
from typing import NamedTuple

from sqlalchemy import Connection, Row, bindparam, func, text

from domain.publications.doc_types import DocType
from domain.publications.scope import MatchabilityFacts
from domain.serials.doi_namespaces import DoiNamespace
from domain.source_records.corrections import CORRECTED_BY, RAW, CorrectionKey
from domain.source_records.external_ids import ExternalIdType
from domain.source_records.metadata_correction.rules import (
    MetadataCorrectionRule,
    MetadataForCorrection,
)
from domain.source_records.metadata_correction.shared_doi import (
    DATACITE_DIRECT_CONVERGENCE,
    DATACITE_PACKAGE_PIECE_RELATION,
    FIGSHARE_ADDITIONAL_FILE_TITLE_PATTERN,
    FIGSHARE_COLLECTION_DOI_PREFIX,
    FIGSHARE_ITEM_DOI_PATTERN,
    DoiClusterCase,
)
from domain.source_records.metadata_correction.source_record import CorrectedSourceRecord
from domain.source_records.source_extras import SourceExtra
from domain.sources.registry import DOI_ORG, Source
from domain.types import JsonValue
from infrastructure.db.queues import Queue, enqueue
from infrastructure.db.rows import rows_as
from infrastructure.db.tables import source_records
from infrastructure.sql_fragments import (
    corrected,
    declares_conference_sql,
    diamond_journal_sql,
    raw_column,
    self_declared_preprint_sql,
    source_extra,
    source_extra_json,
)


class UnaryCorrectionRow(NamedTuple):
    """Une `source_record` candidate à la correction unaire : les faits que lisent les règles (`facts`), et ce dont la phase se sert pour persister."""

    id: int
    source_id: str
    external_ids: dict[str, JsonValue]
    corrections: dict[str, JsonValue]
    facts: MetadataForCorrection


class CorrectionUpdate(NamedTuple):
    """Une mise à jour de la correction unaire : l'enregistrement source `id` et ses valeurs corrigées."""

    id: int
    corrected: CorrectedSourceRecord


class MatchabilityRow(NamedTuple):
    """Une `source_record` : sa valeur courante de `is_matchable` et les faits qui la décident."""

    id: int
    is_matchable: bool
    facts: MatchabilityFacts


class MatchabilityUpdate(NamedTuple):
    """Nouvelle valeur de `is_matchable` de l'enregistrement source `id`."""

    id: int
    is_matchable: bool


class SerialCorrectionRow(NamedTuple):
    """Une `source_record` candidate au rattachement de la revue par l'espace de noms de son DOI : son id, sa source, son type brut, son DOI courant, son `serial_id` courant et `corrections` (reconstruction du brut `serial_id` et garde « ne corriger que le manquant »)."""

    id: int
    source: str
    raw_doc_type: str | None
    doi: str | None
    serial_id: int | None
    corrections: dict[str, JsonValue]


class SerialCorrectionUpdate(NamedTuple):
    """Une mise à jour de rattachement : colonne `serial_id` (posée ou restaurée à NULL) + sidecar `corrections`. Produite par la sous-étape `serial_by_doi`, persistée via `persist_serial_corrections`."""

    id: int
    serial_id: int | None
    corrections: dict[str, JsonValue]


class DoiClusterRow(NamedTuple):
    """Une `source_record` candidate à la correction de DOI par cluster.

    `raw_doi` est le DOI **source reconstruit** (`corrections.doi.raw` ou colonne `doi`), en minuscules — clé de regroupement par DOI. `title_normalized` sert à la comparaison chapitre/chapitre. `canonical_doi` est le DOI de l'œuvre de référence quand `raw_doi` est une **forme secondaire** DataCite (version, forme variante, ou fichier de package), sinon `None` ; `same_work_case` donne alors le cas correspondant."""

    id: int
    doc_type: str | None
    doi: str | None
    title_normalized: str | None
    corrections: dict[str, JsonValue]
    raw_doi: str
    canonical_doi: str | None
    same_work_case: DoiClusterCase | None
    # `raw_doi` est inconnu de doi.org (`failed_lookups`, source `doi_org`).
    unresolved: bool = False
    external_ids: dict[str, JsonValue] = {}
    source: str = ""
    source_id: str = ""
    # Noms de famille normalisés des contributions sources individuelles, renseignés pour les groupes où un dépôt HAL et l'enregistrement source Crossref n'ont aucun nom commun.
    author_names: tuple[str, ...] = ()


class DoiCorrectionUpdate(NamedTuple):
    """Une mise à jour de la correction par cluster : colonne `doi` (nullée, restaurée ou substituée), sidecar, et identifiants externes (clés partagées avec une autre œuvre retirées ou restaurées). Persistée via `persist_doi_corrections`."""

    id: int
    doi: str | None
    corrections: dict[str, JsonValue]
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

# Expression SQL de chaque fait de `MetadataForCorrection`, sur l'enregistrement source `sr` et les jointures de `_SELECT`.
_FACTS: dict[str, str] = {
    "title": "sr.title",
    "doc_type": "sr.doc_type",
    "doi": "sr.doi",
    "serial_id": "sr.serial_id",
    "serial_type": "j.serial_type::text",
    "oa_status": "sr.oa_status",
    "oa_model": "j.oa_model",
    "urls": "sr.urls",
    "embargo_expired": "(sr.embargo_until IS NOT NULL AND sr.embargo_until <= current_date)",
    "self_declared_preprint": self_declared_preprint_sql(),
    "declares_conference": declares_conference_sql(),
    "registrant_publisher_type": "rp.publisher_type::text",
    "in_proceedings_volume": "COALESCE(m.proceedings, false)",
    "group_title": source_extra(SourceExtra.GROUP_TITLE),
    "journal_diamond": f"COALESCE({diamond_journal_sql('j')}, false)",
    "source": "sr.source::text",
    "author_count": "sr.author_count",
}
assert set(_FACTS) == {f.name for f in fields(MetadataForCorrection)}, (
    "projection des faits désynchronisée de MetadataForCorrection"
)

# Chaque variante ajoute son `WHERE`.
_SELECT = f"""
    SELECT sr.id, sr.source_id, sr.external_ids, sr.corrections,
           {", ".join(f"{expression} AS {name}" for name, expression in _FACTS.items())}
    FROM source_records sr
    LEFT JOIN serials j ON j.id = sr.serial_id
    LEFT JOIN monographs m ON m.id = sr.monograph_id
    LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(sr.doi, '/', 1)
    LEFT JOIN publishers rp ON rp.id = dp.publisher_id
"""


def _unary_rows(rows: Iterable[Row[tuple[object, ...]]]) -> list[UnaryCorrectionRow]:
    return [
        UnaryCorrectionRow(
            id=r.id,
            source_id=r.source_id,
            external_ids=r.external_ids,
            corrections=r.corrections,
            facts=MetadataForCorrection(**{name: r._mapping[name] for name in _FACTS}),
        )
        for r in rows
    ]


# Les colonnes du SET sont les clés des paramètres, typées par la table.
_UPDATE = (
    source_records.update()
    .where(source_records.c.id == bindparam("source_record_id"))
    .values(updated_at=func.clock_timestamp())
)


def _persist_updates(conn: Connection, updates: Sequence[Mapping[str, object]]) -> int:
    """UPDATE en lot sur `source_records` : chaque mise à jour pose ses colonnes sur l'enregistrement source de sa clé `id` et met à jour `updated_at`. Les enregistrements sources mis à jour sont marqués pour la réconciliation. Retourne le nombre de lignes.

    Lève `ValueError` sur une clé qui ne nomme aucune colonne de `source_records`.
    """
    if not updates:
        return 0
    unknown = sorted({k for u in updates for k in u} - set(source_records.c.keys()))
    if unknown:
        raise ValueError(f"Colonnes inconnues de source_records : {', '.join(unknown)}")
    params = [
        {"source_record_id": u["id"], **{k: v for k, v in u.items() if k != "id"}} for u in updates
    ]
    conn.execute(_UPDATE, params)
    enqueue(
        conn,
        Queue.SOURCE_RECORD_KEYS,
        "SELECT unnest(CAST(:ids AS integer[]))",
        {"ids": [u["id"] for u in updates]},
    )
    return len(updates)


# L'enregistrement source `{source_record}` a au moins une contribution source individuelle.
_HAS_INDIVIDUAL_SOURCE_CONTRIBUTION = (
    "EXISTS (SELECT 1 FROM source_contributions s"
    " WHERE s.source_record_id = {source_record} AND NOT s.collective)"
)


def _cluster_case(value: str | None) -> DoiClusterCase | None:
    """Convertit le cas rendu par le `CASE` SQL, dont les littéraux sont ceux de l'enum."""
    return DoiClusterCase(value) if value is not None else None


class SourceRecordCorrectionStore:
    """Requêtes de la phase `metadata_correction`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def fetch_for_unary_correction(self) -> list[UnaryCorrectionRow]:
        """Toutes les `source_records`, avec join `serials` et `corrections`.

        Pas de pré-filtre par règle : certaines règles sont inconditionnelles sur `doc_type` (URL theses.fr/DUMAS), et une `source_record` sans `doc_type` reste candidate. La cascade `effective_metadata` fait le filtrage fin.
        """
        return _unary_rows(self._conn.execute(text(_SELECT)))

    def fetch_for_unary_correction_by_serial(self, serial_id: int) -> list[UnaryCorrectionRow]:
        """Les `source_records` rattachées à un journal (`serial_id = :jid`).

        Recompute ciblé après un changement de `serial_type` (hook admin) : seules ces `source_records` voient leur correction journal-dépendante bouger."""
        return _unary_rows(
            self._conn.execute(text(_SELECT + " WHERE sr.serial_id = :jid"), {"jid": serial_id})
        )

    def fetch_for_unary_correction_by_hal_ids(self, hal_ids: list[str]) -> list[UnaryCorrectionRow]:
        """Les `source_records` HAL dont l'identifiant figure dans `hal_ids` : dépôts d'origine des enregistrements sources ScanR d'une correction ciblée."""
        if not hal_ids:
            return []
        return _unary_rows(
            self._conn.execute(
                text(_SELECT + " WHERE sr.source = 'hal' AND sr.source_id = ANY(:ids)"),
                {"ids": hal_ids},
            )
        )

    def persist_corrections(self, updates: list[CorrectionUpdate]) -> int:
        """UPDATE en lot des colonnes effectives + `corrections`, bump `updated_at`, marque pour la réconciliation — `doc_type` et `external_ids` sont des clés de matching, dont la mutation appelle une réconciliation. Retourne le nombre de lignes mises à jour."""
        return _persist_updates(
            self._conn, [{"id": u.id, **u.corrected._asdict()} for u in updates]
        )

    def fetch_missing_hal_ids(self) -> frozenset[str]:
        """Identifiants des dépôts HAL introuvables dans HAL (`failed_lookups`). HAL attribue les identifiants HAL : l'échec est définitif."""
        rows = self._conn.execute(
            text(f"""
                SELECT id_value FROM failed_lookups
                WHERE source = '{Source.HAL.value}' AND id_type = '{ExternalIdType.HAL_ID.value}'
            """)
        )
        return frozenset(rows.scalars())

    def delete_missing_hal_locations(self) -> int:
        """Supprime les localisations dont la correction unaire a retiré le lien des `urls` de leur enregistrement source (dépôt HAL introuvable). La normalisation réécrit les localisations : la suppression se rejoue à chaque passage. Retourne le nombre de localisations supprimées."""
        result = self._conn.execute(
            text(f"""
                DELETE FROM source_record_locations l
                USING source_records sr
                WHERE l.source_record_id = sr.id
                  AND sr.corrections -> '{CorrectionKey.URLS}' ->> '{CORRECTED_BY}'
                      = '{MetadataCorrectionRule.HAL_DEPOSIT_MISSING_TO_REMOVED}'
                  AND sr.corrections -> '{CorrectionKey.URLS}' -> '{RAW}' ? l.url
                  AND l.url <> ALL(COALESCE(sr.urls, '{{}}'))
            """)
        )
        return result.rowcount

    def fetch_matchability_rows(self) -> list[MatchabilityRow]:
        """Toutes les `source_records`, avec les faits que lit `is_matchable` et la valeur courante de `is_matchable`."""
        rows = self._conn.execute(
            text(f"""
                SELECT id, is_matchable, source::text AS source, source_id,
                       {raw_column("doi", "source_records")} AS raw_doi, doi, title_normalized,
                       COALESCE(urls, '{{}}') AS urls, external_ids
                FROM source_records
            """)
        )
        return [
            MatchabilityRow(
                r.id,
                r.is_matchable,
                MatchabilityFacts(
                    r.source,
                    r.source_id,
                    r.raw_doi,
                    r.doi,
                    r.title_normalized,
                    r.urls,
                    r.external_ids,
                ),
            )
            for r in rows
        ]

    def persist_matchability(self, updates: list[MatchabilityUpdate]) -> int:
        """UPDATE en lot de `is_matchable`, bump `updated_at`, marque pour la réconciliation. Retourne le nombre de lignes."""
        return _persist_updates(self._conn, [u._asdict() for u in updates])

    def fetch_serial_doi_namespaces(self) -> list[DoiNamespace]:
        """Le contenu de `serial_doi_namespaces`."""
        rows = self._conn.execute(
            text("SELECT namespace, serial_id, dois, share FROM serial_doi_namespaces")
        )
        return rows_as(DoiNamespace, rows)

    def fetch_serial_by_doi_candidates(self) -> list[SerialCorrectionRow]:
        """`source_records` candidates au rattachement : orphelines à DOI (`serial_id IS NULL AND doi IS NOT NULL`) et déjà rattachées par espace de noms (`corrections ? 'serial_id'`, pour la ré-évaluation auto-cicatrisante)."""
        rows = self._conn.execute(
            text(f"""
                SELECT id, source::text AS source, raw_doc_type,
                       doi, serial_id, corrections
                FROM source_records
                WHERE (serial_id IS NULL AND doi IS NOT NULL)
                   OR {corrected("serial_id", "source_records")}
            """)
        )
        return rows_as(SerialCorrectionRow, rows)

    def persist_serial_corrections(self, updates: list[SerialCorrectionUpdate]) -> int:
        """UPDATE en lot de la colonne `serial_id` + `corrections`, bump `updated_at`, marque pour la réconciliation (pour que la réconciliation rafraîchisse le `serial_id` de la publication — bien que `serial_id` ne soit pas une clé de matching). Retourne le nombre de lignes."""
        return _persist_updates(self._conn, [u._asdict() for u in updates])

    def fetch_doi_cluster_candidates(self) -> list[DoiClusterRow]:
        """Les membres des groupes-DOI candidats à la correction par cluster, avec leur `canonical_doi` éventuel : groupes contenant un `book`/`book_chapter`/`proceedings`, groupes dont le DOI est un DOI de version DataCite (`IsVersionOf`), groupes dont le DOI est inconnu de doi.org, groupes où un dépôt HAL n'a aucun nom d'auteur en commun avec l'enregistrement source Crossref, et `source_records` déjà corrigées (`corrections.doi` ou `corrections.removed_external_ids`) pour la ré-évaluation auto-cicatrisante."""
        rows = self._conn.execute(
            text(f"""
                WITH sr_eff AS (
                    SELECT id, source, source_id, doc_type, doi, title_normalized, publication_year,
                           corrections, source_extras, external_ids,
                           lower({raw_column("doi", "source_records")}) AS eff_doi
                    FROM source_records
                ),
                dataset_dois AS (
                    SELECT DISTINCT eff_doi AS d
                    FROM sr_eff
                    WHERE doc_type = '{DocType.DATASET.value}' AND eff_doi IS NOT NULL
                ),
                unresolved_dois AS (
                    SELECT id_value AS d FROM failed_lookups
                    WHERE source = '{DOI_ORG}' AND id_type = 'doi'
                ),
                -- Collections figshare typées dataset, une par titre et année : un titre partagé par deux collections n'en désigne aucune.
                figshare_collections AS (
                    SELECT title_normalized, publication_year, min(eff_doi) AS doi
                    FROM sr_eff
                    WHERE doc_type = '{DocType.DATASET.value}'
                      AND starts_with(eff_doi, '{FIGSHARE_COLLECTION_DOI_PREFIX}')
                    GROUP BY title_normalized, publication_year
                    HAVING count(DISTINCT eff_doi) = 1
                ),
                -- La cible reste attachée à l'enregistrement source DataCite dont les `related_identifiers`
                -- la mentionnent : la règle de même œuvre lit le type de cet enregistrement, et les
                -- autres enregistrements au même DOI suivent la décision du groupe. Quand un enregistrement
                -- mentionne plusieurs cibles, la version (concept) prime sur la variante. Une cible que
                -- doi.org ne connaît pas est écartée.
                same_work AS (
                    SELECT DISTINCT ON (declarant_id)
                           declarant_id, secondary_doi, canonical_doi, same_work_case
                    FROM (
                        SELECT
                            sr.id AS declarant_id,
                            sr.eff_doi AS secondary_doi,
                            lower(rel->>'doi') AS canonical_doi,
                            {_DATACITE_CASE_SQL} AS same_work_case
                        FROM sr_eff sr
                        CROSS JOIN LATERAL jsonb_array_elements({source_extra_json(SourceExtra.RELATED_IDENTIFIERS)}) rel
                        WHERE sr.source = '{Source.DATACITE.value}'
                          AND rel->>'relation_type' IN {_DATACITE_DIRECT_RELATIONS_SQL}
                          AND rel->>'doi' IS NOT NULL
                          AND lower(rel->>'doi') <> sr.eff_doi
                        UNION ALL
                        -- Pièce d'un dataset → dataset parent : le parent doit être présent en base
                        -- comme dataset pour absorber ses pièces (`IN dataset_dois`). Ça exclut le
                        -- parent article (un dataset supplémentaire d'un article ne s'y fond pas) et
                        -- le parent absent (les pièces attendent son moissonnage). La forme du DOI
                        -- n'intervient pas : les pièces portent souvent un DOI frère, pas suffixé.
                        SELECT
                            sr.id AS declarant_id,
                            sr.eff_doi AS secondary_doi,
                            lower(rel->>'doi') AS canonical_doi,
                            '{DoiClusterCase.DATACITE_PACKAGE_PIECE.value}' AS same_work_case
                        FROM sr_eff sr
                        CROSS JOIN LATERAL jsonb_array_elements({source_extra_json(SourceExtra.RELATED_IDENTIFIERS)}) rel
                        WHERE sr.source = '{Source.DATACITE.value}'
                          AND sr.doc_type = '{DocType.DATASET.value}'
                          AND rel->>'relation_type' = '{DATACITE_PACKAGE_PIECE_RELATION}'
                          AND rel->>'doi' IS NOT NULL
                          AND lower(rel->>'doi') <> sr.eff_doi
                          AND lower(rel->>'doi') IN (SELECT d FROM dataset_dois)
                        UNION ALL
                        -- Fichier complémentaire figshare « Additional file N of T » → collection
                        -- figshare de titre T, sans relation déclarée : la seule collection dataset
                        -- de même titre et de même année.
                        SELECT
                            sr.id AS declarant_id,
                            sr.eff_doi AS secondary_doi,
                            c.doi AS canonical_doi,
                            '{DoiClusterCase.DATACITE_PACKAGE_PIECE.value}' AS same_work_case
                        FROM sr_eff sr
                        JOIN figshare_collections c
                          ON c.title_normalized = regexp_replace(
                                 sr.title_normalized, '{FIGSHARE_ADDITIONAL_FILE_TITLE_PATTERN}', ''
                             )
                         AND c.publication_year = sr.publication_year
                        WHERE sr.source = '{Source.DATACITE.value}'
                          AND sr.doc_type = '{DocType.DATASET.value}'
                          AND sr.eff_doi ~ '{FIGSHARE_ITEM_DOI_PATTERN}'
                          AND sr.title_normalized ~ '{FIGSHARE_ADDITIONAL_FILE_TITLE_PATTERN}'
                    ) s
                    WHERE s.canonical_doi NOT IN (SELECT d FROM unresolved_dois)
                    ORDER BY declarant_id,
                             same_work_case = '{DoiClusterCase.DATACITE_VERSION_TO_CONCEPT.value}' DESC,
                             canonical_doi
                ),
                -- DOI dont un dépôt HAL n'a aucun nom d'auteur en commun avec l'enregistrement source Crossref,
                -- les deux ayant des contributions sources individuelles.
                hal_crossref AS MATERIALIZED (
                    SELECT h.eff_doi AS d, h.id AS hal_id, c.id AS crossref_id
                    FROM sr_eff h
                    JOIN sr_eff c ON c.eff_doi = h.eff_doi AND c.source = '{Source.CROSSREF.value}'
                    WHERE h.source = '{Source.HAL.value}' AND h.eff_doi IS NOT NULL
                ),
                foreign_hal_dois AS (
                    SELECT DISTINCT hc.d FROM hal_crossref hc
                    WHERE {_HAS_INDIVIDUAL_SOURCE_CONTRIBUTION.format(source_record="hc.hal_id")}
                      AND {_HAS_INDIVIDUAL_SOURCE_CONTRIBUTION.format(source_record="hc.crossref_id")}
                      AND NOT EXISTS (
                          SELECT 1
                          FROM source_contributions a
                          JOIN contributor_information ka ON ka.id = a.contributor_information_id
                          JOIN contributor_information kb
                            ON kb.last_name_normalized = ka.last_name_normalized
                          JOIN source_contributions b
                            ON b.contributor_information_id = kb.id AND b.source_record_id = hc.crossref_id
                          WHERE a.source_record_id = hc.hal_id
                            AND NOT a.collective AND NOT b.collective
                      )
                ),
                candidate_dois AS (
                    SELECT secondary_doi AS d FROM same_work
                    UNION
                    SELECT eff_doi AS d FROM sr_eff
                    WHERE doc_type IN ('{DocType.BOOK.value}', '{DocType.BOOK_CHAPTER.value}', '{DocType.PROCEEDINGS.value}')
                      AND eff_doi IS NOT NULL
                    UNION
                    SELECT eff_doi AS d FROM sr_eff
                    WHERE {corrected("doi", "sr_eff")}
                       OR {corrected(CorrectionKey.REMOVED_EXTERNAL_IDS, "sr_eff")}
                    UNION
                    SELECT d FROM unresolved_dois
                    UNION
                    SELECT d FROM foreign_hal_dois
                )
                SELECT sr.id, sr.doc_type, sr.doi, sr.title_normalized, sr.corrections,
                       sr.external_ids, sr.source::text AS source, sr.source_id,
                       sr.eff_doi AS raw_doi,
                       sw.canonical_doi, sw.same_work_case,
                       sr.eff_doi IN (SELECT d FROM unresolved_dois) AS unresolved,
                       CASE WHEN sr.eff_doi IN (SELECT d FROM foreign_hal_dois) THEN ARRAY(
                           SELECT DISTINCT ci.last_name_normalized
                           FROM source_contributions sc
                           JOIN contributor_information ci ON ci.id = sc.contributor_information_id
                           WHERE sc.source_record_id = sr.id AND NOT sc.collective
                             AND ci.last_name_normalized <> ''
                       ) ELSE ARRAY[]::text[] END AS author_names
                FROM sr_eff sr
                JOIN candidate_dois c ON c.d = sr.eff_doi
                LEFT JOIN same_work sw ON sw.declarant_id = sr.id
            """)
        ).all()
        return [
            DoiClusterRow(
                id=row.id,
                doc_type=row.doc_type,
                doi=row.doi,
                title_normalized=row.title_normalized,
                corrections=row.corrections,
                raw_doi=row.raw_doi,
                canonical_doi=row.canonical_doi,
                same_work_case=_cluster_case(row.same_work_case),
                unresolved=row.unresolved,
                external_ids=row.external_ids,
                source=row.source,
                source_id=row.source_id,
                author_names=tuple(row.author_names),
            )
            for row in rows
        ]

    def persist_doi_corrections(self, updates: list[DoiCorrectionUpdate]) -> int:
        """UPDATE en lot des colonnes `doi`, `external_ids` et `corrections`, bump `updated_at`, marque pour la réconciliation — DOI et identifiants externes sont des clés de confirmation, dont la mutation appelle une réconciliation. Retourne le nombre de lignes mises à jour.

        La publication de chaque enregistrement source est marquée pour le groupement des auteurs : le groupement des contributions sources écarte un enregistrement source dont le DOI converge sur celui d'une autre œuvre.
        """
        enqueue(
            self._conn,
            Queue.PUBLICATION_CONTRIBUTIONS,
            "SELECT publication_id FROM source_records"
            " WHERE id = ANY(:ids) AND publication_id IS NOT NULL",
            {"ids": [u.id for u in updates]},
        )
        return _persist_updates(self._conn, [u._asdict() for u in updates])
