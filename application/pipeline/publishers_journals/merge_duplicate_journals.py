"""Sous-étape de la phase `publishers_journals` — fusionne les revues en double.

Trois règles désignent la même publication :

1. deux revues vérifiées dans le Sudoc partagent leur ISSN-L ;
2. elles portent le même ISSN dans une colonne, et les mots d'un titre sont tous dans l'autre (« BMJ » et « BMJ-BRITISH MEDICAL JOURNAL ») ;
3. elles sont seules à porter leur titre normalisé, au moins une est sans ISSN, et leurs enregistrements partagent un préfixe DOI.

L'éditeur ne sert pas de contrôle : deux fiches d'éditeur désignent souvent la même maison. La fusion elle-même est celle de l'administration des revues, injectée par le composition-root : publications et métadonnées passent à la cible, qui requalifie les publications absorbées, puis la source est supprimée. Le journal garde le titre, l'éditeur et les ISSN des deux revues.
"""

import logging
from collections.abc import Callable, Sequence

from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import progression
from application.pipeline.publishers_journals._journal_label import journal_label
from application.ports.pipeline.journals import JournalMergeQueries, JournalTitleRow
from domain.journals.titles import nested_titles

MergeJournals = Callable[[int, int], None]
"""`(cible, source)` : fusionne la revue source dans la cible et valide la transaction."""

MergeGroup = tuple[str, tuple[int, ...]]
"""`(libellé, revues)` : ce que les revues partagent, puis les revues, la cible en tête."""


def run_merge_duplicate_journals(
    logger: logging.Logger,
    *,
    journal_repo: JournalMergeQueries,
    merge: MergeJournals,
) -> PhaseMetrics:
    """Applique les trois règles dans l'ordre. Chaque règle lit ses groupes après les fusions des précédentes."""
    metrics = PhaseMetrics()
    # Revue absorbée → revue qui l'a absorbée. Une revue qui partage ses deux ISSN avec son double figure dans deux groupes.
    absorbed: dict[int, int] = {}

    def merge_groups(groups: Sequence[MergeGroup], titre: str) -> None:
        _merge_groups(logger, metrics, journal_repo, merge, absorbed, groups, titre)

    merge_groups(
        [(f"ISSN-L {g.key}", g.journal_ids) for g in journal_repo.find_journals_sharing_issnl()],
        "%s : fusion des revues de même ISSN-L",
    )
    shared = [
        (f"ISSN {g.issn}", tuple(j.id for j in g.journals if _nested(g.journals[0], j)))
        for g in journal_repo.find_journals_sharing_column_issn()
    ]
    merge_groups(
        [(label, ids) for label, ids in shared if len(ids) > 1],
        "%s : fusion des revues de même ISSN et de titre emboîté",
    )
    merge_groups(
        [(f"titre {g.key!r}", g.journal_ids) for g in journal_repo.find_same_title_duplicates()],
        "%s : fusion des revues de même titre et de même préfixe DOI",
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


def _nested(target: JournalTitleRow, other: JournalTitleRow) -> bool:
    """La cible et la revue candidate portent le même titre, aux mots près."""
    return other.id == target.id or nested_titles(target.title, other.title)


def _merge_groups(
    logger: logging.Logger,
    metrics: PhaseMetrics,
    journal_repo: JournalMergeQueries,
    merge: MergeJournals,
    absorbed: dict[int, int],
    groups: Sequence[MergeGroup],
    titre: str,
) -> None:
    """Fusionne chaque groupe dans sa première revue. Une revue déjà absorbée est passée ; une cible déjà absorbée cède la place à celle qui l'a absorbée."""
    if not groups:
        return
    etape(logger, titre, accord(len(groups), "groupe de revues", "groupes de revues"))
    metrics.add(total=len(groups))
    with progression(len(groups), BRANCHE.rstrip(), logger) as avancement:
        for label, journal_ids in groups:
            target = _survivor(journal_ids[0], absorbed)
            sources = [s for s in journal_ids[1:] if s not in absorbed and s != target]
            summaries = journal_repo.describe_journals([target, *sources]) if sources else {}
            for source in sources:
                merge(target, source)
                absorbed[source] = target
                metrics.add(journals_merged=1)
                # Ligne de détail : le terminal la masque, le journal la garde.
                logger.info(
                    "%s : la revue %s absorbe la revue %s",
                    label,
                    journal_label(summaries[target]),
                    journal_label(summaries[source]),
                    extra={"detail": True},
                )
            avancement.avance()


def _survivor(journal_id: int, absorbed: dict[int, int]) -> int:
    """Revue qui subsiste de `journal_id` après les fusions déjà faites."""
    while journal_id in absorbed:
        journal_id = absorbed[journal_id]
    return journal_id
