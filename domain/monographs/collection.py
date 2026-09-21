"""Entrée de `journals` d'une monographie, d'après celles que portent ses enregistrements."""

from collections.abc import Sequence
from typing import NamedTuple


class MonographJournalChoice(NamedTuple):
    """Entrée de `journals` retenue pour une monographie, ou le conflit qui empêche d'en retenir une."""

    journal_id: int | None
    conflict: tuple[int, ...] = ()


def choose_monograph_journal(
    with_issn: Sequence[int], without_issn: Sequence[int]
) -> MonographJournalChoice:
    """Entrée de `journals` d'une monographie, parmi celles que portent ses enregistrements.

    La seule entrée à ISSN est sa collection. À défaut, la seule entrée sans ISSN décrit le volume lui-même. À défaut, aucune. Plusieurs entrées au même niveau forment un conflit : rien ne dit laquelle retenir.
    """
    if len(with_issn) > 1:
        return MonographJournalChoice(None, tuple(with_issn))
    if with_issn:
        return MonographJournalChoice(with_issn[0])
    if len(without_issn) > 1:
        return MonographJournalChoice(None, tuple(without_issn))
    return MonographJournalChoice(without_issn[0] if without_issn else None)
