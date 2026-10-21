"""Rattachement d'une revue à un enregistrement source via l'espace de noms de son DOI.

Une `source_record` à DOI mais sans `journal_id` reçoit la revue que désigne l'espace de noms de son DOI (`domain/journals/doi_namespaces.py`). Un livre ou un chapitre n'en reçoit pas : un éditeur publie sous un même espace de noms une revue et des livres (EAC, `10.17184/eac.`), ou une revue et les livres de sa collection (Hermès chez CAIRN, `10.3917/herm.`).
"""

from collections.abc import Mapping
from typing import NamedTuple

from domain.journals.containers import is_book_or_chapter
from domain.journals.doi_namespaces import DoiNamespace, resolve_journal
from domain.source_records.corrections import (
    JOURNAL_BY_DOI_KEYS,
    CorrectionKey,
    other_entries,
    raw_value,
    stash_entry,
)
from domain.types import JsonValue

# Provenance inscrite dans `corrections.journal_id.corrected_by`.
JOURNAL_BY_DOI_NAMESPACE = "JOURNAL_BY_DOI_NAMESPACE"


class JournalAttachment(NamedTuple):
    """Revue d'un enregistrement source, et `corrections` complète."""

    journal_id: int | None
    corrections: dict[str, JsonValue]


def attach_journal_by_doi(
    journal_id: int | None,
    doi: str | None,
    raw_doc_type: str | None,
    source: str,
    corrections: Mapping[str, JsonValue],
    namespaces: Mapping[str, DoiNamespace],
) -> JournalAttachment:
    """Revue d'un enregistrement source après le rattachement par l'espace de noms de son DOI.

    Repart du `journal_id` d'avant correction et agit seulement s'il est nul. Quand l'espace de noms désigne une autre revue, ou plus aucune, la revue suit.
    """
    raw_journal_id = raw_value(corrections, CorrectionKey.JOURNAL_ID, journal_id)
    new_corrections = other_entries(corrections, JOURNAL_BY_DOI_KEYS)
    if raw_journal_id is not None or not doi or is_book_or_chapter(raw_doc_type, source):
        return JournalAttachment(raw_journal_id, new_corrections)
    namespace = resolve_journal(doi, namespaces)
    if namespace is None:
        return JournalAttachment(None, new_corrections)
    new_corrections[CorrectionKey.JOURNAL_ID] = stash_entry(None, JOURNAL_BY_DOI_NAMESPACE)
    return JournalAttachment(namespace.journal_id, new_corrections)
