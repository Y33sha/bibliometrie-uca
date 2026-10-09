"""Câblage de la phase `countries`."""

from __future__ import annotations

from application.pipeline.context import Phase


def build() -> Phase:
    """Détection des pays des adresses et recalcul sur les publications.

    Séquence, transactions et métriques dans `application/pipeline/countries/phase.py`.
    """
    from application.pipeline.countries.phase import CountriesPhase
    from infrastructure.pipeline.countries import PgCountryQueries

    return CountriesPhase(PgCountryQueries())
