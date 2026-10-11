"""Câblage de la phase `fetch_truncated`."""

from __future__ import annotations

from interfaces.cli.phases.execution import UnderCircuitBreaker
from pipeline.context import Phase


def build() -> Phase:
    """Re-télécharge les works OpenAlex tronqués à 100 auteurs.

    L'API OpenAlex plafonne la liste des auteurs à 100 par réponse de liste. La phase repère les lignes staging openalex marquées `authors_truncated` à l'extraction, et les re-télécharge une à une par `/works/{id}`, qui rend tous les auteurs. Elle tourne sous le circuit-breaker d'OpenAlex.

    Séquence et métriques dans `application/pipeline/fetch_truncated/phase.py`.
    """
    from application.pipeline.fetch_truncated.phase import FetchTruncatedPhase
    from infrastructure.sources.openalex.fetch_truncated import PgOpenalexFetchTruncatedAdapter

    return UnderCircuitBreaker("openalex", FetchTruncatedPhase(PgOpenalexFetchTruncatedAdapter()))
