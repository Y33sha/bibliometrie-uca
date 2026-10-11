"""Tests de la fusion de deux revues : type de la revue fusionnée."""

import pytest

from domain.journals.journal import JournalType
from domain.journals.merge import merged_journal_type


@pytest.mark.parametrize(
    ("target", "source", "expected"),
    [
        (JournalType.UNKNOWN, JournalType.MEDIA, JournalType.MEDIA),
        (JournalType.JOURNAL, JournalType.MEDIA, JournalType.JOURNAL),
        (JournalType.JOURNAL, JournalType.UNKNOWN, JournalType.JOURNAL),
    ],
)
def test_merged_journal_type_keeps_known_target_type(target, source, expected):
    assert merged_journal_type(target, source) == expected
