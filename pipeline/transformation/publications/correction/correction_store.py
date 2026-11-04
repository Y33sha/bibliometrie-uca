"""Requêtes de la phase `metadata_correction`, et du recalcul ciblé des corrections d'une revue.

La phase écrit sur les enregistrements sources les valeurs corrigées par les règles de `domain.source_records.metadata_correction`. La réconciliation lit donc des colonnes déjà corrigées.
"""

import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import fields
from typing import NamedTuple, cast

from sqlalchemy import Connection, Row, bindparam, func, text

from domain.documents.doc_types import DocType
from domain.publications.scope import MatchabilityFacts
from domain.serials.doi_namespaces import DoiNamespace
from domain.source_records.corrections import CORRECTED_BY, RAW, CorrectionKey
from domain.source_records.identifiers import (
    STRONG_ROLES,
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
from domain.source_records.metadata_correction.serial_by_doi import (
    NAMESPACE_DOI_REMOVALS,
    namespace_dois,
)
from domain.source_records.metadata_correction.shared_doi import (
    CLUSTER_CANDIDATE_DOC_TYPES,
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
from domain.source_records.metadata_correction.unary import UnaryCorrection
from domain.source_records.source_extras import SourceExtra
from domain.sources.registry import DOI_ORG, Source
from domain.types import JsonValue
from infrastructure.db.doi_targets import unversioned_doi_sql
from infrastructure.db.queues import Queue, enqueue, enqueue_ids
from infrastructure.db.rows import rows_as
from infrastructure.db.source_record_identifiers import (
    fetch_identifiers,
    identifiers_json_sql,
    non_related_doi_sql,
    parse_identifiers,
)
from infrastructure.db.tables import source_records
from infrastructure.sql_fragments import (
    corrected,
    declares_conference_sql,
    in_clause,
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
    author_names: tuple[str, ...] = ()
    """Noms de famille normalisés des contributions sources individuelles, renseignés pour les groupes où un enregistrement source a un titre éloigné de celui de l'enregistrement source Crossref."""


class CrossrefTitlePair(NamedTuple):
    """Enregistrement source qui partage un DOI avec un enregistrement source Crossref."""

    doi: str
    title_normalized: str | None
    crossref_title_normalized: str | None


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
_CLUSTER_CANDIDATE_DOC_TYPES_SQL = ", ".join(
    f"'{doc_type}'" for doc_type in sorted(CLUSTER_CANDIDATE_DOC_TYPES)
)
_DATACITE_DIRECT_RELATIONS_SQL = (
    "(" + ", ".join(f"'{relation}'" for relation in DATACITE_DIRECT_CONVERGENCE) + ")"
)

_FACTS: dict[str, str] = {
    "title": "sr.title",
    "title_normalized": "COALESCE(sr.title_normalized, '')",
    "doc_type": "sr.doc_type",
    "serial_id": "sr.serial_id",
    "serial_type": "j.serial_type::text",
    "serial_title": "j.title",
    "urls": "sr.urls",
    "self_declared_preprint": self_declared_preprint_sql(),
    "declares_conference": declares_conference_sql(),
    "in_proceedings_volume": "COALESCE(m.proceedings, false)",
    "group_title": source_extra(SourceExtra.GROUP_TITLE),
    "source": "sr.source::text",
    "author_count": "sr.author_count",
}
"""Expression SQL de chaque fait de `MetadataForCorrection`, sur l'enregistrement source `sr` et les jointures de `_SELECT`. Les faits de `_DOI_FACTS` se calculent sur les identifiants (`_unary_rows`)."""
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


_SELECT = f"""
    SELECT sr.id, sr.source_id, sr.corrections,
           {", ".join(f"{expression} AS {name}" for name, expression in _FACTS.items())}
    FROM source_records sr
    LEFT JOIN serials j ON j.id = sr.serial_id
    LEFT JOIN monographs m ON m.id = sr.monograph_id
"""
"""Chaque variante ajoute son `WHERE`."""


def _unary_row(
    r: Row[tuple[object, ...]],
    identifiers: tuple[SourceIdentifier, ...],
    registrant_types: Mapping[str, str],
) -> UnaryCorrectionRow:
    dois = frozenset(own_dois(active(identifiers)))
    types = {registrant_types.get(doi.split("/", 1)[0]) for doi in dois}
    columns = r._mapping
    return UnaryCorrectionRow(
        id=r.id,
        source_id=r.source_id,
        corrections=r.corrections,
        facts=MetadataForCorrection(
            **{name: columns[name] for name in _FACTS},
            dois=dois,
            registrant_publisher_types=frozenset(t for t in types if t is not None),
        ),
        identifiers=identifiers,
    )


_UPDATE = (
    source_records.update()
    .where(source_records.c.id == bindparam("source_record_id"))
    .values(updated_at=func.clock_timestamp())
)
"""Les colonnes du SET sont les clés des paramètres, typées par la table."""


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
    enqueue_ids(conn, Queue.SOURCE_RECORD_KEYS, [cast("int", u["id"]) for u in updates])
    return len(updates)


_UNRESOLVED_DOIS_SQL = (
    f"SELECT id_value AS d FROM failed_lookups WHERE source = '{DOI_ORG}' AND id_type = 'doi'"
)
"""DOI inconnus de doi.org."""

_RECORD_DOIS_SQL = f"""
    SELECT source_record_id AS id, id_value AS doi, role
    FROM source_record_identifiers
    WHERE {non_related_doi_sql("source_record_identifiers")}
"""
"""DOI de rôle autre que `related` de chaque enregistrement source, quel que soit leur statut."""


class SourceRecordCorrectionStore:
    """Requêtes de la phase `metadata_correction`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def fetch_for_unary_correction(self) -> list[UnaryCorrectionRow]:
        """Renvoie tous les enregistrements sources, avec les faits lus par les règles.

        Certaines règles valent quel que soit le type (URL theses.fr ou DUMAS), et un enregistrement source sans type reste candidat : aucun filtre par règle.
        """
        return self._unary_rows(_SELECT, {}, whole_table=True)

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

    def _unary_rows(
        self, query: str, params: Mapping[str, object], *, whole_table: bool = False
    ) -> list[UnaryCorrectionRow]:
        """Renvoie les lignes de correction unaire de `query`. `whole_table` : la requête lit tous les enregistrements sources, et leurs identifiants se lisent sans filtre."""
        registrant_types: dict[str, str] = dict(
            self._conn.execute(
                text("""
                    SELECT dp.prefix, p.publisher_type::text
                    FROM doi_prefixes dp JOIN publishers p ON p.id = dp.publisher_id
                    WHERE p.publisher_type IS NOT NULL
                """)
            ).all()
        )
        rows = self._conn.execute(text(query), params).all()
        identifiers = fetch_identifiers(self._conn, None if whole_table else [r.id for r in rows])
        return [_unary_row(r, identifiers.get(r.id, ()), registrant_types) for r in rows]

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
                SELECT id, is_matchable, source::text AS source, title_normalized,
                       COALESCE(urls, '{{}}') AS urls,
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
        ).all()
        identifiers = fetch_identifiers(self._conn)
        return [
            MatchabilityRow(
                r.id,
                r.is_matchable,
                MatchabilityFacts(
                    r.source,
                    r.title_normalized,
                    r.urls,
                    identifiers.get(r.id, ()),
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
        """Renvoie les enregistrements sources candidats au rattachement : sans revue avec un DOI retenu par `namespace_dois`, ou déjà rattachés par espace de noms, pour réévaluation."""
        removals = [r for r in NAMESPACE_DOI_REMOVALS if r is not None]
        rows = self._conn.execute(
            text(f"""
                SELECT sr.id, sr.source::text AS source, sr.raw_doc_type,
                       sr.serial_id, sr.corrections,
                       {identifiers_json_sql("sr.id")} AS identifiers
                FROM source_records sr
                WHERE (sr.serial_id IS NULL AND EXISTS (
                          SELECT 1 FROM source_record_identifiers i
                          WHERE i.source_record_id = sr.id
                            AND {non_related_doi_sql("i")}
                            AND (i.removed_by IS NULL OR i.removed_by = ANY(:removals))))
                   OR {corrected("serial_id")}
            """),
            {"removals": removals},
        )
        return [
            SerialCorrectionRow(
                id=r.id,
                source=r.source,
                raw_doc_type=r.raw_doc_type,
                dois=frozenset(namespace_dois(parse_identifiers(r.identifiers))),
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
                WHERE {non_related_doi_sql("source_record_identifiers")}
                  AND {unversioned_doi_sql("id_value")} IS NOT NULL
            """)
        )
        return list(rows.scalars())

    def fetch_anchor_dois(self, dois: Iterable[str]) -> frozenset[str]:
        """Renvoie les DOI de `dois` actifs en rôle fort (`STRONG_ROLES`) d'un enregistrement source : ancres de la réconciliation."""
        rows = self._conn.execute(
            text(f"""
                SELECT DISTINCT id_value FROM source_record_identifiers
                WHERE id_type = '{SourceIdentifierType.DOI.value}'
                  AND role IN {in_clause(STRONG_ROLES)}
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
                record_dois AS ({_RECORD_DOIS_SQL}),
                dataset_dois AS (
                    SELECT DISTINCT d.doi AS d
                    FROM sr_eff sr JOIN record_dois d ON d.id = sr.id
                    WHERE sr.doc_type = '{DocType.DATASET.value}'
                ),
                unresolved_dois AS ({_UNRESOLVED_DOIS_SQL}),
                -- Collections figshare typées dataset, une par titre et année : un titre partagé par deux collections n'en désigne aucune.
                figshare_collections AS (
                    SELECT sr.title_normalized, sr.publication_year, min(d.doi) AS doi
                    FROM sr_eff sr JOIN record_dois d ON d.id = sr.id
                    WHERE sr.doc_type = '{DocType.DATASET.value}'
                      AND starts_with(d.doi, '{FIGSHARE_COLLECTION_DOI_PREFIX}')
                    GROUP BY sr.title_normalized, sr.publication_year
                    HAVING count(DISTINCT d.doi) = 1
                ),
                -- DOI d'item figshare, filtrés une seule fois.
                figshare_items AS MATERIALIZED (
                    SELECT id, doi FROM record_dois WHERE doi ~ '{FIGSHARE_ITEM_DOI_PATTERN}'
                ),
                -- DOI présents en base : DOI de rôle autre que `related` des enregistrements sources, hors retraits de la correction unaire.
                present_dois AS (
                    SELECT DISTINCT id_value AS d FROM source_record_identifiers
                    WHERE {non_related_doi_sql("source_record_identifiers")}
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
                            rel->>'doi' AS canonical_doi,
                            {_DATACITE_CASE_SQL} AS same_work_case
                        FROM sr_eff sr
                        JOIN datacite_dois own ON own.id = sr.id
                        CROSS JOIN LATERAL jsonb_array_elements({source_extra_json(SourceExtra.RELATED_IDENTIFIERS)}) rel
                        WHERE rel->>'relation_type' IN {_DATACITE_DIRECT_RELATIONS_SQL}
                          AND rel->>'doi' IS NOT NULL
                          AND rel->>'doi' <> own.doi
                          AND rel->>'doi' IN (SELECT d FROM present_dois)
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
                            rel->>'doi' AS canonical_doi,
                            '{DoiTargetRule.DATACITE_PACKAGE_PIECE.value}' AS same_work_case
                        FROM sr_eff sr
                        JOIN datacite_dois own ON own.id = sr.id
                        CROSS JOIN LATERAL jsonb_array_elements({source_extra_json(SourceExtra.RELATED_IDENTIFIERS)}) rel
                        WHERE sr.doc_type = '{DocType.DATASET.value}'
                          AND rel->>'relation_type' = '{DATACITE_PACKAGE_PIECE_RELATION}'
                          AND rel->>'doi' IS NOT NULL
                          AND rel->>'doi' <> own.doi
                          AND rel->>'doi' IN (SELECT d FROM dataset_dois)
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
                        JOIN figshare_items piece ON piece.id = sr.id
                        JOIN figshare_collections c
                          ON c.title_normalized = regexp_replace(
                                 sr.title_normalized, '{FIGSHARE_ADDITIONAL_FILE_TITLE_PATTERN}', ''
                             )
                         AND c.publication_year = sr.publication_year
                        WHERE sr.title_normalized ~ '{FIGSHARE_ADDITIONAL_FILE_TITLE_PATTERN}'
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

    def fetch_crossref_title_pairs(self) -> list[CrossrefTitlePair]:
        """Renvoie les paires d'enregistrements sources de même DOI, l'un Crossref, l'autre d'une autre source, avec leurs titres normalisés."""
        return rows_as(
            CrossrefTitlePair,
            self._conn.execute(
                text(f"""
                    WITH record_dois AS ({_RECORD_DOIS_SQL})
                    SELECT od.doi, o.title_normalized,
                           c.title_normalized AS crossref_title_normalized
                    FROM source_records c
                    JOIN record_dois cd ON cd.id = c.id
                    JOIN record_dois od ON od.doi = cd.doi AND od.id <> c.id
                    JOIN source_records o ON o.id = od.id AND o.source <> '{Source.CROSSREF.value}'
                    WHERE c.source = '{Source.CROSSREF.value}'
                """)
            ),
        )

    def fetch_doi_cluster_candidates(
        self, distant_title_dois: Collection[str]
    ) -> list[DoiClusterRow]:
        """Renvoie les membres des groupes de même DOI candidats au retrait du DOI.

        Un groupe réunit les enregistrements sources ayant son DOI, de rôle autre que `related`, quel que soit son statut. Un groupe est candidat si :

        - il contient un type de `CLUSTER_CANDIDATE_DOC_TYPES` : livre, chapitre, volume d'actes, numéro de revue ;
        - son DOI est inconnu de doi.org ;
        - son DOI est dans `distant_title_dois`, avec les noms d'auteur de chaque membre ;
        - il contient un enregistrement source déjà corrigé, à réévaluer.
        """
        rows = self._conn.execute(
            text(f"""
                WITH sr_eff AS (
                    SELECT id, source, doc_type, title_normalized
                    FROM source_records
                ),
                record_dois AS ({_RECORD_DOIS_SQL}),
                unresolved_dois AS ({_UNRESOLVED_DOIS_SQL}),
                candidate_dois AS (
                    SELECT d.doi AS d FROM record_dois d JOIN sr_eff sr ON sr.id = d.id
                    WHERE sr.doc_type IN ({_CLUSTER_CANDIDATE_DOC_TYPES_SQL})
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
                    SELECT unnest(CAST(:distant_title_dois AS text[]))
                )
                SELECT sr.id, sr.doc_type, sr.title_normalized,
                       sr.source::text AS source,
                       {identifiers_json_sql("sr.id")} AS identifiers,
                       m.doi AS shared_doi,
                       m.doi IN (SELECT d FROM unresolved_dois) AS unresolved,
                       EXISTS (SELECT 1 FROM doi_targets t WHERE t.doi = m.doi) AS has_target,
                       CASE WHEN m.doi = ANY(CAST(:distant_title_dois AS text[])) THEN ARRAY(
                           SELECT DISTINCT ci.last_name_normalized
                           FROM source_contributions sc
                           JOIN contributor_information ci ON ci.id = sc.contributor_information_id
                           WHERE sc.source_record_id = sr.id AND NOT sc.collective
                             AND ci.last_name_normalized <> ''
                       ) ELSE ARRAY[]::text[] END AS author_names
                FROM candidate_dois c
                JOIN record_dois m ON m.doi = c.d
                JOIN sr_eff sr ON sr.id = m.id
            """),
            {"distant_title_dois": sorted(distant_title_dois)},
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
            WHERE {non_related_doi_sql("source_record_identifiers")} AND id_value = ANY(:dois)
            """,
            {"dois": changed},
        )
        return len(changed)

    def persist_doi_corrections(self, updates: list[DoiCorrectionUpdate]) -> int:
        """Écrit en lot les statuts des identifiants. Marque les enregistrements sources pour la réconciliation : leurs identifiants sont des clés. Renvoie le nombre de lignes."""
        _persist_statuses(self._conn, {u.id: u.identifiers for u in updates})
        return _persist_updates(self._conn, [{"id": u.id} for u in updates])
