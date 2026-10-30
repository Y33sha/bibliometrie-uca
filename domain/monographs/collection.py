"""Choix de l'entrée de `serials` d'une monographie, parmi celles de ses enregistrements sources."""

from collections.abc import Sequence
from typing import NamedTuple


class MonographSerialChoice(NamedTuple):
    """Entrée de `serials` retenue pour une monographie, ou les entrées en conflit."""

    serial_id: int | None
    conflict: tuple[int, ...] = ()


def choose_monograph_serial(
    with_issn: Sequence[int], without_issn: Sequence[int], series_id: int | None = None
) -> MonographSerialChoice:
    """Choisit l'entrée de `serials` d'une monographie : l'entrée à ISSN, qui est la collection, sinon la série sans ISSN reconnue entre plusieurs volumes (`series_id`), sinon l'entrée sans ISSN, qui décrit le volume. Plusieurs entrées au même rang forment un conflit."""
    if len(with_issn) > 1:
        return MonographSerialChoice(None, tuple(with_issn))
    if with_issn:
        return MonographSerialChoice(with_issn[0])
    if series_id is not None:
        return MonographSerialChoice(series_id)
    if len(without_issn) > 1:
        return MonographSerialChoice(None, tuple(without_issn))
    return MonographSerialChoice(without_issn[0] if without_issn else None)
