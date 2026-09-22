"""Tests de la vérification des ISSN d'une revue par les notices Sudoc (`domain.journals.issn_check`)."""

from domain.journals.issn_check import (
    JournalIssns,
    SetAsideReason,
    SudocCheck,
    check_journal_issns,
    correction_candidates,
)
from domain.journals.issns import IssnSupport, JournalIssn, issns_from_columns
from domain.sources.sudoc import SudocSerialRecord

PRINT, ELECTRONIC, OTHER = IssnSupport.PRINT, IssnSupport.ELECTRONIC, IssnSupport.OTHER


def _record(
    issn: str,
    issnl: str | None,
    support: IssnSupport | None,
    *,
    title: str = "Revue",
    other: tuple[str, ...] = (),
    preceding: tuple[str, ...] = (),
    succeeding: tuple[str, ...] = (),
    continuation: bool = True,
    supplements: tuple[str, ...] = (),
    cancelled: tuple[str, ...] = (),
    hints: tuple[tuple[str, IssnSupport], ...] = (),
) -> SudocSerialRecord:
    """Notice de test. Les titres précédents et suivants sont par défaut une continuation (`430`, `440`) ; `continuation=False` en fait une scission, une fusion ou une absorption."""
    return SudocSerialRecord(
        ppn=f"ppn-{issn}",
        issn=issn,
        issnl=issnl,
        cancelled_issns=cancelled,
        support=support,
        other_support_issns=other,
        preceding_issns=preceding,
        succeeding_issns=succeeding,
        title=title,
        other_support_hints=hints,
        continuation_issns=(*preceding, *succeeding) if continuation else (),
        supplement_issns=supplements,
    )


def _journal(
    issn: str | None = None,
    eissn: str | None = None,
    issnl: str | None = None,
    rejected: tuple[str, ...] = (),
    title: str = "Revue",
    candidates: tuple[str, ...] = (),
) -> JournalIssns:
    """Revue de test, décrite par les ISSN papier, électronique, ISSN-L et les valeurs mises de côté."""
    return JournalIssns(title, tuple(issns_from_columns(issn, eissn, issnl, rejected)), candidates)


def _label(row: JournalIssn) -> str:
    label = f"{row.support or '?'}:{row.status}"
    if row.linking:
        label += "+L"
    if row.replaced_by:
        label += f">{row.replaced_by}"
    return label


def _rows(check: SudocCheck) -> dict[str, str]:
    """ISSN de la revue après vérification : « support:statut », « +L » pour l'ISSN-L, « >successeur »."""
    return {r.issn: _label(r) for r in check.issns}


class TestSupport:
    def test_each_issn_goes_to_its_support_column(self):
        """L'ISSN rangé comme papier prend le support de sa notice, en ligne."""
        check = check_journal_issns(
            _journal(issn="1476-4687", issnl="0028-0836"),
            {
                "1476-4687": _record("1476-4687", "0028-0836", ELECTRONIC),
                "0028-0836": _record("0028-0836", "0028-0836", PRINT),
            },
        )
        assert _rows(check) == {"1476-4687": "electronic:active", "0028-0836": "print:active+L"}
        assert check.found

    def test_issn_absent_from_sudoc_stays_in_its_column(self):
        """Un ISSN actif sans notice reste actif, avec son support."""
        check = check_journal_issns(
            _journal(issn="0028-0836", eissn="2049-3630"),
            {"0028-0836": _record("0028-0836", "0028-0836", PRINT)},
        )
        assert _rows(check) == {"0028-0836": "print:active+L", "2049-3630": "electronic:active"}

    def test_several_issns_of_one_support_stay_active(self):
        """Deux ISSN en ligne, dont un sans notice : tous deux restent actifs."""
        check = check_journal_issns(
            _journal(issn="1126-6708", eissn="1127-2236", issnl="1029-8479"),
            {"1029-8479": _record("1029-8479", "1029-8479", ELECTRONIC)},
        )
        assert _rows(check) == {
            "1126-6708": "print:active",
            "1127-2236": "electronic:active",
            "1029-8479": "electronic:active+L",
        }
        assert check.set_aside == ()

    def test_mentioned_cd_rom_stays_active(self):
        """Cas réel (Journal of High Energy Physics) : la notice en ligne désigne l'ISSN papier « (Print) » et le CD-ROM « (CD-ROM) »."""
        check = check_journal_issns(
            _journal(issn="1126-6708", eissn="1127-2236", issnl="1029-8479"),
            {
                "1029-8479": _record(
                    "1029-8479",
                    "1029-8479",
                    ELECTRONIC,
                    other=("1126-6708", "1127-2236"),
                    hints=(("1126-6708", PRINT), ("1127-2236", OTHER)),
                )
            },
        )
        assert _rows(check) == {
            "1126-6708": "print:active",
            "1127-2236": "other:active",
            "1029-8479": "electronic:active+L",
        }
        assert check.set_aside == ()

    def test_issn_goes_to_the_column_its_mention_names(self):
        """Cas réel (Lithosphere) : l'ISSN rangé comme électronique, sans notice, prend le support papier que lui donne la mention."""
        check = check_journal_issns(
            _journal(issn="1947-4253", eissn="1941-8264"),
            {
                "1947-4253": _record(
                    "1947-4253",
                    "1947-4253",
                    ELECTRONIC,
                    other=("1941-8264",),
                    hints=(("1941-8264", PRINT),),
                )
            },
        )
        assert _rows(check) == {"1947-4253": "electronic:active+L", "1941-8264": "print:active"}

    def test_mention_completes_the_missing_column(self):
        check = check_journal_issns(
            _journal(eissn="1947-4253"),
            {
                "1947-4253": _record(
                    "1947-4253",
                    "1947-4253",
                    ELECTRONIC,
                    other=("1941-8264",),
                    hints=(("1941-8264", PRINT),),
                )
            },
        )
        assert _rows(check) == {"1947-4253": "electronic:active+L", "1941-8264": "print:active"}

    def test_other_support_completes_the_missing_column(self):
        check = check_journal_issns(
            _journal(issn="0767-9513"),
            {
                "0767-9513": _record("0767-9513", "0767-9513", PRINT, other=("1963-1006",)),
                "1963-1006": _record("1963-1006", "0767-9513", ELECTRONIC),
            },
        )
        assert _rows(check) == {"0767-9513": "print:active+L", "1963-1006": "electronic:active"}

    def test_other_support_of_unknown_support_is_not_added(self):
        """La zone `452` liste aussi les CD-ROM : sans notice ni mention, le support de l'ISSN désigné reste inconnu."""
        check = check_journal_issns(
            _journal(issn="0767-9513"),
            {"0767-9513": _record("0767-9513", "0767-9513", PRINT, other=("1963-1006",))},
        )
        assert _rows(check) == {"0767-9513": "print:active+L"}

    def test_several_issns_of_one_support_with_the_journal_issnl_stay_active(self):
        """Cas réel (Review of Economic Dynamics) : la notice de Toxicological Sciences porte l'ISSN-L de la revue."""
        check = check_journal_issns(
            _journal(issn="1096-6099", eissn="1096-0929", issnl="1094-2025"),
            {
                "1096-6099": _record("1096-6099", "1094-2025", ELECTRONIC),
                "1096-0929": _record(
                    "1096-0929", "1094-2025", ELECTRONIC, title="Toxicological sciences"
                ),
                "1094-2025": _record("1094-2025", "1094-2025", PRINT),
            },
        )
        assert _rows(check) == {
            "1096-6099": "electronic:active",
            "1096-0929": "electronic:active",
            "1094-2025": "print:active+L",
        }

    def test_issn_of_the_same_support_as_the_issnl_stays_active(self):
        """Cas réel (Biological Reviews) : l'ISSN papier de l'ancien titre est l'ISSN-L ; l'ISSN papier du titre actuel reste actif."""
        check = check_journal_issns(
            _journal(issn="1464-7931", eissn="1469-185X", issnl="0006-3231"),
            {
                "1464-7931": _record("1464-7931", "0006-3231", PRINT),
                "1469-185X": _record("1469-185X", "0006-3231", ELECTRONIC),
                "0006-3231": _record("0006-3231", "0006-3231", PRINT),
            },
        )
        assert _rows(check) == {
            "1464-7931": "print:active",
            "1469-185X": "electronic:active",
            "0006-3231": "print:active+L",
        }
        assert check.set_aside == ()

    def test_issn_of_another_issnl_on_a_shared_support_is_discarded(self):
        """Cas réel : la notice en ligne de Marianne désigne comme autre support « Marianne Hors-série collection », d'un autre ISSN-L."""
        check = check_journal_issns(
            _journal(issn="2802-3315", eissn="2491-5769", issnl="1275-7500", title="Marianne"),
            {
                "2802-3315": _record(
                    "2802-3315",
                    "2802-3315",
                    PRINT,
                    title="Marianne Hors-série collection",
                    other=("2491-5769",),
                ),
                "2491-5769": _record(
                    "2491-5769",
                    "1275-7500",
                    ELECTRONIC,
                    title="Marianne",
                    other=("2802-3315", "1275-7500"),
                ),
                "1275-7500": _record(
                    "1275-7500", "1275-7500", PRINT, title="Marianne", other=("2491-5769",)
                ),
            },
        )
        assert _rows(check) == {"2491-5769": "electronic:active", "1275-7500": "print:active+L"}
        assert check.discarded == (("2802-3315", SetAsideReason.OTHER_PUBLICATION),)
        assert check.released == (JournalIssn(issn="2802-3315", support=PRINT),)

    def test_issn_takes_the_support_of_its_record(self):
        check = check_journal_issns(
            _journal(issn="2286-0290", eissn="2286-0290"),
            {"2286-0290": _record("2286-0290", "2286-0290", ELECTRONIC)},
        )
        assert _rows(check) == {"2286-0290": "electronic:active+L"}

    def test_journal_absent_from_sudoc_is_unchanged(self):
        check = check_journal_issns(_journal(issn="0028-0836", eissn="1476-4687"), {})
        assert not check.found
        assert _rows(check) == {"0028-0836": "print:active", "1476-4687": "electronic:active"}


class TestSetAside:
    def test_cd_rom_stays_active(self):
        """Cas réel (Nucleic Acids Research) : le CD-ROM reste actif, avec son support ; l'ISSN en ligne complète la revue."""
        check = check_journal_issns(
            _journal(issn="0305-1048", eissn="1362-4954", issnl="0305-1048"),
            {
                "0305-1048": _record(
                    "0305-1048", "0305-1048", PRINT, other=("1362-4962", "1362-4954")
                ),
                "1362-4954": _record("1362-4954", "0305-1048", OTHER),
                "1362-4962": _record("1362-4962", "0305-1048", ELECTRONIC),
            },
        )
        assert _rows(check) == {
            "0305-1048": "print:active+L",
            "1362-4954": "other:active",
            "1362-4962": "electronic:active",
        }

    def test_preceding_title_that_is_the_issnl_stays_in_issnl(self):
        """Cas réel (Volume !) : l'ISSN de l'ancien titre « Copyright volume ! » est l'ISSN-L du titre actuel."""
        check = check_journal_issns(
            _journal(issn="1950-568X", eissn="2117-4148", issnl="1634-5495"),
            {
                "1950-568X": _record("1950-568X", "1634-5495", ELECTRONIC, other=("2117-4148",)),
                "2117-4148": _record(
                    "2117-4148", "1634-5495", PRINT, other=("1950-568X",), preceding=("1634-5495",)
                ),
                "1634-5495": _record("1634-5495", "1634-5495", PRINT, succeeding=("2117-4148",)),
            },
        )
        assert _rows(check) == {
            "1950-568X": "electronic:active",
            "2117-4148": "print:active",
            "1634-5495": "print:active+L",
        }
        assert check.set_aside == ()

    def test_title_change_with_support_change_is_set_aside(self):
        """Cas réel : la revue en ligne ILCEA suit « Les Cahiers de l'ILCEA », sur papier."""
        check = check_journal_issns(
            _journal(issn="1639-6073", eissn="2101-0609", issnl="2101-0609", title="ILCEA"),
            {
                "2101-0609": _record(
                    "2101-0609", "2101-0609", ELECTRONIC, title="ILCEA", preceding=("1639-6073",)
                ),
                "1639-6073": _record(
                    "1639-6073",
                    "1639-6073",
                    PRINT,
                    title="Les Cahiers de l'ILCEA",
                    other=("2101-0609",),
                    succeeding=("2101-0609",),
                ),
            },
        )
        assert _rows(check) == {
            "1639-6073": "print:related_title>2101-0609",
            "2101-0609": "electronic:active+L",
        }
        assert check.set_aside == (("1639-6073", SetAsideReason.RELATED_TITLE),)

    def test_preceding_title_on_the_other_support_is_a_support_change(self):
        """Cas réel (Mappemonde) : la notice en ligne désigne la notice papier de même titre comme titre précédent."""
        check = check_journal_issns(
            _journal(eissn="1769-7298", issnl="0764-3470", title="Mappemonde"),
            {
                "1769-7298": _record(
                    "1769-7298",
                    "1769-7298",
                    ELECTRONIC,
                    title="Mappemonde",
                    other=("0764-3470",),
                    preceding=("0764-3470",),
                ),
                "0764-3470": _record(
                    "0764-3470",
                    "0764-3470",
                    PRINT,
                    title="Mappemonde",
                    other=("1769-7298",),
                    succeeding=("1769-7298",),
                ),
            },
        )
        assert _rows(check) == {"1769-7298": "electronic:active+L", "0764-3470": "print:active"}
        assert check.set_aside == ()

    def test_preceding_title_with_the_same_issnl_is_a_support_change(self):
        """Cas réel (Actualité et dossier en santé publique) : la notice en ligne s'intitule « ADSP »."""
        check = check_journal_issns(
            _journal(eissn="2804-0163", issnl="1243-275X"),
            {
                "2804-0163": _record(
                    "2804-0163", "1243-275X", ELECTRONIC, title="ADSP", preceding=("1243-275X",)
                ),
                "1243-275X": _record(
                    "1243-275X", "1243-275X", PRINT, title="Actualité et dossier en santé publique"
                ),
            },
        )
        assert _rows(check) == {"2804-0163": "electronic:active", "1243-275X": "print:active+L"}
        assert check.set_aside == ()

    def test_rejected_issn_returns_as_other_support(self):
        """Cas réel (Études mongoles et sibériennes) : l'ISSN papier, mis de côté comme titre précédent, a le même ISSN-L que la notice en ligne."""
        check = check_journal_issns(
            _journal(eissn="2101-0013", issnl="2101-0013", rejected=("0766-5075", "2551-9603")),
            {
                "2101-0013": _record(
                    "2101-0013",
                    "2101-0013",
                    ELECTRONIC,
                    other=("2551-9603",),
                    preceding=("2551-9603",),
                    hints=(("2551-9603", PRINT),),
                ),
                "2551-9603": _record(
                    "2551-9603", "2101-0013", PRINT, other=("2101-0013",), preceding=("0766-5075",)
                ),
            },
        )
        assert _rows(check) == {
            "2101-0013": "electronic:active+L",
            "0766-5075": "?:related_title>2101-0013",
            "2551-9603": "print:active",
        }

    def test_successor_of_another_group_is_set_aside(self):
        check = check_journal_issns(
            _journal(issn="0028-0836", eissn="0036-8075"),
            {
                "0028-0836": _record("0028-0836", "0028-0836", PRINT, succeeding=("0036-8075",)),
                "0036-8075": _record("0036-8075", "0036-8075", PRINT, title="Revue nouvelle série"),
            },
        )
        assert _rows(check) == {"0028-0836": "print:active+L", "0036-8075": "print:related_title"}
        assert check.set_aside == (("0036-8075", SetAsideReason.RELATED_TITLE),)

    def test_cancelled_issn_is_set_aside(self):
        check = check_journal_issns(
            _journal(issn="0028-0836", eissn="0302-2889"),
            {"0028-0836": _record("0028-0836", "0028-0836", PRINT, cancelled=("0302-2889",))},
        )
        assert _rows(check) == {"0028-0836": "print:active+L", "0302-2889": "electronic:cancelled"}
        assert check.set_aside == (("0302-2889", SetAsideReason.CANCELLED),)

    def test_title_before_a_split_is_discarded(self):
        """*Physical Review* s'est scindé en sections : sa notice désigne ses successeurs sans continuation (`446`)."""
        check = check_journal_issns(
            _journal(issn="2469-9926", title="Physical review A", candidates=("0031-899X",)),
            {
                "2469-9926": _record(
                    "2469-9926",
                    "2469-9926",
                    PRINT,
                    title="Physical review A",
                    preceding=("0031-899X",),
                    continuation=False,
                ),
                "0031-899X": _record(
                    "0031-899X",
                    "0031-899X",
                    PRINT,
                    title="Physical review",
                    succeeding=("2469-9926",),
                    continuation=False,
                ),
            },
        )
        assert check.discarded == (("0031-899X", SetAsideReason.LINKED_TITLE),)
        assert _rows(check) == {"2469-9926": "print:active+L"}
        assert check.released == (JournalIssn(issn="0031-899X", support=PRINT),)

    def test_supplement_is_set_aside(self):
        """Cas réel : des enregistrements d'Acta Cardiologica portent l'ISSN de son supplément, dont la notice désigne la revue (`422`)."""
        check = check_journal_issns(
            _journal(issn="0001-5385", title="Acta Cardiologica", candidates=("0373-7934",)),
            {
                "0001-5385": _record("0001-5385", "0001-5385", PRINT, title="Acta cardiologica"),
                "0373-7934": _record(
                    "0373-7934",
                    "0373-7934",
                    PRINT,
                    title="Acta cardiologica. Supplementum",
                    supplements=("0001-5385",),
                ),
            },
        )
        assert check.set_aside == (("0373-7934", SetAsideReason.SUPPLEMENT),)
        assert _rows(check) == {"0001-5385": "print:active+L", "0373-7934": "print:supplement"}

    def test_continuation_coded_on_one_side_only(self):
        """Cas réel : la notice de BMC Family Practice désigne BMC Primary Care comme titre suivant (`440`) ; la notice de BMC Primary Care ne désigne rien."""
        check = check_journal_issns(
            _journal(eissn="2731-4553", title="BMC Primary Care", candidates=("1471-2296",)),
            {
                "2731-4553": _record(
                    "2731-4553", "2731-4553", ELECTRONIC, title="BMC primary care"
                ),
                "1471-2296": _record(
                    "1471-2296",
                    "1471-2296",
                    ELECTRONIC,
                    title="BMC family practice",
                    succeeding=("2731-4553",),
                ),
            },
        )
        assert check.set_aside == (("1471-2296", SetAsideReason.RELATED_TITLE),)
        assert _rows(check) == {
            "2731-4553": "electronic:active+L",
            "1471-2296": "electronic:related_title>2731-4553",
        }


class TestCoherence:
    def test_issn_of_another_publication_is_discarded(self):
        """Cas réel : HAL donne à Neuropsychopharmacology l'ISSN de British Journal of Cancer. Il est écarté : gardé par la revue, il ferait fusionner les deux revues."""
        check = check_journal_issns(
            _journal(
                issn="1740-634X",
                eissn="0007-0920",
                issnl="0893-133X",
                title="Neuropsychopharmacology",
            ),
            {
                "1740-634X": _record(
                    "1740-634X", "0893-133X", ELECTRONIC, title="Neuropsychopharmacology"
                ),
                "0007-0920": _record(
                    "0007-0920", "0007-0920", PRINT, title="British journal of cancer"
                ),
                "0893-133X": _record(
                    "0893-133X", "0893-133X", PRINT, title="Neuropsychopharmacology"
                ),
            },
        )
        assert check.discarded == (("0007-0920", SetAsideReason.OTHER_PUBLICATION),)
        assert _rows(check) == {"1740-634X": "electronic:active", "0893-133X": "print:active+L"}

    def test_other_supports_form_one_group_despite_different_issnls(self):
        """Cas réel (Journal of Applied Physiology) : la notice papier porte l'ISSN-L de l'ancien titre ; la zone `452` relie les deux supports."""
        check = check_journal_issns(
            _journal(issn="8750-7587", eissn="1522-1601", issnl="1522-1601"),
            {
                "8750-7587": _record("8750-7587", "0161-7567", PRINT, other=("1522-1601",)),
                "1522-1601": _record("1522-1601", "1522-1601", ELECTRONIC, other=("8750-7587",)),
            },
        )
        assert check.set_aside == ()
        assert _rows(check) == {"8750-7587": "print:active", "1522-1601": "electronic:active+L"}

    def test_print_and_online_with_nested_titles_form_one_group(self):
        """Cas réel : la notice en ligne de European Archives of Oto-Rhino-Laryngology ajoute « and head & neck » au titre."""
        check = check_journal_issns(
            _journal(
                issn="0937-4477",
                eissn="1434-4726",
                title="European Archives of Oto-Rhino-Laryngology",
            ),
            {
                "0937-4477": _record(
                    "0937-4477",
                    "0937-4477",
                    PRINT,
                    title="European archives of oto-rhino-laryngology",
                ),
                "1434-4726": _record(
                    "1434-4726",
                    "1434-4726",
                    ELECTRONIC,
                    title="European archives of oto-rhino-laryngology and head & neck",
                ),
            },
        )
        assert check.set_aside == ()
        assert _rows(check) == {"0937-4477": "print:active+L", "1434-4726": "electronic:active"}

    def test_nested_titles_do_not_join_a_declared_other_support(self):
        """Cas réel : la notice en ligne d'Hermès désigne son support papier ; « Les Essentiels d'Hermès » est une autre publication."""
        check = check_journal_issns(
            _journal(
                issn="1967-3566",
                eissn="1963-1006",
                issnl="1967-3566",
                title="Les Essentiels d'Hermès",
            ),
            {
                "1967-3566": _record(
                    "1967-3566", "1967-3566", PRINT, title="Les Essentiels d'Hermès"
                ),
                "1963-1006": _record(
                    "1963-1006", "0767-9513", ELECTRONIC, title="Hermès", other=("0767-9513",)
                ),
            },
        )
        assert _rows(check) == {"1967-3566": "print:active+L"}
        assert check.discarded == (("1963-1006", SetAsideReason.OTHER_PUBLICATION),)

    def test_different_series_are_not_joined(self):
        """« Physical review C » et « Physical review D » : les mots de l'un ne sont pas tous dans l'autre."""
        check = check_journal_issns(
            _journal(issn="2469-9985", eissn="2470-0029", title="Physical review C"),
            {
                "2469-9985": _record("2469-9985", "2469-9985", PRINT, title="Physical review C"),
                "2470-0029": _record(
                    "2470-0029", "2470-0010", ELECTRONIC, title="Physical review D"
                ),
            },
        )
        assert check.conflict

    def test_title_breaks_a_tie_between_groups(self):
        check = check_journal_issns(
            _journal(issn="0028-0836", eissn="0007-0920", title="Nature"),
            {
                "0028-0836": _record("0028-0836", "0028-0836", PRINT, title="Nature"),
                "0007-0920": _record(
                    "0007-0920", "0007-0920", PRINT, title="British journal of cancer"
                ),
            },
        )
        assert check.discarded == (("0007-0920", SetAsideReason.OTHER_PUBLICATION),)
        assert _rows(check) == {"0028-0836": "print:active+L"}

    def test_tie_between_groups_changes_nothing(self):
        check = check_journal_issns(
            _journal(issn="0028-0836", eissn="0007-0920"),
            {
                "0028-0836": _record("0028-0836", "0028-0836", PRINT),
                "0007-0920": _record("0007-0920", "0007-0920", PRINT),
            },
        )
        assert check.conflict
        assert _rows(check) == {"0028-0836": "print:active", "0007-0920": "electronic:active"}
        assert check.set_aside == ()

    def test_succeeding_title_breaks_a_tie(self):
        """Cas réel : « INRA productions animales » devient « INRAE productions animales »."""
        check = check_journal_issns(
            _journal(
                issn="2273-7766",
                eissn="2824-3633",
                issnl="2824-3633",
                title="INRAE productions animales",
            ),
            {
                "2273-7766": _record(
                    "2273-7766",
                    "2273-774X",
                    ELECTRONIC,
                    title="INRA productions animales",
                    succeeding=("2824-3633",),
                ),
                "2824-3633": _record(
                    "2824-3633",
                    "2824-3633",
                    ELECTRONIC,
                    title="INRAE productions animales",
                    preceding=("2273-7766",),
                ),
            },
        )
        assert not check.conflict
        assert _rows(check) == {
            "2273-7766": "electronic:related_title>2824-3633",
            "2824-3633": "electronic:active+L",
        }
        assert check.set_aside == (("2273-7766", SetAsideReason.RELATED_TITLE),)


class TestSetAsideReexamined:
    def test_support_change_without_record(self):
        """Cas réel (Revista Hospitalidade) : la notice en ligne désigne l'ISSN papier, sans notice, comme titre précédent et comme autre support « (Print) »."""
        check = check_journal_issns(
            _journal(eissn="2179-9164", issnl="2179-9164", rejected=("1807-975X",)),
            {
                "2179-9164": _record(
                    "2179-9164",
                    "2179-9164",
                    ELECTRONIC,
                    other=("1807-975X",),
                    preceding=("1807-975X",),
                    hints=(("1807-975X", PRINT),),
                )
            },
        )
        assert _rows(check) == {"2179-9164": "electronic:active+L", "1807-975X": "print:active"}

    def test_set_aside_issn_of_the_journal_becomes_active(self):
        """Cas réel : un passage antérieur a mis de côté l'ISSN en ligne de European Archives of Oto-Rhino-Laryngology ; il redevient actif."""
        check = check_journal_issns(
            _journal(
                issn="0937-4477",
                rejected=("1434-4726",),
                title="European Archives of Oto-Rhino-Laryngology",
            ),
            {
                "0937-4477": _record(
                    "0937-4477",
                    "0937-4477",
                    PRINT,
                    title="European archives of oto-rhino-laryngology",
                ),
                "1434-4726": _record(
                    "1434-4726",
                    "1434-4726",
                    ELECTRONIC,
                    title="European archives of oto-rhino-laryngology and head & neck",
                ),
            },
        )
        assert _rows(check) == {"0937-4477": "print:active+L", "1434-4726": "electronic:active"}

    def test_rejected_issn_of_another_publication_is_discarded(self):
        """Un ISSN d'une autre publication, mis de côté par un passage antérieur, est écarté de la revue."""
        check = check_journal_issns(
            _journal(
                issn="1740-634X",
                issnl="0893-133X",
                rejected=("0007-0920",),
                title="Neuropsychopharmacology",
            ),
            {
                "1740-634X": _record(
                    "1740-634X", "0893-133X", ELECTRONIC, title="Neuropsychopharmacology"
                ),
                "0007-0920": _record(
                    "0007-0920", "0007-0920", PRINT, title="British journal of cancer"
                ),
                "0893-133X": _record(
                    "0893-133X", "0893-133X", PRINT, title="Neuropsychopharmacology"
                ),
            },
        )
        assert _rows(check) == {"1740-634X": "electronic:active", "0893-133X": "print:active+L"}
        assert check.set_aside == ()
        assert check.discarded == (("0007-0920", SetAsideReason.OTHER_PUBLICATION),)

    def test_group_of_rejected_issns_with_another_title_is_discarded(self):
        check = check_journal_issns(
            _journal(issn="0028-0836", rejected=("0007-0920",), title="Nature"),
            {
                "0007-0920": _record(
                    "0007-0920", "0007-0920", PRINT, title="British journal of cancer"
                )
            },
        )
        assert _rows(check) == {"0028-0836": "print:active"}
        assert check.discarded == (("0007-0920", SetAsideReason.OTHER_PUBLICATION),)

    def test_print_issn_prevails_over_the_cd_rom(self):
        """Cas réel : la revue « Methods in enzymology on CD-ROM/Methods in enzymology » a ses ISSN papier et CD-ROM mis de côté ; ils redeviennent actifs."""
        check = check_journal_issns(
            _journal(
                eissn="1557-7988",
                rejected=("0076-6879", "1079-2376"),
                title="Methods in enzymology on CD-ROM/Methods in enzymology",
            ),
            {
                "0076-6879": _record(
                    "0076-6879", "0076-6879", PRINT, title="Methods in enzymology"
                ),
                "1079-2376": _record(
                    "1079-2376", None, OTHER, title="Methods in enzymology on CD-ROM"
                ),
            },
        )
        assert _rows(check) == {
            "1557-7988": "electronic:active",
            "0076-6879": "print:active+L",
            "1079-2376": "other:active",
        }


class TestDocumentIssns:
    def test_document_issn_of_the_journal_completes_a_column(self):
        """Cas réel (Diabetes Care) : les enregistrements portent l'ISSN en ligne, absent de la revue."""
        check = check_journal_issns(
            _journal(issn="0149-5992", issnl="0149-5992", candidates=("1935-5548",)),
            {
                "0149-5992": _record("0149-5992", "0149-5992", PRINT, title="Diabetes care"),
                "1935-5548": _record("1935-5548", "0149-5992", ELECTRONIC, title="Diabetes care"),
            },
        )
        assert _rows(check) == {"0149-5992": "print:active+L", "1935-5548": "electronic:active"}

    def test_document_issn_of_another_publication_is_discarded(self):
        """Cas réel : des enregistrements de Technè portent l'ISSN de la revue « Spotlight »."""
        check = check_journal_issns(
            _journal(
                issn="1254-7867",
                eissn="2534-5168",
                issnl="1254-7867",
                title="Technè",
                candidates=("2750-6185",),
            ),
            {
                "1254-7867": _record("1254-7867", "1254-7867", PRINT, title="Technè"),
                "2534-5168": _record("2534-5168", "1254-7867", ELECTRONIC, title="Technè"),
                "2750-6185": _record("2750-6185", "2750-6185", ELECTRONIC, title="Spotlight"),
            },
        )
        assert _rows(check) == {"1254-7867": "print:active+L", "2534-5168": "electronic:active"}
        assert check.discarded == (("2750-6185", SetAsideReason.OTHER_PUBLICATION),)

    def test_document_issns_do_not_take_over_the_journal(self):
        """Cas réel (INRAE productions animales) : les enregistrements portent les deux ISSN de l'ancien titre, qui forment le groupe le plus nombreux."""
        check = check_journal_issns(
            _journal(
                eissn="2824-3633",
                issnl="2824-3633",
                rejected=("2273-7766",),
                title="INRAE productions animales",
                candidates=("2273-774X",),
            ),
            {
                "2824-3633": _record(
                    "2824-3633",
                    "2824-3633",
                    ELECTRONIC,
                    title="INRAE productions animales",
                    preceding=("2273-774X", "2273-7766"),
                ),
                "2273-774X": _record(
                    "2273-774X",
                    "2273-774X",
                    PRINT,
                    title="INRA productions animales",
                    other=("2273-7766",),
                ),
                "2273-7766": _record(
                    "2273-7766",
                    "2273-774X",
                    ELECTRONIC,
                    title="INRA productions animales",
                    other=("2273-774X",),
                ),
            },
        )
        assert _rows(check) == {
            "2824-3633": "electronic:active+L",
            "2273-7766": "electronic:related_title>2824-3633",
            "2273-774X": "print:related_title>2824-3633",
        }
        assert check.set_aside == (("2273-774X", SetAsideReason.RELATED_TITLE),)


class TestCorrection:
    def test_rejected_issn_is_corrected(self):
        """Cas réel : `1950-2051` pour la revue Constructif, dont l'ISSN est `1950-5051`. La valeur mal formée désigne sa correction."""
        check = check_journal_issns(
            _journal(rejected=("1950-2051",), title="Constructif"),
            {"1950-5051": _record("1950-5051", "1950-5051", PRINT, title="Constructif")},
        )
        assert check.corrections == (("1950-2051", "1950-5051"),)
        assert _rows(check) == {
            "1950-2051": "?:malformed>1950-5051",
            "1950-5051": "print:active+L",
        }

    def test_distant_title_prevents_correction(self):
        """Cas réel : la notice de `1288-0124` s'intitule seulement « Bulletin »."""
        check = check_journal_issns(
            _journal(rejected=("1298-0124",), title="Bulletin de l'ATELIER"),
            {"1288-0124": _record("1288-0124", "1288-0124", PRINT, title="Bulletin")},
        )
        assert check.corrections == ()
        assert _rows(check) == {"1298-0124": "?:malformed"}

    def test_correction_of_another_issnl_is_refused(self):
        check = check_journal_issns(
            _journal(issn="0028-0836", rejected=("1476-4688",), title="Nature"),
            {
                "0028-0836": _record("0028-0836", "0028-0836", PRINT, title="Nature"),
                "1476-4687": _record("1476-4687", "0036-8075", ELECTRONIC, title="Nature"),
            },
        )
        assert check.corrections == ()

    def test_valid_rejected_issn_is_kept_as_is(self):
        """Une valeur valide mise de côté, sans notice, garde son statut."""
        check = check_journal_issns(
            _journal(issn="0305-1048", rejected=("1362-4954",)),
            {"0305-1048": _record("0305-1048", "0305-1048", PRINT)},
        )
        assert check.corrections == ()
        assert _rows(check) == {"0305-1048": "print:active+L", "1362-4954": "?:unverified"}

    def test_correction_candidates(self):
        assert "1950-5051" in correction_candidates(("1950-2051", "(Internet)"))
        assert correction_candidates(("(Internet)",)) == frozenset()
