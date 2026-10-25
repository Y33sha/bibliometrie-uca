"""Entrée de `serials` d'une monographie, d'après celles que portent ses enregistrements."""

from collections.abc import Sequence
from typing import NamedTuple


class MonographSerialChoice(NamedTuple):
    """Entrée de `serials` retenue pour une monographie, ou le conflit qui empêche d'en retenir une."""

    serial_id: int | None
    conflict: tuple[int, ...] = ()


def choose_monograph_serial(
    with_issn: Sequence[int], without_issn: Sequence[int], series_id: int | None = None
) -> MonographSerialChoice:
    """Entrée de `serials` d'une monographie, parmi celles que portent ses enregistrements.

    La seule entrée à ISSN est sa collection. À défaut, la série sans ISSN reconnue entre plusieurs volumes (`series_id`). À défaut, la seule entrée sans ISSN, qui décrit le volume lui-même. À défaut, aucune. Plusieurs entrées au même niveau forment un conflit : rien ne dit laquelle retenir.
    """
    if len(with_issn) > 1:
        return MonographSerialChoice(None, tuple(with_issn))
    if with_issn:
        return MonographSerialChoice(with_issn[0])
    if series_id is not None:
        return MonographSerialChoice(series_id)
    if len(without_issn) > 1:
        return MonographSerialChoice(None, tuple(without_issn))
    return MonographSerialChoice(without_issn[0] if without_issn else None)
