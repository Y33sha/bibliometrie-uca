"""Câblage de la phase `fetch_truncated`."""

from __future__ import annotations

from interfaces.cli.phases.execution import UnderCircuitBreaker
from pipeline.context import Phase


def build() -> Phase:
    """Relit les works OpenAlex tronqués à 100 auteurs, sous le circuit-breaker d'OpenAlex.

    Séquence et métriques dans `pipeline/sources/openalex/fetch_truncated.py`.
    """
    from pipeline.sources.openalex.fetch_truncated import FetchTruncatedPhase

    return UnderCircuitBreaker("openalex", FetchTruncatedPhase())
