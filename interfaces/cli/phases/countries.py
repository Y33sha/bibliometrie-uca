"""Câblage de la phase `countries`."""

from __future__ import annotations

from pipeline.context import Phase


def build() -> Phase:
    """Détection des pays des adresses et recalcul sur les publications.

    Séquence, transactions et métriques dans `pipeline/structures/countries.py`.
    """
    from pipeline.structures.countries import CountriesPhase
    from pipeline.structures.countries_queries import CountryQueries

    return CountriesPhase(CountryQueries())
