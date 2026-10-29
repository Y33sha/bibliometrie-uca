"""Nature d'une monographie : volume d'actes ou livre."""

from collections.abc import Iterable
from typing import NamedTuple

from domain.serials.containers import is_conference
from domain.serials.serial import SerialType
from domain.serials.titles import names_proceedings


class MonographRecord(NamedTuple):
    """Enregistrement source d'une monographie, réduit aux indices de congrès."""

    source: str
    raw_doc_type: str | None
    declares_conference: bool


def is_proceedings_volume(
    records: Iterable[MonographRecord], *, collection_type: str | None, title: str
) -> bool:
    """Vrai si la monographie est un volume d'actes. Un seul indice suffit : un enregistrement source issu d'un congrès, une collection de type recueil d'actes, ou un titre qui annonce des actes."""
    return (
        any(
            is_conference(r.raw_doc_type, r.source, declares_conference=r.declares_conference)
            for r in records
        )
        or collection_type == SerialType.PROCEEDINGS
        or names_proceedings(title)
    )
