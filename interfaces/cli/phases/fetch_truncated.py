"""Câblage de la phase `fetch_truncated`."""

from __future__ import annotations

from application.pipeline.context import Phase


def build() -> Phase:
    """Re-télécharge les works OpenAlex tronqués à 100 auteurs.

    L'API OpenAlex plafonne la liste des auteurs à 100 par réponse. La phase repère les lignes staging openalex à 100 auteurs restées `processed=FALSE`, et les re-télécharge en paginant leurs auteurs. Sa position, après `fetch_stale` et avant `normalize`, lui donne à voir les works tronqués que les phases de rattrapage viennent de ramener.

    Séquence et métriques dans `application/pipeline/extract/fetch_truncated.py`.
    """
    from application.pipeline.extract.fetch_truncated import FetchTruncatedPhase
    from infrastructure.sources.openalex.fetch_truncated import PgOpenalexFetchTruncatedAdapter

    return FetchTruncatedPhase(PgOpenalexFetchTruncatedAdapter())
