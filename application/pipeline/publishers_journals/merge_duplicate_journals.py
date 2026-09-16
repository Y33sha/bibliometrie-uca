"""Sous-étape de la phase `publishers_journals` — fusionne les revues en double.

Deux revues vérifiées dans le Sudoc qui partagent leur ISSN-L décrivent la même publication. De même quand elles portent le même ISSN dans une colonne et que les mots d'un titre sont tous dans l'autre, « BMJ » et « BMJ-BRITISH MEDICAL JOURNAL » par exemple. L'éditeur ne sert pas de contrôle : deux fiches d'éditeur désignent souvent la même maison.

Dans un groupe, la revue qui porte le plus de publications absorbe les autres ; à égalité, celle dont l'identifiant est le plus petit. La fusion elle-même est celle de l'administration des revues, injectée par le composition-root : publications et métadonnées passent à la cible, qui requalifie les publications absorbées, puis la source est supprimée.
"""

import logging
from collections.abc import Callable

from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import progression
from application.ports.pipeline.journals import JournalMergeQueries, JournalTitleRow
from domain.journals.titles import nested_titles

MergeJournals = Callable[[int, int], None]
"""`(cible, source)` : fusionne la revue source dans la cible et valide la transaction."""


def run_merge_duplicate_journals(
    logger: logging.Logger,
    *,
    journal_repo: JournalMergeQueries,
    merge: MergeJournals,
) -> PhaseMetrics:
    """Fusionne les revues de même ISSN-L, puis celles qui partagent un ISSN de colonne sous un titre emboîté."""
    metrics = PhaseMetrics()
    # Revue absorbée → revue qui l'a absorbée. Une revue qui partage ses deux ISSN avec son double figure dans deux groupes.
    absorbed: dict[int, int] = {}
    issnl_groups = journal_repo.find_journals_sharing_issnl()
    if issnl_groups:
        _merge_groups(
            logger,
            metrics,
            merge,
            absorbed,
            [(g.issnl, g.journal_ids) for g in issnl_groups],
            "%s : fusion des revues de même ISSN-L",
        )
    # Lecture après les fusions précédentes : elles ont retiré des revues.
    shared = [
        (group.issn, tuple(j.id for j in group.journals if _same_journal(group.journals[0], j)))
        for group in journal_repo.find_journals_sharing_column_issn()
    ]
    shared = [(issn, ids) for issn, ids in shared if len(ids) > 1]
    if shared:
        _merge_groups(
            logger,
            metrics,
            merge,
            absorbed,
            shared,
            "%s : fusion des revues de même ISSN et de titre emboîté",
        )
    if metrics.total:
        logger.info(
            "%sTerminé : %s",
            DERNIERE_BRANCHE,
            accord(
                metrics.extras.get("journals_merged", 0), "revue fusionnée", "revues fusionnées"
            ),
        )
    return metrics


def _same_journal(target: JournalTitleRow, other: JournalTitleRow) -> bool:
    """La cible et la revue candidate portent le même titre, aux mots près."""
    return other.id == target.id or nested_titles(target.title, other.title)


def _merge_groups(
    logger: logging.Logger,
    metrics: PhaseMetrics,
    merge: MergeJournals,
    absorbed: dict[int, int],
    groups: list[tuple[str, tuple[int, ...]]],
    titre: str,
) -> None:
    """Fusionne chaque groupe dans sa première revue. Une revue déjà absorbée par un groupe précédent est passée ; une cible déjà absorbée cède la place à celle qui l'a absorbée."""
    etape(logger, titre, accord(len(groups), "groupe de revues", "groupes de revues"))
    metrics.add(total=len(groups))
    with progression(len(groups), BRANCHE.rstrip(), logger) as avancement:
        for issn, journal_ids in groups:
            target = _survivor(journal_ids[0], absorbed)
            for source in journal_ids[1:]:
                if source in absorbed or source == target:
                    continue
                merge(target, source)
                absorbed[source] = target
                metrics.add(journals_merged=1)
                # Ligne de détail : le terminal la masque, le journal la garde.
                logger.info(
                    "ISSN %s : la revue %d absorbe la revue %d",
                    issn,
                    target,
                    source,
                    extra={"detail": True},
                )
            avancement.avance()


def _survivor(journal_id: int, absorbed: dict[int, int]) -> int:
    """Revue qui subsiste de `journal_id` après les fusions déjà faites."""
    while journal_id in absorbed:
        journal_id = absorbed[journal_id]
    return journal_id
