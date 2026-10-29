"""Phase `metadata_correction` — sous-étape **cluster** (corrections de DOI par groupe).

Réécrit `doi_targets` et retire le DOI de certaines source_records. Deux familles de cas (extensibles) :

- **convergence** : le DOI d'une forme secondaire DataCite a pour cible le DOI de l'œuvre principale présente en base, dans `doi_targets`. Version → concept (`IsVersionOf`), forme variante / copie repository → version publiée (`IsVariantFormOf`), pièce d'un dataset → dataset parent (`IsPartOf`, ou collection figshare de même titre pour un fichier complémentaire figshare). La cible tient lieu du DOI pour tous les enregistrements sources qui ont ce DOI. La sous-étape matchable écarte de la réconciliation l'enregistrement source DataCite de la forme secondaire ;
- **divergence** : un DOI partagé par des œuvres distinctes (ouvrage/chapitre, chapitres de titres différents, volume d'actes/communication, dépôt HAL d'une autre œuvre) est nullé sur le ou les mauvais côtés, sinon le matching les fusionnerait.

Un DOI inconnu de doi.org (`failed_lookups`, source `doi_org`) est nullé sur tous les enregistrements sources qui le citent.

Après une divergence, les enregistrements sources qui gardent le DOI perdent les clés de confirmation qu'ils partagent avec les enregistrements sources qui le perdent, par exemple le dépôt HAL d'une communication recopié par l'enregistrement source OpenAlex du volume d'actes. Le cas de chaque identifiant retiré, DOI nullé compris, est inscrit dans `source_record_identifiers.removed_by`.

Les `doc_type` lus sont ceux que la sous-étape unaire a corrigés. Idempotent et auto-cicatrisant : on repart du **DOI brut reconstruit** (`corrections.doi`) et de tous les identifiants de la table, donc une `source_record` dont la relation/le conflit a disparu récupère son DOI et ses identifiants source au run suivant.
"""

import logging
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.source_records.corrections import (
    CLUSTER_KEYS,
    CORRECTED_BY,
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
    DoiClusterDecision,
    DoiClusterMember,
    DoiTarget,
    confirmation_id_removals,
    confirmation_ids,
    doi_target,
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

# Règles de retrait d'identifiants de la sous-étape cluster : ses cas.
CLUSTER_IDENTIFIER_RULES = frozenset(case.value for case in DoiClusterCase)


def _base_identifiers(row: DoiClusterRow) -> list[SourceIdentifier]:
    """Identifiants actifs de l'enregistrement source avant le retrait par cluster : ceux que l'étape unaire laisse actifs."""
    return active(with_removals(row.identifiers, CLUSTER_IDENTIFIER_RULES, {}))


def _compute_update(
    row: DoiClusterRow,
    decision: DoiClusterDecision | None,
    removal: ConfirmationIdRemoval | None = None,
) -> DoiCorrectionUpdate | None:
    """État cible d'une `source_record`. Avec une décision du domaine, le DOI est nullé, le brut stashé sous le cas de la décision, et retiré des identifiants sous ce cas. Sans décision, le DOI brut est restauré. `removal` retire des identifiants sous son cas. Les retraits du passage précédent sont recalculés. Retourne `None` si rien ne change (idempotence / auto-cicatrisation)."""
    raw_doi = raw_value(row.corrections, CorrectionKey.DOI, row.doi)
    corrections = other_entries(row.corrections, CLUSTER_KEYS)

    removals: dict[tuple[SourceIdentifierType, str], str] = {}
    if decision is None:
        new_doi = raw_doi
    else:
        new_doi = None
        corrections[CorrectionKey.DOI] = stash_entry(raw_doi, decision.case.value)
        if raw_doi is not None:
            removals[(SourceIdentifierType.DOI, raw_doi)] = decision.case.value

    if removal is not None:
        for id_type, values in removal.removed.items():
            for value in values:
                removals.setdefault((SourceIdentifierType(id_type), value), removal.case.value)
    identifiers = with_removals(row.identifiers, CLUSTER_IDENTIFIER_RULES, removals)

    if new_doi == row.doi and corrections == row.corrections and identifiers == row.identifiers:
        return None
    return DoiCorrectionUpdate(row.id, new_doi, corrections, identifiers)


def _groups(
    rows: list[DoiClusterRow],
) -> Iterator[tuple[str, list[DoiClusterRow], list[DoiClusterMember], bool]]:
    """Groupes par DOI brut : le DOI, ses lignes, ses membres pour le domaine, et si doi.org ignore le DOI."""
    groups: dict[str, list[DoiClusterRow]] = defaultdict(list)
    for row in rows:
        groups[row.raw_doi].append(row)
    for raw_doi, members in groups.items():
        group = [
            DoiClusterMember(
                m.id,
                m.doc_type,
                m.title_normalized,
                m.canonical_doi,
                m.same_work_case,
                confirmation_ids(_base_identifiers(m)),
                source_record_own_ids(m.source, m.source_id),
                m.source,
                frozenset(m.author_names),
            )
            for m in members
        ]
        yield raw_doi, members, group, any(m.unresolved for m in members)


def compute_doi_targets(rows: list[DoiClusterRow]) -> list[DoiTarget]:
    """Cible du DOI de chaque groupe d'une forme secondaire (`doi_target`)."""
    return [
        target
        for raw_doi, _, group, unresolved in _groups(rows)
        if (target := doi_target(group, shared_doi=raw_doi, unresolved=unresolved)) is not None
    ]


def compute_updates(rows: list[DoiClusterRow]) -> list[DoiCorrectionUpdate]:
    """Regroupe par DOI brut, demande au domaine les membres qui perdent le DOI, renvoie les mises à jour.

    Pur (hors I/O) et sans décision métier : la règle vit dans `resolve_cluster_doi_corrections` ; ici on ne fait que regrouper et persister l'état cible."""
    updates: list[DoiCorrectionUpdate] = []
    for raw_doi, members, group, unresolved in _groups(rows):
        decisions = resolve_cluster_doi_corrections(
            group, shared_doi=raw_doi, unresolved=unresolved
        )
        decision_by_id = {d.id: d for d in decisions}
        removal_by_id = {r.id: r for r in confirmation_id_removals(group, decisions)}
        for m in members:
            upd = _compute_update(m, decision_by_id.get(m.id), removal_by_id.get(m.id))
            if upd is not None:
                updates.append(upd)
    return updates


@dataclass
class ClusterCorrectionStats:
    """Bilan de la passe cluster : `source_records` examinées, DOI corrigés, et nombre de cibles ou de corrections par cas (`DoiClusterCase` : version → concept, variante → primaire, fichier → dépôt, ouvrage/chapitre, chapitres distincts, volume d'actes/communication)."""

    examined: int
    corrected: int
    case_counts: dict[str, int]


def tally_doi_corrections(updates: list[DoiCorrectionUpdate]) -> dict[str, int]:
    """Nombre de corrections de DOI par cas, à partir du `corrected_by` stashé sur `doi`."""
    case_counts: dict[str, int] = {}
    for update in updates:
        entry = update.corrections.get("doi")
        case = entry.get(CORRECTED_BY) if isinstance(entry, dict) else None
        if isinstance(case, str):
            case_counts[case] = case_counts.get(case, 0) + 1
    return case_counts


def run(
    conn: Connection, store: SourceRecordCorrectionStore, logger: logging.Logger
) -> ClusterCorrectionStats:
    """Passe cluster : relie le DOI des formes secondaires DataCite à celui de l'œuvre principale présente en base (version → concept, variante → version publiée, fichier → dépôt parent). Nulle le DOI des chapitres qui ont celui de l'ouvrage, des communications qui ont celui du volume d'actes, et le DOI inconnu de doi.org."""
    step(logger, "Corrections de DOI par confrontation de documents")
    t0 = time.perf_counter()
    rows = store.fetch_doi_cluster_candidates()
    logger.info("%s%s %s", BRANCH, quantity(len(rows), "document"), inflect(len(rows), "examiné"))

    targets = compute_doi_targets(rows)
    changed = store.replace_doi_targets(targets)
    logger.info(
        "%s%s de forme secondaire, dont %s",
        BRANCH,
        quantity(len(targets), "DOI"),
        quantity(changed, "cible modifiée", "cibles modifiées"),
    )

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
    for target in targets:
        case_counts[target.case.value] = case_counts.get(target.case.value, 0) + 1

    persist_in_batches(conn, updates, store.persist_doi_corrections)
    logger.info("%sTerminé en %.1fs", LAST_BRANCH, time.perf_counter() - t0)
    return ClusterCorrectionStats(len(rows), len(updates), case_counts)
