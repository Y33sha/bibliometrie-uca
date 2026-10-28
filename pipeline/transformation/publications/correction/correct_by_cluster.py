"""Phase `metadata_correction` — sous-étape **cluster** (corrections de DOI par groupe).

Corrige le DOI de certaines source_records afin de provoquer leur fusion en phase `publications` (versions d'un même document avec DOI distincts) ou de l'empêcher (DOI identiques sur publications différentes). Deux familles de cas (extensibles) :

- **convergence** : une forme secondaire DataCite converge sur le DOI de l'œuvre principale — version → concept (`IsVersionOf`), forme variante / copie repository → version publiée (`IsVariantFormOf`), pièce d'un dataset → dataset parent présent (`IsPartOf`, ou collection figshare de même titre pour un fichier complémentaire figshare) ;
- **divergence** : un DOI partagé par des œuvres distinctes (ouvrage/chapitre, chapitres de titres différents, volume d'actes/communication, dépôt HAL d'une autre œuvre) est nullé sur le ou les mauvais côtés, sinon le matching les fusionnerait.

Un DOI inconnu de doi.org (`failed_lookups`, source `doi_org`) est nullé sur tous les enregistrements sources qui le citent.

Après une divergence, les enregistrements sources qui gardent le DOI perdent les clés de confirmation qu'ils partagent avec les enregistrements sources qui le perdent, par exemple le dépôt HAL d'une communication recopié par l'enregistrement source OpenAlex du volume d'actes. Les valeurs retirées sont notées sous `corrections.removed_external_ids`, que la sous-étape unaire réapplique.

Les `doc_type` lus sont ceux que la sous-étape unaire a corrigés. Idempotent et auto-cicatrisant : on repart du **DOI brut reconstruit** (`corrections.doi`) et des identifiants d'avant retrait, donc une `source_record` dont la relation/le conflit a disparu récupère son DOI et ses identifiants source au run suivant.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.source_records.corrections import (
    CLUSTER_KEYS,
    CORRECTED_BY,
    CorrectionKey,
    other_entries,
    raw_value,
    removal_entry,
    stash_entry,
    with_values_restored,
    without_values,
)
from domain.source_records.metadata_correction.shared_doi import (
    ConfirmationIdRemoval,
    DoiClusterDecision,
    DoiClusterMember,
    confirmation_id_removals,
    confirmation_ids,
    resolve_cluster_doi_corrections,
    source_record_own_ids,
)
from domain.types import JsonValue
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.correction_store import (
    DoiClusterRow,
    DoiCorrectionUpdate,
    SourceRecordCorrectionStore,
)


def _base_external_ids(row: DoiClusterRow) -> dict[str, JsonValue]:
    """Identifiants externes de l'enregistrement source avant le retrait par cluster : ceux que l'étape unaire a écrits, valeurs retirées au run précédent restaurées."""
    return with_values_restored(
        row.external_ids, row.corrections.get(CorrectionKey.REMOVED_EXTERNAL_IDS)
    )


def _compute_update(
    row: DoiClusterRow,
    decision: DoiClusterDecision | None,
    removal: ConfirmationIdRemoval | None = None,
) -> DoiCorrectionUpdate | None:
    """État cible d'une `source_record` : selon la décision du domaine, DOI nullé (`target_doi=None`) ou substitué (concept), le brut stashé sous la provenance du cas ; sans décision, ou si la cible égale le brut (dépôt non versionné), le DOI brut est restauré. `removal` retire des identifiants externes, notés sous `CorrectionKey.REMOVED_EXTERNAL_IDS` ; sans retrait, les valeurs retirées au run précédent sont restaurées. Retourne `None` si rien ne change (idempotence / auto-cicatrisation). La *décision* vient du domaine."""
    raw_doi = raw_value(row.corrections, CorrectionKey.DOI, row.doi)
    corrections = other_entries(row.corrections, CLUSTER_KEYS)

    if decision is None or decision.target_doi == raw_doi:
        new_doi = raw_doi
    else:
        new_doi = decision.target_doi
        corrections[CorrectionKey.DOI] = stash_entry(raw_doi, decision.case.value)

    base = _base_external_ids(row)
    new_external_ids = base
    if removal is not None:
        entry = removal_entry(
            {k: base[k] for k in removal.removed if k in base}, removal.removed, removal.case.value
        )
        new_external_ids = without_values(base, entry)
        corrections[CorrectionKey.REMOVED_EXTERNAL_IDS] = entry

    if (
        new_doi == row.doi
        and new_external_ids == row.external_ids
        and corrections == row.corrections
    ):
        return None
    return DoiCorrectionUpdate(row.id, new_doi, corrections, new_external_ids)


def compute_updates(rows: list[DoiClusterRow]) -> list[DoiCorrectionUpdate]:
    """Regroupe par DOI brut, demande au domaine le DOI cible de chaque membre, renvoie les mises à jour.

    Pur (hors I/O) et sans décision métier : la règle vit dans `resolve_cluster_doi_corrections` ; ici on ne fait que regrouper et persister l'état cible."""
    groups: dict[str, list[DoiClusterRow]] = defaultdict(list)
    for row in rows:
        groups[row.raw_doi].append(row)

    updates: list[DoiCorrectionUpdate] = []
    for raw_doi, members in groups.items():
        group = [
            DoiClusterMember(
                m.id,
                m.doc_type,
                m.title_normalized,
                m.canonical_doi,
                m.same_work_case,
                confirmation_ids(_base_external_ids(m)),
                source_record_own_ids(m.source, m.source_id),
                m.source,
                frozenset(m.author_names),
            )
            for m in members
        ]
        decisions = resolve_cluster_doi_corrections(
            group, shared_doi=raw_doi, unresolved=any(m.unresolved for m in members)
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
    """Bilan de la passe cluster : `source_records` examinées, DOI corrigés, et nombre de corrections par cas (`DoiClusterCase` : version → concept, variante → primaire, fichier → dépôt, ouvrage/chapitre, chapitres distincts, volume d'actes/communication)."""

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
    """Passe cluster : fait converger les formes secondaires DataCite sur l'œuvre principale (version → concept, variante → version publiée, fichier → dépôt parent). Nulle le DOI des chapitres qui ont celui de l'ouvrage, des communications qui ont celui du volume d'actes, et le DOI inconnu de doi.org."""
    step(logger, "Corrections de DOI par confrontation de documents")
    t0 = time.perf_counter()
    rows = store.fetch_doi_cluster_candidates()
    logger.info("%s%s %s", BRANCH, quantity(len(rows), "document"), inflect(len(rows), "examiné"))

    updates = compute_updates(rows)
    logger.info("%s%s à appliquer", BRANCH, quantity(len(updates), "correction"))
    removals = sum(1 for u in updates if CorrectionKey.REMOVED_EXTERNAL_IDS in u.corrections)
    logger.info(
        "%sidentifiants partagés avec une autre œuvre retirés de %s",
        BRANCH,
        quantity(removals, "enregistrement source", "enregistrements sources"),
    )
    case_counts = tally_doi_corrections(updates)

    persist_in_batches(conn, updates, store.persist_doi_corrections)
    logger.info("%sTerminé en %.1fs", LAST_BRANCH, time.perf_counter() - t0)
    return ClusterCorrectionStats(len(rows), len(updates), case_counts)
