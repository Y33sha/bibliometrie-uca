"""Périodes de présence d'une personne dans une unité, d'après les exports RH : fusion, mise à jour par un export."""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from itertools import groupby

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class HrPeriod:
    """Période de présence dans une unité. Une date absente est une borne ouverte."""

    unit_label: str
    start: date | None
    end: date | None


def _start_key(period: HrPeriod) -> date:
    return period.start or date.min


def _continues(current: HrPeriod, following: HrPeriod) -> bool:
    """Vrai quand `following`, de début postérieur ou égal, chevauche `current` ou commence le lendemain de sa fin."""
    if current.end is None or following.start is None:
        return True
    return following.start <= current.end + _ONE_DAY


def merge_periods(periods: Iterable[HrPeriod]) -> list[HrPeriod]:
    """Fusionne les périodes d'une même unité qui se chevauchent ou se suivent. Renvoie les périodes triées par unité et par début."""
    merged: list[HrPeriod] = []
    ordered = sorted(periods, key=lambda p: (p.unit_label, _start_key(p)))
    for _, unit_periods in groupby(ordered, key=lambda p: p.unit_label):
        current: HrPeriod | None = None
        for period in unit_periods:
            if current is None:
                current = period
            elif _continues(current, period):
                end = (
                    None
                    if current.end is None or period.end is None
                    else max(current.end, period.end)
                )
                current = replace(current, end=end)
            else:
                merged.append(current)
                current = period
        if current is not None:
            merged.append(current)
    return merged


def updated_periods(
    stored: Iterable[HrPeriod], exported: Iterable[HrPeriod], window_start: date
) -> list[HrPeriod]:
    """Renvoie les périodes d'une personne après un export, qui fait foi à partir du début de sa fenêtre d'observation.

    Les périodes en base s'arrêtent la veille de `window_start`. Les périodes de l'export s'ajoutent, puis les périodes d'une même unité fusionnent.
    """
    day_before = window_start - _ONE_DAY
    kept = [
        replace(p, end=day_before if p.end is None else min(p.end, day_before))
        for p in stored
        if p.start is None or p.start < window_start
    ]
    return merge_periods([*kept, *exported])
