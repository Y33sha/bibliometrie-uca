"""Modes d'exécution du pipeline (`MODES`) : chacun fixe les sources moissonnées, la fenêtre du moissonnage et les opérations coûteuses du run."""

from dataclasses import dataclass

from domain.sources.registry import HARVESTED_SOURCES, PROFILES


@dataclass(frozen=True)
class ModePolicy:
    """Politique d'un mode d'exécution."""

    harvest_sources: frozenset[str]
    """Sources moissonnées par le mode. Une source sur option s'ajoute seulement avec `--include-wos`."""
    incremental: bool
    """Le moissonnage retient les documents modifiés depuis le dernier moissonnage quotidien réussi."""
    vacuum_full: bool
    """Les `VACUUM` de la maintenance des tables deviennent des `VACUUM FULL` : la table est réécrite, et l'espace libéré revient au système."""
    fetch_stale: bool
    """La phase `fetch_stale` réinterroge un à un les enregistrements sources non revus par le moissonnage."""
    harvest_by_person: bool
    """La phase `harvest_by_person` moissonne les sources par l'identifiant des personnes RH."""
    hal_theses_by_nnt: bool
    """La phase `fetch_missing` cherche dans HAL, par NNT, les thèses de theses.fr sans document HAL."""
    refresh_hal_structures: bool
    """Le référentiel des structures HAL recharge aussi les structures connues, sinon seulement les absentes."""


MODES: dict[str, ModePolicy] = {
    "daily": ModePolicy(
        harvest_sources=frozenset(s for s in HARVESTED_SOURCES if PROFILES[s].incremental),
        incremental=True,
        vacuum_full=False,
        fetch_stale=False,
        harvest_by_person=False,
        hal_theses_by_nnt=False,
        refresh_hal_structures=False,
    ),
    "full": ModePolicy(
        harvest_sources=frozenset(HARVESTED_SOURCES),
        incremental=False,
        vacuum_full=True,
        fetch_stale=True,
        harvest_by_person=True,
        hal_theses_by_nnt=True,
        refresh_hal_structures=True,
    ),
}

MODE_NAMES: tuple[str, ...] = tuple(MODES.keys())
