"""Revues homonymes de deux éditeurs à fusionner.

La fusion de deux éditeurs fusionne aussi leurs revues de même titre normalisé. Certaines paires de revues bloquent la fusion des éditeurs : l'utilisatrice les traite d'abord dans l'administration des revues.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from domain.errors import BlockingSerial
from domain.serials.issns import SerialIssn, issn_conflict


@dataclass(frozen=True, slots=True)
class SharedTitlePair:
    """Deux revues de même titre normalisé, l'une de l'éditeur cible, l'autre de l'éditeur source."""

    target_serial_id: int
    target_title: str
    target_issns: tuple[SerialIssn, ...]
    source_serial_id: int
    source_title: str
    source_issns: tuple[SerialIssn, ...]


def split_shared_title_pairs(
    pairs: Sequence[SharedTitlePair],
) -> tuple[list[SharedTitlePair], list[BlockingSerial]]:
    """Sépare les paires fusionnables des paires qui bloquent la fusion des éditeurs.

    Une paire bloque dans deux cas. Ses ISSN se contredisent (`issn_conflict`). Ou l'une de ses revues figure dans une autre paire : son éditeur contient alors deux revues de même titre normalisé, doublon à résoudre avant la fusion.
    """
    target_seen = Counter(pair.target_serial_id for pair in pairs)
    source_seen = Counter(pair.source_serial_id for pair in pairs)
    mergeable: list[SharedTitlePair] = []
    blockers: list[BlockingSerial] = []
    for pair in pairs:
        reasons: list[str] = []
        if target_seen[pair.target_serial_id] > 1:
            reasons.append("doublon interne dans l'éditeur cible (titre dédupliqué)")
        if source_seen[pair.source_serial_id] > 1:
            reasons.append("doublon interne dans l'éditeur source (titre dédupliqué)")
        if conflict := issn_conflict(pair.target_issns, pair.source_issns):
            reasons.append(f"{conflict} (cible / source)")
        if reasons:
            blockers.append(
                BlockingSerial(
                    target_serial_id=pair.target_serial_id,
                    target_title=pair.target_title,
                    source_serial_id=pair.source_serial_id,
                    source_title=pair.source_title,
                    reason=" ; ".join(reasons),
                )
            )
        else:
            mergeable.append(pair)
    return mergeable, blockers
