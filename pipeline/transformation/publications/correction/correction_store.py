"""Requêtes de la phase `metadata_correction`, et du recalcul ciblé des corrections d'une revue.

La phase écrit sur les enregistrements sources les valeurs corrigées par les règles de `domain.source_records.metadata_correction`. La réconciliation lit donc des colonnes déjà corrigées.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import fields
from typing import NamedTuple

from sqlalchemy import Connection, Row, bindparam, func, text

from domain.publications.doc_types import DocType
from domain.publications.scope import MatchabilityFacts
from domain.serials.doi_namespaces import DoiNamespace
from domain.source_records.corrections import CORRECTED_BY, RAW, CorrectionKey
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    active,
    own_dois,
)
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
    DoiTarget,
    DoiTargetRule,
    SecondaryFormDeclaration,
)
from domain.source_records.metadata_correction.source_record import UnaryCorrection
from domain.source_records.source_extras import SourceExtra
from domain.sources.registry import DOI_ORG, Source
from domain.types import JsonValue
from infrastructure.db.doi_targets import unversioned_doi_sql
from infrastructure.db.queues import Queue, enqueue
from infrastructure.db.rows import rows_as
from infrastructure.db.source_record_identifiers import identifiers_json_sql, parse_identifiers
from infrastructure.db.tables import source_records
from infrastructure.sql_fragments import (
    corrected,
    declares_conference_sql,
    diamond_journal_sql,
    self_declared_preprint_sql,
    source_extra,
    source_extra_json,
)


class UnaryCorrectionRow(NamedTuple):
    """Enregistrement source candidat à la correction unaire : faits lus par les règles, identifiants avec leur statut, et `corrections`, réécrit par la phase."""

    id: int
    source_id: str
    corrections: dict[str, JsonValue]
    facts: MetadataForCorrection
    identifiers: tuple[SourceIdentifier, ...] = ()


class CorrectionUpdate(NamedTuple):
    """Mise à jour de la correction unaire de l'enregistrement source `id` : colonnes corrigées et identifiants."""

    id: int
    corrected: UnaryCorrection


class MatchabilityRow(NamedTuple):
    """Enregistrement source, avec sa valeur de `is_matchable` et les faits qui la décident."""

    id: int
    is_matchable: bool
    facts: MatchabilityFacts


class MatchabilityUpdate(NamedTuple):
    """Nouvelle valeur de `is_matchable` de l'enregistrement source `id`."""

    id: int
    is_matchable: bool


class SerialCorrectionRow(NamedTuple):
    """Enregistrement source candidat au rattachement de la revue par l'espace de noms de ses DOI."""

    id: int
    source: str
    raw_doc_type: str | None
    dois: frozenset[str]
    """DOI propres actifs."""
    serial_id: int | None
    corrections: dict[str, JsonValue]
    """Garde le rattachement d'origine, et limite la correction à une revue manquante."""


class SerialCorrectionUpdate(NamedTuple):
    """Mise à jour du rattachement de revue d'un enregistrement source."""

    id: int
    serial_id: int | None
    """Revue rattachée, ou `None` pour retirer le rattachement."""
    corrections: dict[str, JsonValue]


class SecondaryFormRow(NamedTuple):
    """Déclaration de forme secondaire d'un enregistrement source."""

    doi: str
    """DOI d'avant correction, en minuscules."""
    declaration: SecondaryFormDeclaration


class DoiClusterRow(NamedTuple):
    """Enregistrement source membre d'un groupe candidat au retrait de DOI.

    Le groupe réunit les enregistrements sources ayant le DOI `shared_doi`, de rôle autre que `related`, quel que soit son statut. Un enregistrement source appartient à un groupe par DOI.
    """

    id: int
    doc_type: str | None
    title_normalized: str | None
    """Sert à comparer deux chapitres."""
    shared_doi: str
    unresolved: bool = False
    """Vrai si `shared_doi` est inconnu de doi.org (`failed_lookups`, source `doi_org`)."""
    has_target: bool = False
    """Vrai si `shared_doi` a une cible dans `doi_targets`."""
    identifiers: tuple[SourceIdentifier, ...] = ()
    source: str = ""
    source_id: str = ""
    author_names: tuple[str, ...] = ()
    """Noms de famille normalisés des contributions sources individuelles, renseignés pour les groupes où un dépôt HAL et l'enregistrement source Crossref n'ont aucun nom commun."""


class DoiCorrectionUpdate(NamedTuple):
    """Mise à jour du retrait de DOI par groupe : identifiants de l'enregistrement source aux statuts recalculés."""

    id: int
    identifiers: tuple[SourceIdentifier, ...]


# Branches du `CASE` et liste `IN` des relations DataCite de `DATACITE_DIRECT_CONVERGENCE`.
_DATACITE_CASE_SQL = (
    "CASE rel->>'relation_type' "
    + " ".join(
        f"WHEN '{relation}' THEN '{case.value}'"
        for relation, case in DATACITE_DIRECT_CONVERGENCE.items()
    )
    + " END"
)
_CLUSTER_CASES_SQL = ", ".join(f"'{case.value}'" for case in DoiClusterCase)
_DATACITE_DIRECT_RELATIONS_SQL = (
    "(" + ", ".join(f"'{relation}'" for relation in DATACITE_DIRECT_CONVERGENCE) + ")"
)

# Expression SQL de chaque fait de `MetadataForCorrection`, sur l'enregistrement source `sr` et les jointures de `_SELECT`. Les faits de `_DOI_FACTS` se calculent sur les identifiants (`_unary_rows`).
_FACTS: dict[str, str] = {
    "title": "sr.title",
    "doc_type": "sr.doc_type",
    "serial_id": "sr.serial_id",
    "serial_type": "j.serial_type::text",
    "oa_status": "sr.oa_status",
    "oa_model": "j.oa_model",
    "urls": "sr.urls",
    "embargo_expired": "(sr.embargo_until IS NOT NULL AND sr.embargo_until <= current_date)",
    "self_declared_preprint": self_declared_preprint_sql(),
    "declares_conference": declares_conference_sql(),
    "in_proceedings_volume": "COALESCE(m.proceedings, false)",
    "group_title": source_extra(SourceExtra.GROUP_TITLE),
    "journal_diamond": f"COALESCE({diamond_journal_sql('j')}, false)",
    "source": "sr.source::text",
    "author_count": "sr.author_count",
}
_DOI_FACTS = frozenset({"dois", "registrant_publisher_types"})
assert set(_FACTS) | _DOI_FACTS == {f.name for f in fields(MetadataForCorrection)}, (
    "projection des faits désynchronisée de MetadataForCorrection"
)

_UPDATE_STATUSES = text("""
    UPDATE source_record_identifiers i SET removed_by = s.removed_by
    FROM jsonb_to_recordset(CAST(:rows AS jsonb))
        AS s(source_record_id integer, id_type text, id_value text, removed_by text)
    WHERE i.source_record_id = s.source_record_id AND i.id_type::text = s.id_type
      AND i.id_value = s.id_value AND i.removed_by IS DISTINCT FROM s.removed_by
""")


def _persist_statuses(
    conn: Connection, identifiers_by_source_record: Mapping[int, Iterable[SourceIdentifier]]
) -> None:
    """Écrit le statut de chaque identifiant des enregistrements sources donnés."""
    rows = [
        {
            "source_record_id": source_record_id,
            "id_type": i.id_type.value,
            "id_value": i.value,
            "removed_by": i.removed_by,
        }
        for source_record_id, identifiers in identifiers_by_source_record.items()
        for i in identifiers
    ]
    if rows:
        conn.execute(_UPDATE_STATUSES, {"rows": json.dumps(rows)})


# Chaque variante ajoute son `WHERE`.
_SELECT = f"""
    SELECT sr.id, sr.source_id, sr.corrections,
           {identifiers_json_sql("sr.id")} AS identifiers,
           {", ".join(f"{expression} AS {name}" for name, expression in _FACTS.items())}
    FROM source_records sr
    LEFT JOIN serials j ON j.id = sr.serial_id
    LEFT JOIN monographs m ON m.id = sr.monograph_id
"""


def _unary_row(
    r: Row[tuple[object, ...]], registrant_types: Mapping[str, str]
) -> UnaryCorrectionRow:
    identifiers = parse_identifiers(r.identifiers)
    dois = frozenset(own_dois(active(identifiers)))
    types = {registrant_types.get(doi.split("/", 1)[0]) for doi in dois}
    return UnaryCorrectionRow(
        id=r.id,
        source_id=r.source_id,
        corrections=r.corrections,
        facts=MetadataForCorrection(
            **{name: r._mapping[name] for name in _FACTS},
            dois=dois,
            registrant_publisher_types=frozenset(t for t in types if t is not None),
        ),
        identifiers=identifiers,
    )


# Les colonnes du SET sont les clés des paramètres, typées par la table.
_UPDATE = (
    source_records.update()
    .where(source_records.c.id == bindparam("source_record_id"))
    .values(updated_at=func.clock_timestamp())
)


def _persist_updates(conn: Connection, updates: Sequence[Mapping[str, object]]) -> int:
    """Écrit en lot les colonnes de chaque mise à jour sur l'enregistrement source de clé `id`, avec `updated_at`, et marque ces enregistrements sources pour la réconciliation. Renvoie le nombre de lignes.

    Raises:
        ValueError: une clé ne nomme aucune colonne de `source_records`.
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


class SourceRecordCorrectionStore:
    """Requêtes de la phase `metadata_correction`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def fetch_for_unary_correction(self) -> list[UnaryCorrectionRow]:
        """Renvoie tous les enregistrements sources, avec les faits lus par les règles.

        Certaines règles valent quel que soit le type (URL theses.fr ou DUMAS), et un enregistrement source sans type reste candidat : aucun filtre par règle.
        """
        return self._unary_rows(_SELECT, {})

    def fetch_for_unary_correction_by_serial(self, serial_id: int) -> list[UnaryCorrectionRow]:
        """Renvoie les enregistrements sources d'une revue, pour le recalcul ciblé après un changement de son type dans l'administration."""
        return self._unary_rows(_SELECT + " WHERE sr.serial_id = :jid", {"jid": serial_id})

    def fetch_for_unary_correction_by_hal_ids(self, hal_ids: list[str]) -> list[UnaryCorrectionRow]:
        """Renvoie les enregistrements sources HAL de ces identifiants : dépôts d'origine des enregistrements sources ScanR d'une correction ciblée."""
        if not hal_ids:
            return []
        return self._unary_rows(
            _SELECT + " WHERE sr.source = 'hal' AND sr.source_id = ANY(:ids)", {"ids": hal_ids}
        )

    def _unary_rows(self, query: str, params: Mapping[str, object]) -> list[UnaryCorrectionRow]:
        registrant_types: dict[str, str] = dict(
            self._conn.execute(
                text("""
                    SELECT dp.prefix, p.publisher_type::text
                    FROM doi_prefixes dp JOIN publishers p ON p.id = dp.publisher_id
                    WHERE p.publisher_type IS NOT NULL
                """)
            ).all()
        )
        return [_unary_row(r, registrant_types) for r in self._conn.execute(text(query), params)]

    def persist_corrections(self, updates: list[CorrectionUpdate]) -> int:
        """Écrit en lot les colonnes corrigées, `corrections` et les statuts des identifiants. Marque les enregistrements sources pour la réconciliation : leur type et leurs identifiants sont des clés. Renvoie le nombre de lignes."""
        _persist_statuses(self._conn, {u.id: u.corrected.identifiers for u in updates})
        return _persist_updates(
            self._conn, [{"id": u.id, **u.corrected.columns._asdict()} for u in updates]
        )

    def fetch_missing_hal_ids(self) -> frozenset[str]:
        """Renvoie les identifiants des dépôts HAL introuvables dans HAL (`failed_lookups`). HAL attribue les identifiants HAL : l'échec est définitif."""
        rows = self._conn.execute(
            text(f"""
                SELECT id_value FROM failed_lookups
                WHERE source = '{Source.HAL.value}' AND id_type = '{SourceIdentifierType.HAL_ID.value}'
            """)
        )
        return frozenset(rows.scalars())

    def delete_missing_hal_locations(self) -> int:
        """Supprime les localisations à lien retiré des `urls` de leur enregistrement source par la correction unaire (dépôt HAL introuvable). La normalisation réécrit les localisations, donc la suppression se rejoue à chaque passage. Renvoie le nombre de localisations supprimées."""
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
        """Renvoie tous les enregistrements sources, avec leur valeur de `is_matchable` et les faits qui la décident."""
        rows = self._conn.execute(
            text(f"""
                SELECT id, is_matchable, source::text AS source, source_id, title_normalized,
                       COALESCE(urls, '{{}}') AS urls,
                       {identifiers_json_sql("source_records.id")} AS identifiers,
                       EXISTS (
                           SELECT 1 FROM source_record_identifiers p
                           JOIN doi_targets t ON t.doi = p.id_value
                           JOIN source_record_identifiers o
                             ON o.id_value = t.target_doi
                            AND o.id_type = '{SourceIdentifierType.DOI.value}'
                            AND o.role = '{SourceIdentifierRole.PRIMARY.value}'
                            AND o.source_record_id <> source_records.id
                           WHERE p.source_record_id = source_records.id
                             AND p.id_type = '{SourceIdentifierType.DOI.value}'
                             AND p.role = '{SourceIdentifierRole.PRIMARY.value}'
                       ) AS primary_doi_target_recorded
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
                    r.title_normalized,
                    r.urls,
                    parse_identifiers(r.identifiers),
                    r.primary_doi_target_recorded,
                ),
            )
            for r in rows
        ]

    def persist_matchability(self, updates: list[MatchabilityUpdate]) -> int:
        """Écrit en lot `is_matchable`, et marque les enregistrements sources pour la réconciliation. Renvoie le nombre de lignes."""
        return _persist_updates(self._conn, [u._asdict() for u in updates])

    def fetch_serial_doi_namespaces(self) -> list[DoiNamespace]:
        """Renvoie les espaces de noms DOI des revues (`serial_doi_namespaces`)."""
        rows = self._conn.execute(
            text("SELECT namespace, serial_id, dois, share FROM serial_doi_namespaces")
        )
        return rows_as(DoiNamespace, rows)

    def fetch_serial_by_doi_candidates(self) -> list[SerialCorrectionRow]:
        """Renvoie les enregistrements sources candidats au rattachement : sans revue avec un DOI actif, ou déjà rattachés par espace de noms, pour réévaluation."""
        rows = self._conn.execute(
            text(f"""
                SELECT sr.id, sr.source::text AS source, sr.raw_doc_type,
                       sr.serial_id, sr.corrections,
                       {identifiers_json_sql("sr.id")} AS identifiers
                FROM source_records sr
                WHERE (sr.serial_id IS NULL AND EXISTS (
                          SELECT 1 FROM source_record_identifiers i
                          WHERE i.source_record_id = sr.id
                            AND i.id_type = '{SourceIdentifierType.DOI.value}'
                            AND i.role <> '{SourceIdentifierRole.RELATED.value}'
                            AND i.removed_by IS NULL))
                   OR {corrected("serial_id")}
            """)
        )
        return [
            SerialCorrectionRow(
                id=r.id,
                source=r.source,
                raw_doc_type=r.raw_doc_type,
                dois=frozenset(own_dois(active(parse_identifiers(r.identifiers)))),
                serial_id=r.serial_id,
                corrections=r.corrections,
            )
            for r in rows
        ]

    def persist_serial_corrections(self, updates: list[SerialCorrectionUpdate]) -> int:
        """Écrit en lot `serial_id` et `corrections`, et marque les enregistrements sources pour la réconciliation, qui recalcule la revue de la publication. Renvoie le nombre de lignes."""
        return _persist_updates(self._conn, [u._asdict() for u in updates])

    def fetch_versioned_dois(self) -> list[str]:
        """Renvoie les DOI à suffixe de version des enregistrements sources, de rôle autre que `related`, quel que soit leur statut."""
        rows = self._conn.execute(
            text(f"""
                SELECT DISTINCT id_value FROM source_record_identifiers
                WHERE id_type = '{SourceIdentifierType.DOI.value}'
                  AND role <> '{SourceIdentifierRole.RELATED.value}'
                  AND {unversioned_doi_sql("id_value")} IS NOT NULL
            """)
        )
        return list(rows.scalars())

    def fetch_anchor_dois(self, dois: Iterable[str]) -> frozenset[str]:
        """Renvoie les DOI de `dois` actifs en rôle `primary` ou `derived` d'un enregistrement source : ancres de la réconciliation."""
        rows = self._conn.execute(
            text(f"""
                SELECT DISTINCT id_value FROM source_record_identifiers
                WHERE id_type = '{SourceIdentifierType.DOI.value}'
                  AND role IN ('{SourceIdentifierRole.PRIMARY.value}', '{SourceIdentifierRole.DERIVED.value}')
                  AND removed_by IS NULL
                  AND id_value = ANY(:dois)
            """),
            {"dois": sorted(set(dois))},
        )
        return frozenset(rows.scalars())

    def fetch_secondary_form_declarations(self) -> list[SecondaryFormRow]:
        """Renvoie les déclarations de forme secondaire, une par enregistrement source : DOI déclaré forme secondaire d'une œuvre principale présente en base. Un DOI inconnu de doi.org, déclaré ou cible, est écarté."""
        rows = self._conn.execute(
            text(f"""
                WITH sr_eff AS (
                    SELECT id, source, doc_type, title_normalized, publication_year, source_extras
                    FROM source_records
                ),
                -- DOI de rôle autre que `related` de chaque enregistrement source, quel que soit leur statut.
                record_dois AS (
                    SELECT source_record_id AS id, id_value AS doi, role
                    FROM source_record_identifiers
                    WHERE id_type = '{SourceIdentifierType.DOI.value}'
                      AND role <> '{SourceIdentifierRole.RELATED.value}'
                ),
                dataset_dois AS (
                    SELECT DISTINCT d.doi AS d
                    FROM sr_eff sr JOIN record_dois d ON d.id = sr.id
                    WHERE sr.doc_type = '{DocType.DATASET.value}'
                ),
                unresolved_dois AS (
                    SELECT id_value AS d FROM failed_lookups
                    WHERE source = '{DOI_ORG}' AND id_type = 'doi'
                ),
                -- Collections figshare typées dataset, une par titre et année : un titre partagé par deux collections n'en désigne aucune.
                figshare_collections AS (
                    SELECT sr.title_normalized, sr.publication_year, min(d.doi) AS doi
                    FROM sr_eff sr JOIN record_dois d ON d.id = sr.id
                    WHERE sr.doc_type = '{DocType.DATASET.value}'
                      AND starts_with(d.doi, '{FIGSHARE_COLLECTION_DOI_PREFIX}')
                    GROUP BY sr.title_normalized, sr.publication_year
                    HAVING count(DISTINCT d.doi) = 1
                ),
                -- DOI présents en base : DOI de rôle autre que `related` des enregistrements sources, hors retraits de la correction unaire.
                present_dois AS (
                    SELECT DISTINCT id_value AS d FROM source_record_identifiers
                    WHERE id_type = '{SourceIdentifierType.DOI.value}'
                      AND role <> '{SourceIdentifierRole.RELATED.value}'
                      AND (removed_by IS NULL OR removed_by IN ({_CLUSTER_CASES_SQL}))
                ),
                -- DOI `primary` de chaque enregistrement source DataCite, son DOI propre.
                datacite_dois AS (
                    SELECT d.id, d.doi FROM record_dois d
                    JOIN sr_eff sr ON sr.id = d.id
                    WHERE sr.source = '{Source.DATACITE.value}'
                      AND d.role = '{SourceIdentifierRole.PRIMARY.value}'
                ),
                -- La règle de même œuvre lit le type de l'enregistrement source DataCite dont les
                -- `related_identifiers` mentionnent la cible. Quand un enregistrement mentionne plusieurs
                -- cibles, la version (concept) prime sur la variante.
                same_work AS (
                    SELECT DISTINCT ON (declarant_id)
                           declarant_id, doc_type, secondary_doi, canonical_doi, same_work_case
                    FROM (
                        SELECT
                            sr.id AS declarant_id,
                            sr.doc_type,
                            own.doi AS secondary_doi,
                            lower(rel->>'doi') AS canonical_doi,
                            {_DATACITE_CASE_SQL} AS same_work_case
                        FROM sr_eff sr
                        JOIN datacite_dois own ON own.id = sr.id
                        CROSS JOIN LATERAL jsonb_array_elements({source_extra_json(SourceExtra.RELATED_IDENTIFIERS)}) rel
                        WHERE rel->>'relation_type' IN {_DATACITE_DIRECT_RELATIONS_SQL}
                          AND rel->>'doi' IS NOT NULL
                          AND lower(rel->>'doi') <> own.doi
                          AND lower(rel->>'doi') IN (SELECT d FROM present_dois)
                        UNION ALL
                        -- Pièce d'un dataset → dataset parent : le parent doit être présent en base
                        -- comme dataset pour absorber ses pièces (`IN dataset_dois`). Ça exclut le
                        -- parent article (un dataset supplémentaire d'un article ne s'y fond pas) et
                        -- le parent absent (les pièces attendent son moissonnage). La forme du DOI
                        -- n'intervient pas : les pièces portent souvent un DOI frère, pas suffixé.
                        SELECT
                            sr.id AS declarant_id,
                            sr.doc_type,
                            own.doi AS secondary_doi,
                            lower(rel->>'doi') AS canonical_doi,
                            '{DoiTargetRule.DATACITE_PACKAGE_PIECE.value}' AS same_work_case
                        FROM sr_eff sr
                        JOIN datacite_dois own ON own.id = sr.id
                        CROSS JOIN LATERAL jsonb_array_elements({source_extra_json(SourceExtra.RELATED_IDENTIFIERS)}) rel
                        WHERE sr.doc_type = '{DocType.DATASET.value}'
                          AND rel->>'relation_type' = '{DATACITE_PACKAGE_PIECE_RELATION}'
                          AND rel->>'doi' IS NOT NULL
                          AND lower(rel->>'doi') <> own.doi
                          AND lower(rel->>'doi') IN (SELECT d FROM dataset_dois)
                        UNION ALL
                        -- Fichier complémentaire figshare « Additional file N of T » → collection
                        -- figshare de titre T, sans relation déclarée : la seule collection dataset
                        -- de même titre et de même année. Le DOI et le titre désignent la pièce,
                        -- quels que soient sa source et son type.
                        SELECT
                            sr.id AS declarant_id,
                            sr.doc_type,
                            piece.doi AS secondary_doi,
                            c.doi AS canonical_doi,
                            '{DoiTargetRule.DATACITE_PACKAGE_PIECE.value}' AS same_work_case
                        FROM sr_eff sr
                        JOIN record_dois piece ON piece.id = sr.id
                        JOIN figshare_collections c
                          ON c.title_normalized = regexp_replace(
                                 sr.title_normalized, '{FIGSHARE_ADDITIONAL_FILE_TITLE_PATTERN}', ''
                             )
                         AND c.publication_year = sr.publication_year
                        WHERE piece.doi ~ '{FIGSHARE_ITEM_DOI_PATTERN}'
                          AND sr.title_normalized ~ '{FIGSHARE_ADDITIONAL_FILE_TITLE_PATTERN}'
                    ) s
                    WHERE s.canonical_doi NOT IN (SELECT d FROM unresolved_dois)
                      AND s.secondary_doi NOT IN (SELECT d FROM unresolved_dois)
                    ORDER BY declarant_id,
                             same_work_case = '{DoiTargetRule.DATACITE_VERSION_TO_CONCEPT.value}' DESC,
                             canonical_doi
                )
                SELECT declarant_id AS id, doc_type, secondary_doi AS doi,
                       canonical_doi AS target_doi, same_work_case AS rule
                FROM same_work
            """)
        ).all()
        return [
            SecondaryFormRow(
                row.doi,
                SecondaryFormDeclaration(
                    row.id, row.doc_type, row.target_doi, DoiTargetRule(row.rule)
                ),
            )
            for row in rows
        ]

    def fetch_doi_cluster_candidates(self) -> list[DoiClusterRow]:
        """Renvoie les membres des groupes de même DOI candidats au retrait du DOI.

        Un groupe réunit les enregistrements sources ayant son DOI, de rôle autre que `related`, quel que soit son statut. Un groupe est candidat si :

        - il contient un livre, un chapitre ou un volume d'actes ;
        - son DOI est inconnu de doi.org ;
        - un de ses dépôts HAL partage zéro nom d'auteur avec son enregistrement source Crossref ;
        - il contient un enregistrement source déjà corrigé, à réévaluer.
        """
        rows = self._conn.execute(
            text(f"""
                WITH sr_eff AS (
                    SELECT id, source, source_id, doc_type, title_normalized
                    FROM source_records
                ),
                record_dois AS (
                    SELECT source_record_id AS id, id_value AS doi
                    FROM source_record_identifiers
                    WHERE id_type = '{SourceIdentifierType.DOI.value}'
                      AND role <> '{SourceIdentifierRole.RELATED.value}'
                ),
                unresolved_dois AS (
                    SELECT id_value AS d FROM failed_lookups
                    WHERE source = '{DOI_ORG}' AND id_type = 'doi'
                ),
                -- DOI dont un dépôt HAL n'a aucun nom d'auteur en commun avec l'enregistrement source Crossref,
                -- les deux ayant des contributions sources individuelles.
                hal_crossref AS MATERIALIZED (
                    SELECT hd.doi AS d, h.id AS hal_id, c.id AS crossref_id
                    FROM sr_eff h
                    JOIN record_dois hd ON hd.id = h.id
                    JOIN record_dois cd ON cd.doi = hd.doi
                    JOIN sr_eff c ON c.id = cd.id AND c.source = '{Source.CROSSREF.value}'
                    WHERE h.source = '{Source.HAL.value}'
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
                    SELECT d.doi AS d FROM record_dois d JOIN sr_eff sr ON sr.id = d.id
                    WHERE sr.doc_type IN ('{DocType.BOOK.value}', '{DocType.BOOK_CHAPTER.value}', '{DocType.PROCEEDINGS.value}')
                    UNION
                    SELECT d.doi AS d FROM record_dois d
                    WHERE EXISTS (
                        SELECT 1 FROM source_record_identifiers i
                        WHERE i.source_record_id = d.id
                          AND i.removed_by IN ({_CLUSTER_CASES_SQL})
                    )
                    UNION
                    SELECT d FROM unresolved_dois
                    UNION
                    SELECT d FROM foreign_hal_dois
                )
                SELECT sr.id, sr.doc_type, sr.title_normalized,
                       sr.source::text AS source, sr.source_id,
                       {identifiers_json_sql("sr.id")} AS identifiers,
                       m.doi AS shared_doi,
                       m.doi IN (SELECT d FROM unresolved_dois) AS unresolved,
                       EXISTS (SELECT 1 FROM doi_targets t WHERE t.doi = m.doi) AS has_target,
                       CASE WHEN m.doi IN (SELECT d FROM foreign_hal_dois) THEN ARRAY(
                           SELECT DISTINCT ci.last_name_normalized
                           FROM source_contributions sc
                           JOIN contributor_information ci ON ci.id = sc.contributor_information_id
                           WHERE sc.source_record_id = sr.id AND NOT sc.collective
                             AND ci.last_name_normalized <> ''
                       ) ELSE ARRAY[]::text[] END AS author_names
                FROM candidate_dois c
                JOIN record_dois m ON m.doi = c.d
                JOIN sr_eff sr ON sr.id = m.id
            """)
        ).all()
        return [
            DoiClusterRow(
                id=row.id,
                doc_type=row.doc_type,
                title_normalized=row.title_normalized,
                shared_doi=row.shared_doi,
                unresolved=row.unresolved,
                has_target=row.has_target,
                identifiers=parse_identifiers(row.identifiers),
                source=row.source,
                source_id=row.source_id,
                author_names=tuple(row.author_names),
            )
            for row in rows
        ]

    def replace_doi_targets(self, targets: list[DoiTarget]) -> int:
        """Réécrit `doi_targets` avec les cibles données. Les enregistrements sources à DOI de cible changée sont marqués pour la réconciliation. Renvoie le nombre de DOI à cible changée."""
        current = {
            r.doi: (r.target_doi, r.rule)
            for r in self._conn.execute(text("SELECT doi, target_doi, rule FROM doi_targets"))
        }
        new = {t.doi: (t.target_doi, t.rule.value) for t in targets}
        changed = sorted(d for d in current.keys() | new.keys() if current.get(d) != new.get(d))
        if not changed:
            return 0
        self._conn.execute(
            text("DELETE FROM doi_targets WHERE doi = ANY(:dois)"), {"dois": changed}
        )
        inserted = [
            {"doi": d, "target_doi": new[d][0], "rule": new[d][1]} for d in changed if d in new
        ]
        if inserted:
            self._conn.execute(
                text(
                    "INSERT INTO doi_targets (doi, target_doi, rule)"
                    " VALUES (:doi, :target_doi, :rule)"
                ),
                inserted,
            )
        enqueue(
            self._conn,
            Queue.SOURCE_RECORD_KEYS,
            f"""
            SELECT DISTINCT source_record_id FROM source_record_identifiers
            WHERE id_type = '{SourceIdentifierType.DOI.value}'
              AND role <> '{SourceIdentifierRole.RELATED.value}' AND id_value = ANY(:dois)
            """,
            {"dois": changed},
        )
        return len(changed)

    def persist_doi_corrections(self, updates: list[DoiCorrectionUpdate]) -> int:
        """Écrit en lot les statuts des identifiants. Marque les enregistrements sources pour la réconciliation : leurs identifiants sont des clés. Renvoie le nombre de lignes."""
        _persist_statuses(self._conn, {u.id: u.identifiers for u in updates})
        return _persist_updates(self._conn, [{"id": u.id} for u in updates])
