"""Tâche `remove_identifiers` de la phase `metadata_correction` : retrait d'identifiants par groupe d'enregistrements sources de même DOI. Un groupe réunit les enregistrements sources ayant son DOI dans `source_record_identifiers`, de rôle autre que `related`. Un enregistrement source appartient à un groupe par DOI.

Un DOI partagé par des œuvres distinctes (ouvrage et chapitre, chapitres de titres différents, volume d'actes et communication, numéro de revue et article, avis et article, enregistrement source d'une autre œuvre) est retiré du ou des mauvais côtés. Sinon, la réconciliation fusionnerait ces œuvres. Un enregistrement source qui détient le DOI en `primary` ou `derived` le garde. Un DOI à cible dans `doi_targets` est celui d'une forme secondaire : aucun membre de son groupe ne le perd. Un DOI inconnu de doi.org est retiré de tous les enregistrements sources qui le citent.

Un document qui porte le DOI d'un erratum ou d'un avis Crossref le perd, et reçoit le DOI de l'œuvre corrigée déclaré par l'avis. La règle de l'ajout est inscrite dans `source_record_identifiers.added_by`.

Quand une partie du groupe perd le DOI, les enregistrements sources qui le gardent perdent les clés de confirmation partagées avec ceux qui le perdent. Exemple : le dépôt HAL d'une communication, recopié par l'enregistrement source OpenAlex du volume d'actes. Le cas de chaque identifiant retiré, DOI compris, est inscrit dans `source_record_identifiers.removed_by`.

Les types lus sont ceux corrigés par la tâche unaire. Chaque passage repart de tous les identifiants : un enregistrement source à conflit disparu retrouve ses identifiants au run suivant.
"""

import logging
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping

from sqlalchemy import Connection

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
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
from domain.source_records.notices import corrected_work_doi
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.correction_store import (
    DoiClusterRow,
    DoiCorrectionUpdate,
    SourceRecordCorrectionStore,
)

CLUSTER_IDENTIFIER_RULES = frozenset(case.value for case in DoiClusterCase)
"""Règles de retrait d'identifiants de la tâche : les cas de `DoiClusterCase`."""


def _source_identifiers(row: DoiClusterRow) -> tuple[SourceIdentifier, ...]:
    """Renvoie les identifiants de l'enregistrement source, hors ceux ajoutés par cette tâche."""
    return tuple(i for i in row.identifiers if i.added_by not in CLUSTER_IDENTIFIER_RULES)


def _base_identifiers(row: DoiClusterRow) -> list[SourceIdentifier]:
    """Renvoie les identifiants de l'enregistrement source laissés actifs par l'étape unaire, avant cette tâche."""
    return active(with_removals(_source_identifiers(row), CLUSTER_IDENTIFIER_RULES, {}))


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
    added_dois: Mapping[str, SourceIdentifierRole] = {},  # noqa: B006 — lu, jamais modifié
) -> DoiCorrectionUpdate | None:
    """Renvoie les identifiants d'un enregistrement source aux statuts recalculés, avec ses DOI ajoutés, ou `None` si rien ne change. Les retraits et les ajouts sont recalculés à chaque passage.

    Args:
        removed_dois: cas de retrait de chaque DOI perdu par l'enregistrement source.
        confirmation_removals: retraits de clés de confirmation, chacun sous son cas.
        added_dois: DOI ajoutés (`AVIS_VS_ARTICLE`), avec le rôle du DOI d'avis retiré. Un DOI donné par la source reste tel quel.
    """
    removals: dict[tuple[SourceIdentifierType, str], str] = {
        (SourceIdentifierType.DOI, doi): case for doi, case in removed_dois.items()
    }
    for removal in confirmation_removals:
        for id_type, values in removal.removed.items():
            for value in values:
                removals.setdefault((id_type, value), removal.case.value)
    identifiers = with_removals(_source_identifiers(row), CLUSTER_IDENTIFIER_RULES, removals)
    present = {i.key for i in identifiers}
    identifiers += tuple(
        SourceIdentifier(
            SourceIdentifierType.DOI, doi, role, added_by=DoiClusterCase.AVIS_VS_ARTICLE.value
        )
        for doi, role in sorted(added_dois.items())
        if (SourceIdentifierType.DOI, doi) not in present
    )

    if set(identifiers) == set(row.identifiers):
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


def compute_updates(
    rows: list[DoiClusterRow],
    corrected_works: Mapping[str, str] = {},  # noqa: B006 — lu, jamais modifié
) -> list[DoiCorrectionUpdate]:
    """Calcule les mises à jour des enregistrements sources des groupes de même DOI. Les retraits d'un enregistrement source membre de plusieurs groupes se cumulent. La règle de retrait est définie dans `resolve_cluster_doi_corrections`.

    Un document qui perd le DOI d'un avis (`AVIS_VS_ARTICLE`) reçoit le DOI de l'œuvre corrigée, déclaré par l'avis : il rejoint ainsi la publication de cette œuvre.

    Args:
        corrected_works: DOI de l'œuvre corrigée, par DOI d'avis Crossref (`corrected_work_doi`).
    """
    groups: dict[str, list[DoiClusterRow]] = defaultdict(list)
    for row in rows:
        groups[row.shared_doi].append(row)

    records: dict[int, DoiClusterRow] = {}
    removed_dois: dict[int, dict[str, str]] = defaultdict(dict)
    added_dois: dict[int, dict[str, SourceIdentifierRole]] = defaultdict(dict)
    confirmation_removals: dict[int, list[ConfirmationIdRemoval]] = defaultdict(list)
    for shared_doi, members in groups.items():
        group = [_member(m, shared_doi) for m in members]
        decisions = resolve_cluster_doi_corrections(
            group,
            unresolved=any(m.unresolved for m in members),
            has_target=any(m.has_target for m in members),
        )
        by_id = {m.id: m for m in members}
        for decision in decisions:
            removed_dois[decision.id][shared_doi] = decision.case.value
            work = corrected_works.get(shared_doi)
            if decision.case is DoiClusterCase.AVIS_VS_ARTICLE and work is not None:
                added_dois[decision.id][work] = _role_of(by_id[decision.id], shared_doi)
        for removal in confirmation_id_removals(group, decisions):
            confirmation_removals[removal.id].append(removal)
        records.update((m.id, m) for m in members)

    return [
        update
        for record_id, row in records.items()
        if (
            update := _compute_update(
                row,
                removed_dois.get(record_id, {}),
                confirmation_removals.get(record_id, ()),
                added_dois.get(record_id, {}),
            )
        )
        is not None
    ]


def _role_of(row: DoiClusterRow, doi: str) -> SourceIdentifierRole:
    """Renvoie le rôle du DOI `doi` dans les identifiants de l'enregistrement source."""
    return next(
        i.role
        for i in _source_identifiers(row)
        if i.id_type is SourceIdentifierType.DOI and i.value == doi
    )


def fetch_corrected_works(
    store: SourceRecordCorrectionStore, rows: list[DoiClusterRow]
) -> dict[str, str]:
    """Renvoie le DOI de l'œuvre corrigée de chaque DOI de groupe qui est celui d'un avis Crossref."""
    extras = store.fetch_crossref_notice_extras(sorted({row.shared_doi for row in rows}))
    return {
        doi: work
        for doi, source_extras in extras.items()
        if (work := corrected_work_doi(source_extras, doi))
    }


def tally_doi_corrections(updates: list[DoiCorrectionUpdate]) -> dict[str, int]:
    """Compte les DOI retirés par cas, dans les identifiants des enregistrements sources mis à jour."""
    return Counter(
        i.removed_by
        for update in updates
        for i in update.identifiers
        if i.id_type is SourceIdentifierType.DOI and i.removed_by in CLUSTER_IDENTIFIER_RULES
    )


def run(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Retire le DOI des chapitres qui ont celui de l'ouvrage, des communications qui ont celui du volume d'actes, des articles qui ont celui du numéro de revue, des enregistrements sources qui ont celui d'une autre œuvre, et le DOI inconnu de doi.org.

    Renvoie les enregistrements sources examinés, mis à jour, et les DOI retirés par cas.
    """
    store = SourceRecordCorrectionStore(conn)
    t0 = time.perf_counter()
    rows = fetch_candidates(store)
    examined = len({row.id for row in rows})
    logger.info("%s%s %s", BRANCH, quantity(examined, "document"), inflect(examined, "examiné"))

    updates = compute_updates(rows, fetch_corrected_works(store, rows))
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

    written = persist_in_batches(conn, updates, store.persist_doi_corrections)
    logger.info("%sTerminé en %.1fs", LAST_BRANCH, time.perf_counter() - t0)
    return PhaseMetrics(seen=examined, updated=written, extras=tally_doi_corrections(updates))
