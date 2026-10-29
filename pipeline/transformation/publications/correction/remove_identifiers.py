"""Sous-étape `remove_identifiers` de la phase `metadata_correction` : retrait d'identifiants par groupe d'enregistrements sources de même DOI. Un groupe réunit les enregistrements sources qui ont son DOI dans `source_record_identifiers`, de rôle autre que `related` ; un enregistrement source appartient à un groupe par DOI.

Un DOI que partagent des œuvres distinctes (ouvrage et chapitre, chapitres de titres différents, volume d'actes et communication, dépôt HAL d'une autre œuvre) est retiré du ou des mauvais côtés : la réconciliation fusionnerait sinon ces œuvres. Un DOI qui a une cible dans `doi_targets` est celui d'une forme secondaire : aucun membre de son groupe ne le perd. Un DOI inconnu de doi.org est retiré de tous les enregistrements sources qui le citent.

Après une divergence, les enregistrements sources qui gardent le DOI perdent les clés de confirmation qu'ils partagent avec ceux qui le perdent : par exemple le dépôt HAL d'une communication, recopié par l'enregistrement source OpenAlex du volume d'actes. Le cas de chaque identifiant retiré, DOI compris, est inscrit dans `source_record_identifiers.removed_by`.

Les types lus sont ceux que la sous-étape unaire a corrigés. Chaque passage repart du DOI d'avant correction (`corrections.doi`) et de tous les identifiants : un enregistrement source dont le conflit disparaît retrouve son DOI et ses identifiants au run suivant.
"""

import logging
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.source_records.corrections import (
    CLUSTER_KEYS,
    CorrectionKey,
    other_entries,
    raw_value,
    stash_entry,
)
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierType,
    active,
    with_removals,
)
from domain.source_records.metadata_correction.shared_doi import (
    ConfirmationIdRemoval,
    DoiClusterCase,
    DoiClusterMember,
    confirmation_id_removals,
    confirmation_ids,
    resolve_cluster_doi_corrections,
    source_record_own_ids,
)
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.correction_store import (
    DoiClusterRow,
    DoiCorrectionUpdate,
    SourceRecordCorrectionStore,
)

# Règles de retrait d'identifiants de la sous-étape : ses cas.
CLUSTER_IDENTIFIER_RULES = frozenset(case.value for case in DoiClusterCase)


def _base_identifiers(row: DoiClusterRow) -> list[SourceIdentifier]:
    """Identifiants actifs de l'enregistrement source avant cette sous-étape : ceux que l'étape unaire laisse actifs."""
    return active(with_removals(row.identifiers, CLUSTER_IDENTIFIER_RULES, {}))


def _compute_update(
    row: DoiClusterRow,
    removed_dois: Mapping[str, str],
    confirmation_removals: Iterable[ConfirmationIdRemoval] = (),
) -> DoiCorrectionUpdate | None:
    """État cible d'un enregistrement source, ou `None` si rien ne change.

    `removed_dois` : cas de retrait de chaque DOI que l'enregistrement source perd, par DOI. Chacun est retiré des identifiants sous son cas. La colonne `doi` passe à NULL quand son DOI d'origine est retiré, et sa valeur d'origine est gardée sous le cas ; sinon le DOI d'origine revient. Un retrait de clés de confirmation retire des identifiants sous son cas. Les retraits du passage précédent sont recalculés.
    """
    raw_doi = raw_value(row.corrections, CorrectionKey.DOI, row.doi)
    corrections = other_entries(row.corrections, CLUSTER_KEYS)

    removals: dict[tuple[SourceIdentifierType, str], str] = {
        (SourceIdentifierType.DOI, doi): case for doi, case in removed_dois.items()
    }
    column_case = removed_dois.get(raw_doi.lower()) if raw_doi else None
    if column_case is None:
        new_doi = raw_doi
    else:
        new_doi = None
        corrections[CorrectionKey.DOI] = stash_entry(raw_doi, column_case)

    for removal in confirmation_removals:
        for id_type, values in removal.removed.items():
            for value in values:
                removals.setdefault((SourceIdentifierType(id_type), value), removal.case.value)
    identifiers = with_removals(row.identifiers, CLUSTER_IDENTIFIER_RULES, removals)

    if new_doi == row.doi and corrections == row.corrections and identifiers == row.identifiers:
        return None
    return DoiCorrectionUpdate(row.id, new_doi, corrections, identifiers)


def compute_updates(rows: list[DoiClusterRow]) -> list[DoiCorrectionUpdate]:
    """Mises à jour des enregistrements sources des groupes de même DOI. Un enregistrement source appartient à un groupe par DOI ; ses retraits se cumulent. La règle de retrait vit dans `resolve_cluster_doi_corrections`."""
    groups: dict[str, list[DoiClusterRow]] = defaultdict(list)
    for row in rows:
        groups[row.shared_doi].append(row)

    records: dict[int, DoiClusterRow] = {}
    removed_dois: dict[int, dict[str, str]] = defaultdict(dict)
    confirmation_removals: dict[int, list[ConfirmationIdRemoval]] = defaultdict(list)
    for shared_doi, members in groups.items():
        group = [
            DoiClusterMember(
                m.id,
                m.doc_type,
                m.title_normalized,
                confirmation_ids(_base_identifiers(m)),
                source_record_own_ids(m.source, m.source_id),
                m.source,
                frozenset(m.author_names),
            )
            for m in members
        ]
        decisions = resolve_cluster_doi_corrections(
            group,
            shared_doi=shared_doi,
            unresolved=any(m.unresolved for m in members),
            has_target=any(m.has_target for m in members),
        )
        for decision in decisions:
            removed_dois[decision.id][shared_doi] = decision.case.value
        for removal in confirmation_id_removals(group, decisions):
            confirmation_removals[removal.id].append(removal)
        records.update((m.id, m) for m in members)

    return [
        update
        for record_id, row in records.items()
        if (
            update := _compute_update(
                row, removed_dois.get(record_id, {}), confirmation_removals.get(record_id, ())
            )
        )
        is not None
    ]


@dataclass
class IdentifierRemovalStats:
    """Bilan de la sous-étape : enregistrements sources examinés, DOI corrigés, corrections par cas (`DoiClusterCase`)."""

    examined: int
    corrected: int
    case_counts: dict[str, int]


def tally_doi_corrections(updates: list[DoiCorrectionUpdate]) -> dict[str, int]:
    """DOI retirés par cas, dans les identifiants des enregistrements sources mis à jour."""
    case_counts: dict[str, int] = {}
    for update in updates:
        for i in update.identifiers:
            if i.id_type is SourceIdentifierType.DOI and i.removed_by in CLUSTER_IDENTIFIER_RULES:
                case_counts[i.removed_by] = case_counts.get(i.removed_by, 0) + 1
    return case_counts


def run(
    conn: Connection, store: SourceRecordCorrectionStore, logger: logging.Logger
) -> IdentifierRemovalStats:
    """Retire le DOI des chapitres qui ont celui de l'ouvrage, des communications qui ont celui du volume d'actes, des dépôts HAL qui ont celui d'une autre œuvre, et le DOI inconnu de doi.org."""
    step(logger, "Retraits de DOI par confrontation de documents")
    t0 = time.perf_counter()
    rows = store.fetch_doi_cluster_candidates()
    examined = len({row.id for row in rows})
    logger.info("%s%s %s", BRANCH, quantity(examined, "document"), inflect(examined, "examiné"))

    updates = compute_updates(rows)
    logger.info("%s%s à appliquer", BRANCH, quantity(len(updates), "correction"))
    removals = sum(
        1
        for u in updates
        if any(
            i.removed_by in CLUSTER_IDENTIFIER_RULES and i.id_type is not SourceIdentifierType.DOI
            for i in u.identifiers
        )
    )
    logger.info(
        "%sidentifiants partagés avec une autre œuvre retirés de %s",
        BRANCH,
        quantity(removals, "enregistrement source", "enregistrements sources"),
    )
    case_counts = tally_doi_corrections(updates)

    persist_in_batches(conn, updates, store.persist_doi_corrections)
    logger.info("%sTerminé en %.1fs", LAST_BRANCH, time.perf_counter() - t0)
    return IdentifierRemovalStats(examined, len(updates), case_counts)
