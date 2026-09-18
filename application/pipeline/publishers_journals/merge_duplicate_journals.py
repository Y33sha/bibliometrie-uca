"""Sous-étape de la phase `publishers_journals` — fusionne les revues en double.

Quatre règles désignent la même publication :

1. deux revues vérifiées dans le Sudoc partagent leur ISSN-L ;
2. elles portent le même ISSN dans une colonne, et les mots d'un titre sont tous dans l'autre (« BMJ » et « BMJ-BRITISH MEDICAL JOURNAL ») ;
3. elles sont seules à porter leur titre normalisé, au moins une est sans ISSN, et leurs enregistrements partagent un préfixe DOI ;
4. des enregistrements d'une même publication les portent, leurs titres sont compatibles (« Phys.Rev.Lett. » et « Physical Review Letters », voir `compatible_titles`), et elles n'ont pas chacune des ISSN sans aucun en commun.

L'éditeur ne sert pas de contrôle : deux fiches d'éditeur désignent souvent la même maison. La fusion elle-même est celle de l'administration des revues, injectée par le composition-root : publications et métadonnées passent à la cible, qui requalifie les publications absorbées, puis la source est supprimée. Le journal garde le titre, l'éditeur et les ISSN des deux revues.
"""

import logging
from collections.abc import Callable, Sequence

from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import progression
from application.pipeline.publishers_journals._journal_label import journal_label
from application.ports.pipeline.journals import (
    JournalMergeCandidate,
    JournalMergeQueries,
    JournalPublicationPair,
    JournalTitleRow,
)
from domain.journals.titles import compatible_titles, nested_titles

MergeJournals = Callable[[int, int], None]
"""`(cible, source)` : fusionne la revue source dans la cible et valide la transaction."""

MergeGroup = tuple[str, tuple[int, ...]]
"""`(libellé, revues)` : ce que les revues partagent, puis les revues, la cible en tête."""

# Ce que les revues d'un groupe partagent, une règle par barre d'avancement.
_REGLES = (
    "même ISSN-L",
    "même ISSN et titre emboîté",
    "mêmes titre et préfixe DOI",
    "même publication et titre compatible",
)
_LARGEUR_REGLE = max(len(regle) for regle in _REGLES)


def _branche(regle: str) -> str:
    """Libellé de la barre d'avancement d'une règle : sa branche, son nom, et le remplissage qui aligne les barres les unes sous les autres."""
    return f"{BRANCHE}{regle:<{_LARGEUR_REGLE}}"


def run_merge_duplicate_journals(
    logger: logging.Logger,
    *,
    journal_repo: JournalMergeQueries,
    merge: MergeJournals,
) -> PhaseMetrics:
    """Applique les quatre règles dans l'ordre. Chaque règle lit ses groupes après les fusions des précédentes."""
    metrics = PhaseMetrics()
    # Revue absorbée → revue qui l'a absorbée. Une revue qui partage ses deux ISSN avec son double figure dans deux groupes.
    absorbed: dict[int, int] = {}
    issnl, issn_et_titre, titre_et_prefixe, publication_et_titre = _REGLES
    ouverte = False

    def merge_groups(groups: Sequence[MergeGroup], regle: str) -> None:
        nonlocal ouverte
        if not groups:
            return
        if not ouverte:
            etape(logger, "Fusion de revues :")
            ouverte = True
        _merge_groups(logger, metrics, journal_repo, merge, absorbed, groups, regle)

    merge_groups(
        [(f"ISSN-L {g.key}", g.journal_ids) for g in journal_repo.find_journals_sharing_issnl()],
        issnl,
    )
    shared = [
        (f"ISSN {g.issn}", tuple(j.id for j in g.journals if _nested(g.journals[0], j)))
        for g in journal_repo.find_journals_sharing_column_issn()
    ]
    merge_groups([(label, ids) for label, ids in shared if len(ids) > 1], issn_et_titre)
    merge_groups(
        [(f"titre {g.key!r}", g.journal_ids) for g in journal_repo.find_same_title_duplicates()],
        titre_et_prefixe,
    )
    merge_groups(
        _compatible_pairs(journal_repo.find_journals_sharing_a_publication()),
        publication_et_titre,
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


def _compatible_pairs(pairs: Sequence[JournalPublicationPair]) -> list[MergeGroup]:
    """Paires de revues aux titres compatibles, la cible en tête.

    Deux revues qui ont chacune des ISSN, sans aucun en commun, sont deux publications distinctes : « Geosciences » (2076-3263) et « Geosciences » (1023-7429).
    """
    groups: list[MergeGroup] = []
    for pair in pairs:
        a, b = pair.first, pair.second
        if a.issns and b.issns and not a.issns & b.issns:
            continue
        if not compatible_titles(a.title, b.title):
            continue
        target, source = sorted((a, b), key=_merge_priority, reverse=True)
        label = accord(pair.publications, "publication commune", "publications communes")
        groups.append((label, (target.id, source.id)))
    return groups


def _merge_priority(journal: JournalMergeCandidate) -> tuple[bool, int, int]:
    """Rang de cible : la revue qui a un ISSN, puis celle qui porte le plus de publications, puis la plus ancienne."""
    return (bool(journal.issns), journal.pub_count, -journal.id)


def _merge_groups(
    logger: logging.Logger,
    metrics: PhaseMetrics,
    journal_repo: JournalMergeQueries,
    merge: MergeJournals,
    absorbed: dict[int, int],
    groups: Sequence[MergeGroup],
    regle: str,
) -> None:
    """Fusionne chaque groupe dans sa première revue. Une revue déjà absorbée est passée ; une cible déjà absorbée cède la place à celle qui l'a absorbée."""
    metrics.add(total=len(groups))
    with progression(len(groups), _branche(regle), logger) as avancement:
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
