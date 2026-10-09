"""Câblage de la phase `affiliations`."""

from __future__ import annotations

from application.pipeline.context import Phase
from application.pipeline.metrics import PhaseMetrics
from interfaces.cli.phases.execution import log, open_tx


def build() -> Phase:
    """Rattachement des signatures aux structures du périmètre, par leurs adresses.

    Séquence, transactions et métriques dans `application/pipeline/affiliations/phase.py`.
    """
    from application.pipeline.affiliations.phase import AffiliationsPhase
    from infrastructure.pipeline.affiliations.address_resolution import (
        PgAddressResolutionQueries,
    )
    from infrastructure.pipeline.affiliations.in_perimeter import PgAffiliationsQueries
    from infrastructure.pipeline.perimeter import PgPerimeterStructuresQueries

    return AffiliationsPhase(
        PgAddressResolutionQueries(),
        PgAffiliationsQueries(),
        PgPerimeterStructuresQueries(),
        refresh_ror=_run_refresh_ror,
    )


def _run_refresh_ror() -> PhaseMetrics:
    """Rafraîchissement du référentiel ROR depuis le dump publié sur Zenodo, sur sa propre connexion."""
    from application.pipeline.affiliations.refresh_ror import run_refresh_ror
    from infrastructure.repositories import ror_repository
    from infrastructure.sources.config import get_polite_pool_email_optional
    from infrastructure.sources.polite_pool import build_user_agent
    from infrastructure.sources.ror.dump import ZenodoRorDumpSource

    # Le dump est public : l'adresse du polite pool y est facultative.
    source = ZenodoRorDumpSource(
        user_agent=build_user_agent(get_polite_pool_email_optional() or ""), logger=log
    )
    with open_tx() as conn:
        return run_refresh_ror(conn, source=source, repo=ror_repository(conn), logger=log)
