"""Tests de la vérification des ISSN d'une revue par les notices Sudoc (`domain.journals.issn_check`)."""

from domain.journals.issn_check import JournalIssns, check_journal_issns, correction_candidates
from domain.sources.sudoc import SudocSerialRecord, Support

PRINT, ELECTRONIC = Support.PRINT, Support.ELECTRONIC


def _record(
    issn: str,
    issnl: str,
    support: Support | None,
    *,
    title: str = "Revue",
    other: tuple[str, ...] = (),
) -> SudocSerialRecord:
    return SudocSerialRecord(
        ppn=f"ppn-{issn}",
        issn=issn,
        issnl=issnl,
        cancelled_issns=(),
        support=support,
        other_support_issns=other,
        title=title,
    )


def _journal(
    issn: str | None = None,
    eissn: str | None = None,
    issnl: str | None = None,
    rejected: tuple[str, ...] = (),
    title: str = "Revue",
) -> JournalIssns:
    return JournalIssns(title, issn, eissn, issnl, rejected)


class TestPlacement:
    def test_each_issn_goes_to_its_support_column(self):
        """L'ISSN électronique rangé dans `issn` passe dans `eissn`."""
        check = check_journal_issns(
            _journal(issn="1476-4687", issnl="0028-0836"),
            {
                "1476-4687": _record("1476-4687", "0028-0836", ELECTRONIC),
                "0028-0836": _record("0028-0836", "0028-0836", PRINT),
            },
        )
        assert (check.issn, check.eissn, check.issnl) == ("0028-0836", "1476-4687", "0028-0836")
        assert check.found
        assert not check.ambiguous_support

    def test_issn_absent_from_sudoc_stays_in_its_column(self):
        check = check_journal_issns(
            _journal(issn="0028-0836", eissn="2049-3630"),
            {"0028-0836": _record("0028-0836", "0028-0836", PRINT)},
        )
        assert (check.issn, check.eissn) == ("0028-0836", "2049-3630")

    def test_other_support_completes_the_missing_column(self):
        check = check_journal_issns(
            _journal(issn="0767-9513"),
            {"0767-9513": _record("0767-9513", "0767-9513", PRINT, other=("1963-1006",))},
        )
        assert (check.issn, check.eissn, check.issnl) == ("0767-9513", "1963-1006", "0767-9513")

    def test_two_issns_of_the_same_support_stay_in_place(self):
        check = check_journal_issns(
            _journal(issn="0028-0836", eissn="0036-8075"),
            {
                "0028-0836": _record("0028-0836", "0028-0836", PRINT),
                "0036-8075": _record("0036-8075", "0028-0836", PRINT),
            },
        )
        assert check.ambiguous_support
        assert (check.issn, check.eissn, check.issnl) == ("0028-0836", "0036-8075", "0028-0836")

    def test_journal_absent_from_sudoc_is_unchanged(self):
        journal = _journal(issn="0028-0836", eissn="1476-4687")
        check = check_journal_issns(journal, {})
        assert not check.found
        assert (check.issn, check.eissn, check.issnl) == ("0028-0836", "1476-4687", None)


class TestCoherence:
    def test_issn_of_another_issnl_is_removed(self):
        """Cas réel : HAL donne à Neuropsychopharmacology l'ISSN de British Journal of Cancer."""
        check = check_journal_issns(
            _journal(issn="1740-634X", eissn="0007-0920", issnl="0893-133X"),
            {
                "1740-634X": _record("1740-634X", "0893-133X", ELECTRONIC),
                "0007-0920": _record("0007-0920", "0007-0920", PRINT),
                "0893-133X": _record("0893-133X", "0893-133X", PRINT),
            },
        )
        assert check.intruders == ("0007-0920",)
        assert (check.issn, check.eissn, check.issnl) == ("0893-133X", "1740-634X", "0893-133X")

    def test_tie_between_issnls_changes_nothing(self):
        journal = _journal(issn="0028-0836", eissn="0007-0920")
        check = check_journal_issns(
            journal,
            {
                "0028-0836": _record("0028-0836", "0028-0836", PRINT),
                "0007-0920": _record("0007-0920", "0007-0920", PRINT),
            },
        )
        assert check.conflict
        assert (check.issn, check.eissn, check.issnl) == ("0028-0836", "0007-0920", None)
        assert check.intruders == ()


class TestCorrection:
    def test_rejected_issn_is_corrected(self):
        """Cas réel : `1950-2051` pour la revue Constructif, dont l'ISSN est `1950-5051`."""
        check = check_journal_issns(
            _journal(rejected=("1950-2051",), title="Constructif"),
            {"1950-5051": _record("1950-5051", "1950-5051", PRINT, title="Constructif")},
        )
        assert check.corrections == (("1950-2051", "1950-5051"),)
        assert check.rejected == ()
        assert (check.issn, check.issnl) == ("1950-5051", "1950-5051")

    def test_distant_title_prevents_correction(self):
        """Cas réel : la notice de `1288-0124` s'intitule seulement « Bulletin »."""
        check = check_journal_issns(
            _journal(rejected=("1298-0124",), title="Bulletin de l'ATELIER"),
            {"1288-0124": _record("1288-0124", "1288-0124", PRINT, title="Bulletin")},
        )
        assert check.corrections == ()
        assert check.rejected == ("1298-0124",)

    def test_correction_of_another_issnl_is_refused(self):
        check = check_journal_issns(
            _journal(issn="0028-0836", rejected=("1476-4688",), title="Nature"),
            {
                "0028-0836": _record("0028-0836", "0028-0836", PRINT, title="Nature"),
                "1476-4687": _record("1476-4687", "0036-8075", ELECTRONIC, title="Nature"),
            },
        )
        assert check.corrections == ()

    def test_correction_candidates(self):
        assert "1950-5051" in correction_candidates(("1950-2051", "(Internet)"))
