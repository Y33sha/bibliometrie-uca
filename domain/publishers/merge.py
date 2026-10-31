"""Revues homonymes de deux éditeurs à fusionner.

La fusion de deux éditeurs fusionne aussi leurs revues de même titre normalisé. Certaines paires de revues bloquent la fusion des éditeurs : elles se traitent d'abord dans l'administration des revues.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from domain.errors import BlockingSerial


@dataclass(frozen=True, slots=True)
class SharedTitlePair:
    """Deux revues de même titre normalisé, l'une de l'éditeur cible, l'autre de l'éditeur source."""

    target_serial_id: int
    target_title: str
    target_issnl: str | None
    source_serial_id: int
    source_title: str
    source_issnl: str | None


def split_shared_title_pairs(
    pairs: Sequence[SharedTitlePair],
) -> tuple[list[SharedTitlePair], list[BlockingSerial]]:
    """Sépare les paires fusionnables des paires qui bloquent la fusion des éditeurs.

    Une paire bloque dans deux cas. Ses deux revues ont chacune un ISSN-L : deux ISSN-L désignent deux revues. Ou l'une de ses revues figure dans une autre paire : l'autre éditeur contient alors deux revues de même titre normalisé, doublon à résoudre avant la fusion.
    """
    target_seen = Counter(pair.target_serial_id for pair in pairs)
    source_seen = Counter(pair.source_serial_id for pair in pairs)
    mergeable: list[SharedTitlePair] = []
    blockers: list[BlockingSerial] = []
    for pair in pairs:
        reasons: list[str] = []
        if target_seen[pair.target_serial_id] > 1:
            reasons.append("doublon interne dans l'éditeur source (titre dédupliqué)")
        if source_seen[pair.source_serial_id] > 1:
            reasons.append("doublon interne dans l'éditeur cible (titre dédupliqué)")
        if pair.target_issnl and pair.source_issnl:
            reasons.append(
                f"ISSN-L différents : {pair.target_issnl} / {pair.source_issnl} (cible / source)"
            )
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
