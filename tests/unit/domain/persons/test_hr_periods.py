from datetime import date

from domain.persons.hr_periods import HrPeriod, merge_periods, updated_periods

UFR = "UFR X"
LAB = "LAB Y"


def test_periodes_contigues_fusionnent():
    periods = [
        HrPeriod(LAB, date(2026, 1, 1), date(2026, 5, 31)),
        HrPeriod(LAB, date(2026, 6, 1), None),
    ]
    assert merge_periods(periods) == [HrPeriod(LAB, date(2026, 1, 1), None)]


def test_periodes_chevauchantes_fusionnent_sur_la_fin_la_plus_tardive():
    periods = [
        HrPeriod(LAB, date(2020, 1, 1), date(2026, 12, 31)),
        HrPeriod(LAB, date(2021, 1, 1), date(2025, 12, 31)),
    ]
    assert merge_periods(periods) == [HrPeriod(LAB, date(2020, 1, 1), date(2026, 12, 31))]


def test_periodes_separees_restent_distinctes():
    periods = [
        HrPeriod(LAB, date(2020, 1, 1), date(2020, 12, 31)),
        HrPeriod(LAB, date(2022, 1, 1), None),
    ]
    assert merge_periods(periods) == periods


def test_unites_differentes_ne_fusionnent_pas():
    periods = [HrPeriod(UFR, date(2020, 1, 1), None), HrPeriod(LAB, date(2020, 1, 1), None)]
    assert sorted(merge_periods(periods), key=lambda p: p.unit_label) == sorted(
        periods, key=lambda p: p.unit_label
    )


def test_debut_absent_fusionne_avec_la_suite():
    periods = [HrPeriod(LAB, None, date(2020, 12, 31)), HrPeriod(LAB, date(2021, 1, 1), None)]
    assert merge_periods(periods) == [HrPeriod(LAB, None, None)]


def test_export_prolonge_la_presence_anterieure():
    """Présence en base depuis 2005, export depuis 2021 : une seule période, depuis 2005."""
    stored = [HrPeriod(UFR, date(2005, 9, 1), None)]
    exported = [HrPeriod(UFR, date(2021, 1, 1), None)]
    assert updated_periods(stored, exported, date(2025, 12, 15)) == [
        HrPeriod(UFR, date(2005, 9, 1), None)
    ]


def test_export_fait_foi_sur_la_fenetre():
    """Période ouverte en base, départ dans l'export : la période s'arrête au départ."""
    stored = [HrPeriod(UFR, date(2005, 9, 1), None)]
    exported = [HrPeriod(UFR, date(2019, 1, 1), date(2025, 12, 31))]
    assert updated_periods(stored, exported, date(2025, 12, 15)) == [
        HrPeriod(UFR, date(2005, 9, 1), date(2025, 12, 31))
    ]


def test_unite_absente_de_l_export_s_arrete_avant_la_fenetre():
    stored = [HrPeriod(UFR, date(2005, 9, 1), None)]
    exported = [HrPeriod(LAB, date(2026, 1, 1), None)]
    assert updated_periods(stored, exported, date(2025, 12, 15)) == [
        HrPeriod(LAB, date(2026, 1, 1), None),
        HrPeriod(UFR, date(2005, 9, 1), date(2025, 12, 14)),
    ]


def test_periode_en_base_commencant_dans_la_fenetre_disparait():
    stored = [HrPeriod(UFR, date(2026, 3, 1), None)]
    assert updated_periods(stored, [], date(2025, 12, 15)) == []


def test_reimport_du_meme_export_est_idempotent():
    exported = [
        HrPeriod(UFR, date(2019, 1, 1), date(2025, 12, 31)),
        HrPeriod(LAB, date(2026, 1, 1), None),
    ]
    window_start = date(2025, 12, 15)
    once = updated_periods([], exported, window_start)
    assert updated_periods(once, exported, window_start) == once
