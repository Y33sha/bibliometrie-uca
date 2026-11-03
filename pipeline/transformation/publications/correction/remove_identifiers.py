"""Sous-étape `remove_identifiers` de la phase `metadata_correction` : retrait d'identifiants par groupe d'enregistrements sources de même DOI. Un groupe réunit les enregistrements sources ayant son DOI dans `source_record_identifiers`, de rôle autre que `related`. Un enregistrement source appartient à un groupe par DOI.

Un DOI partagé par des œuvres distinctes (ouvrage et chapitre, chapitres de titres différents, volume d'actes et communication, numéro de revue et article, enregistrement source d'une autre œuvre) est retiré du ou des mauvais côtés. Sinon, la réconciliation fusionnerait ces œuvres. Un enregistrement source qui détient le DOI en `primary` ou `derived` le garde. Un DOI à cible dans `doi_targets` est celui d'une forme secondaire : aucun membre de son groupe ne le perd. Un DOI inconnu de doi.org est retiré de tous les enregistrements sources qui le citent.

Quand une partie du groupe perd le DOI, les enregistrements sources qui le gardent perdent les clés de confirmation partagées avec ceux qui le perdent. Exemple : le dépôt HAL d'une communication, recopié par l'enregistrement source OpenAlex du volume d'actes. Le cas de chaque identifiant retiré, DOI compris, est inscrit dans `source_record_identifiers.removed_by`.

Les types lus sont ceux corrigés par la sous-étape unaire. Chaque passage repart de tous les identifiants : un enregistrement source à conflit disparu retrouve ses identifiants au run suivant.
"""

import logging
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import Connection

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
    distant_titles,
    own_ids,
    resolve_cluster_doi_corrections,
)
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.correction_store import (
    DoiClusterRow,
    DoiCorrectionUpdate,
    SourceRecordCorrectionStore,
)

CLUSTER_IDENTIFIER_RULES = frozenset(case.value for case in DoiClusterCase)
"""Règles de retrait d'identifiants de la sous-étape : les cas de `DoiClusterCase`."""


def _base_identifiers(row: DoiClusterRow) -> list[SourceIdentifier]:
    """Renvoie les identifiants de l'enregistrement source laissés actifs par l'étape unaire, avant cette sous-étape."""
    return active(with_removals(row.identifiers, CLUSTER_IDENTIFIER_RULES, {}))


def _member(row: DoiClusterRow, shared_doi: str) -> DoiClusterMember:
    """Renvoie le membre du groupe de `shared_doi`, d'après ses identifiants laissés actifs par l'étape unaire."""
    identifiers = _base_identifiers(row)
    owned = own_ids(identifiers)
    return DoiClusterMember(
        row.id,
        row.doc_type,
        row.title_normalized,
        confirmation_ids=confirmation_ids(identifiers),
        own_ids=owned,
        source=row.source,
        author_names=frozenset(row.author_names),
        owns_doi=shared_doi in owned.get(SourceIdentifierType.DOI, ()),
    )


def _compute_update(
    row: DoiClusterRow,
    removed_dois: Mapping[str, str],
    confirmation_removals: Iterable[ConfirmationIdRemoval] = (),
) -> DoiCorrectionUpdate | None:
    """Renvoie les identifiants d'un enregistrement source aux statuts recalculés, ou `None` si rien ne change. Les retraits du passage précédent sont recalculés.

    Args:
        removed_dois: cas de retrait de chaque DOI perdu par l'enregistrement source.
        confirmation_removals: retraits de clés de confirmation, chacun sous son cas.
    """
    removals: dict[tuple[SourceIdentifierType, str], str] = {
        (SourceIdentifierType.DOI, doi): case for doi, case in removed_dois.items()
    }
    for removal in confirmation_removals:
        for id_type, values in removal.removed.items():
            for value in values:
                removals.setdefault((id_type, value), removal.case.value)
    identifiers = with_removals(row.identifiers, CLUSTER_IDENTIFIER_RULES, removals)

    if identifiers == row.identifiers:
        return None
    return DoiCorrectionUpdate(row.id, identifiers)


def fetch_candidates(store: SourceRecordCorrectionStore) -> list[DoiClusterRow]:
    """Renvoie les membres des groupes candidats au retrait du DOI. Un groupe où un enregistrement source a un titre éloigné de celui de l'enregistrement source Crossref est candidat : seuls ces groupes reçoivent les noms d'auteur, plus coûteux à lire."""
    distant = {
        pair.doi
        for pair in store.fetch_crossref_title_pairs()
        if distant_titles(pair.title_normalized, pair.crossref_title_normalized)
    }
    return store.fetch_doi_cluster_candidates(distant)


def compute_updates(rows: list[DoiClusterRow]) -> list[DoiCorrectionUpdate]:
    """Calcule les mises à jour des enregistrements sources des groupes de même DOI. Les retraits d'un enregistrement source membre de plusieurs groupes se cumulent. La règle de retrait est définie dans `resolve_cluster_doi_corrections`."""
    groups: dict[str, list[DoiClusterRow]] = defaultdict(list)
    for row in rows:
        groups[row.shared_doi].append(row)

    records: dict[int, DoiClusterRow] = {}
    removed_dois: dict[int, dict[str, str]] = defaultdict(dict)
    confirmation_removals: dict[int, list[ConfirmationIdRemoval]] = defaultdict(list)
    for shared_doi, members in groups.items():
        group = [_member(m, shared_doi) for m in members]
        decisions = resolve_cluster_doi_corrections(
            group,
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
    """Bilan de la sous-étape."""

    examined: int
    """Enregistrements sources examinés."""
    corrected: int
    """Enregistrements sources mis à jour."""
    case_counts: dict[str, int]
    """DOI retirés par cas (`DoiClusterCase`)."""


def tally_doi_corrections(updates: list[DoiCorrectionUpdate]) -> dict[str, int]:
    """Compte les DOI retirés par cas, dans les identifiants des enregistrements sources mis à jour."""
    case_counts: dict[str, int] = {}
    for update in updates:
        for i in update.identifiers:
            if i.id_type is SourceIdentifierType.DOI and i.removed_by in CLUSTER_IDENTIFIER_RULES:
                case_counts[i.removed_by] = case_counts.get(i.removed_by, 0) + 1
    return case_counts


def run(
    conn: Connection, store: SourceRecordCorrectionStore, logger: logging.Logger
) -> IdentifierRemovalStats:
    """Retire le DOI des chapitres qui ont celui de l'ouvrage, des communications qui ont celui du volume d'actes, des articles qui ont celui du numéro de revue, des enregistrements sources qui ont celui d'une autre œuvre, et le DOI inconnu de doi.org."""
    step(logger, "Retraits de DOI par confrontation de documents")
    t0 = time.perf_counter()
    rows = fetch_candidates(store)
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
