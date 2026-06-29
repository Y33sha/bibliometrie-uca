"""Tests purs de `compute_updates` : rattachement du journal manquant par préfixe DOI,
idempotence et auto-cicatrisation."""

from application.pipeline.metadata_correction.journal_by_doi import compute_updates
from application.ports.pipeline.metadata_correction import (
    JournalByDoiRow,
    JournalCorrectionUpdate,
)
from domain.source_publications.raw_metadata import stash_entry

_PREFIXES = [("10.64628/aak", 7), ("10.5194", 1), ("10.5194/acp", 2)]

_STASH = stash_entry(None, "JOURNAL_BY_DOI_PREFIX")


def _row(**overrides: object) -> JournalByDoiRow:
    base: dict[str, object] = {
        "id": 1,
        "doi": None,
        "journal_id": None,
        "raw_metadata": {},
    }
    base.update(overrides)
    return JournalByDoiRow(**base)  # type: ignore[arg-type]


def test_orphan_with_unique_prefix_is_attached():
    row = _row(doi="10.64628/aak.xyz", journal_id=None)
    assert compute_updates([row], _PREFIXES) == [
        JournalCorrectionUpdate(1, 7, {"journal_id": _STASH})
    ]


def test_orphan_picks_most_specific_nested_prefix():
    row = _row(doi="10.5194/acp.42", journal_id=None)
    assert compute_updates([row], _PREFIXES) == [
        JournalCorrectionUpdate(1, 2, {"journal_id": _STASH})
    ]


def test_orphan_without_matching_prefix_is_untouched():
    assert compute_updates([_row(doi="10.1016/j.ex.2020")], _PREFIXES) == []


def test_orphan_without_doi_is_untouched():
    assert compute_updates([_row(doi=None)], _PREFIXES) == []


def test_source_journal_id_is_not_overwritten():
    # journal_id résolu par la normalisation (pas de stash) : on ne touche pas.
    row = _row(doi="10.64628/aak.xyz", journal_id=99)
    assert compute_updates([row], _PREFIXES) == []


def test_already_attached_is_idempotent():
    # Rattachée au run précédent (colonne posée + stash) : re-dérive le même journal → no-op.
    row = _row(doi="10.64628/aak.xyz", journal_id=7, raw_metadata={"journal_id": _STASH})
    assert compute_updates([row], _PREFIXES) == []


def test_attachment_self_heals_when_prefix_no_longer_matches():
    # Le doi_prefix du journal a disparu : on restaure NULL et on retire le stash.
    row = _row(doi="10.9999/gone.1", journal_id=7, raw_metadata={"journal_id": _STASH})
    assert compute_updates([row], _PREFIXES) == [JournalCorrectionUpdate(1, None, {})]


def test_other_raw_metadata_keys_are_preserved():
    row = _row(
        doi="10.64628/aak.xyz",
        journal_id=None,
        raw_metadata={"doc_type": stash_entry("preprint", "SOME_RULE")},
    )
    assert compute_updates([row], _PREFIXES) == [
        JournalCorrectionUpdate(
            1, 7, {"doc_type": stash_entry("preprint", "SOME_RULE"), "journal_id": _STASH}
        )
    ]
