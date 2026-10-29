"""Rattachement d'une revue à un enregistrement source via l'espace de noms de ses DOI.

Un enregistrement source à DOI mais sans revue reçoit la revue que désignent les espaces de noms de ses DOI (`domain/serials/doi_namespaces.py`). Si ses DOI désignent plusieurs revues, il reste sans revue. Un livre ou un chapitre n'en reçoit pas : un éditeur publie sous un même espace de noms une revue et des livres (EAC, `10.17184/eac.`), ou une revue et les livres de sa collection (Hermès chez CAIRN, `10.3917/herm.`).
"""

from collections.abc import Collection, Mapping
from typing import NamedTuple

from domain.serials.containers import is_book_or_chapter
from domain.serials.doi_namespaces import DoiNamespace, resolve_serial
from domain.source_records.corrections import (
    SERIAL_BY_DOI_KEYS,
    CorrectionKey,
    other_entries,
    raw_value,
    stash_entry,
)
from domain.types import JsonValue

# Provenance inscrite dans `corrections.serial_id.corrected_by`.
SERIAL_BY_DOI_NAMESPACE = "SERIAL_BY_DOI_NAMESPACE"


class SerialAttachment(NamedTuple):
    """Revue d'un enregistrement source, et `corrections` complète."""

    serial_id: int | None
    corrections: dict[str, JsonValue]


def attach_serial_by_doi(
    serial_id: int | None,
    dois: Collection[str],
    raw_doc_type: str | None,
    source: str,
    corrections: Mapping[str, JsonValue],
    namespaces: Mapping[str, DoiNamespace],
) -> SerialAttachment:
    """Revue d'un enregistrement source après le rattachement par l'espace de noms de ses DOI.

    Repart du `serial_id` d'avant correction et agit seulement s'il est nul. Quand les espaces de noms désignent une autre revue, ou plus aucune, la revue suit.
    """
    raw_serial_id = raw_value(corrections, CorrectionKey.SERIAL_ID, serial_id)
    new_corrections = other_entries(corrections, SERIAL_BY_DOI_KEYS)
    if raw_serial_id is not None or not dois or is_book_or_chapter(raw_doc_type, source):
        return SerialAttachment(raw_serial_id, new_corrections)
    serials = {ns.serial_id for doi in dois if (ns := resolve_serial(doi, namespaces))}
    if len(serials) != 1:
        return SerialAttachment(None, new_corrections)
    new_corrections[CorrectionKey.SERIAL_ID] = stash_entry(None, SERIAL_BY_DOI_NAMESPACE)
    return SerialAttachment(serials.pop(), new_corrections)
