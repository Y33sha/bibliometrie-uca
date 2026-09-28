"""Nature d'une monographie : volume d'actes ou livre."""

from collections.abc import Iterable
from typing import NamedTuple

from domain.journals.containers import is_conference
from domain.journals.journal import JournalType
from domain.journals.titles import names_proceedings


class MonographRecord(NamedTuple):
    """Ce qu'un enregistrement rattaché à la monographie dit de lui-même : sa source, son type brut, et le congrès qu'il déclare."""

    source: str
    raw_doc_type: str | None
    declares_conference: bool


def is_proceedings_volume(
    records: Iterable[MonographRecord], *, collection_type: str | None, title: str
) -> bool:
    """Indique si une monographie est un volume d'actes.

    Trois signaux suffisent chacun : un enregistrement issu d'un congrès (`is_conference`), une collection typée recueil d'actes, un titre anglais qui annonce des actes (`names_proceedings`). Les chapitres des « Actes du colloque » en sciences humaines restent ainsi des chapitres.
    """
    return (
        any(
            is_conference(r.raw_doc_type, r.source, declares_conference=r.declares_conference)
            for r in records
        )
        or collection_type == JournalType.PROCEEDINGS
        or names_proceedings(title)
    )
