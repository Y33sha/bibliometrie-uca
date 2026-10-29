"""Socle des moissonneurs : patron commun et écriture d'un document dans `staging`.

Le patron gère l'en-tête et le bilan du journal, la barre de progression et l'arrêt sur source indisponible. Chaque source hérite de `SourceHarvester` et implémente `load_config()` et `harvest_all()`. La pagination reste propre à chaque source.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol

from sqlalchemy import Connection

from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue
from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_logger
from pipeline.http.circuit_breaker import SourceUnavailableError, trip_source
from pipeline.ingestion.common.staging import StagingStore, UpsertOutcome
from pipeline.runtime.config import window_years
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import (
    BRANCH_CONTINUATION,
    inflect,
    quantity,
    source_branch,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress, track_progress
from pipeline.runtime.observability.signals import signal_source_unconfigured

__all__ = [
    "HarvestConfigError",
    "Harvester",
    "HarvestWindow",
    "HarvesterFactory",
    "SourceHarvester",
    "run_harvest",
    "stage_document",
]


type Forms = tuple[str, str]
"""Singulier et pluriel d'un mot du bilan."""

_SUMMARY_FORMS: dict[bool, tuple[Forms, Forms, Forms, Forms]] = {
    False: (
        ("trouvé", "trouvés"),
        ("nouveau", "nouveaux"),
        ("mis à jour", "mis à jour"),
        ("inchangé", "inchangés"),
    ),
    True: (
        ("trouvée", "trouvées"),
        ("nouvelle", "nouvelles"),
        ("mise à jour", "mises à jour"),
        ("inchangée", "inchangées"),
    ),
}
"""Mots du bilan d'une source, au masculin puis au féminin."""


def stage_document(
    conn: Connection,
    metrics: PhaseMetrics,
    *,
    source: str,
    record: Mapping[str, JsonValue],
    entry_mode: StagingEntryMode = StagingEntryMode.BULK,
) -> bool:
    """Écrit un document reçu d'une réponse de liste dans `staging` et le compte dans `metrics` : nouveau, mis à jour ou inchangé. Renvoie `False` pour un document sans identifiant, ni écrit ni compté."""
    match StagingStore(conn).stage(source, record, entry_mode=entry_mode):
        case None:
            return False
        case UpsertOutcome.NEW:
            metrics.add(new=1)
        case UpsertOutcome.UPDATED:
            metrics.add(updated=1)
        case UpsertOutcome.UNCHANGED:
            metrics.add(unchanged=1)
    return True


class HarvestConfigError(Exception):
    """Configuration d'extraction incomplète : il manque un paramètre indispensable à l'API (identifiants d'institution, affiliations, PPN).

    `load_config` la lève avant toute requête, et la source est sautée avec un message explicite.
    """


@dataclass(frozen=True, slots=True)
class HarvestWindow:
    """Bornes d'un moissonnage : année de départ, année unique (`--year`), date de modification minimale (mode quotidien).

    `year` prime sur `start_year`. `since`, au format `YYYY-MM-DD`, sert au moissonnage incrémental de HAL et d'OpenAlex.
    """

    start_year: int | None = None
    year: int | None = None
    since: str | None = None


class SourceHarvester[ConfigT, ClientT](ABC):
    """Patron d'un moissonneur, de l'API de la source vers `staging`.

    `ConfigT` est le type de la configuration propre à la source, que `load_config` renvoie et que `harvest_all` reçoit. `ClientT` est le type du client HTTP de la source, reçu à la construction.

    Une sous-classe définit `SOURCE`, `load_config` et `harvest_all`, et peut définir `setup_logging`.
    """

    SOURCE: ClassVar[str] = ""
    DOCUMENT: ClassVar[str] = "document"
    """Nom des éléments que rapporte la source, au singulier."""
    FEMININE: ClassVar[bool] = False
    """Genre de `DOCUMENT`, auquel s'accordent les mots du bilan."""

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        client: ClientT,
    ) -> None:
        self.conn = conn
        self.logger = logger
        self._client = client

    def _years(self, window: HarvestWindow) -> list[int]:
        """Années de publication à moissonner : `--year`, sinon de `start_year` à l'année courante. Le mode incrémental garde cette plage."""
        return window_years(self.conn, start_year=window.start_year, year=window.year)

    def _label(self, scope: str | None = None) -> str:
        """Libellé de la barre de la source, avec la colonne du périmètre en cours."""
        return source_branch(self.SOURCE, scope)

    def _harvest_by_year(
        self,
        years: list[int],
        count_year: Callable[[int], int],
        harvest_step: Callable[[int, Progress], PhaseMetrics],
    ) -> PhaseMetrics:
        """Extrait les années dans l'ordre sous une seule barre, dont le libellé suit l'année en cours.

        `count_year` donne le volume d'une année : la barre connaît son total dès le départ. Une coupure laisse sur la barre l'année interrompue, et les précédentes sont terminées.

        Une source indisponible (`SourceUnavailableError`) arrête la boucle et coupe la source : les années restantes repartent au prochain run, les métriques des années extraites sont gardées.
        """
        metrics = PhaseMetrics()
        if not years:
            return metrics
        total = sum(count_year(year) for year in years)
        with track_progress(total, self._label(str(years[0])), self.logger) as progress:
            for year in years:
                progress.relabel(self._label(str(year)))
                try:
                    metrics.merge(harvest_step(year, progress))
                except SourceUnavailableError:
                    trip_source()
                    break
            else:
                year_range = f"{years[0]}-{years[-1]}" if len(years) > 1 else str(years[0])
                progress.relabel(self._label(year_range))
        self._write_summary(metrics)
        return metrics

    def _harvest_at_once(
        self,
        total: int,
        harvest_step: Callable[[Progress], PhaseMetrics],
        *,
        by: str | None = None,
    ) -> PhaseMetrics:
        """Extrait un périmètre d'un seul tenant sous la barre de la source, puis écrit le bilan."""
        with track_progress(total, self._label(), self.logger) as progress:
            metrics = harvest_step(progress)
        self._write_summary(metrics, by=by)
        return metrics

    def _write_summary(
        self,
        metrics: PhaseMetrics,
        *,
        found: int | None = None,
        by: str | None = None,
    ) -> None:
        """Écrit sous la barre le nombre de documents trouvés, ventilé en nouveaux, mis à jour et inchangés.

        `found` donne le nombre du bilan quand un filtre retient une partie des documents parcourus. `by` nomme le critère de recherche : « trouvés par ORCID ».
        """
        found_form, new_form, updated_form, unchanged_form = _SUMMARY_FORMS[self.FEMININE]
        n = metrics.total if found is None else found
        self.logger.info(
            "%s%s %s%s : %s, %s, %s",
            BRANCH_CONTINUATION,
            quantity(n, self.DOCUMENT),
            inflect(n, *found_form),
            f" par {by}" if by else "",
            quantity(metrics.new, *new_form),
            quantity(metrics.updated, *updated_form),
            quantity(metrics.unchanged, *unchanged_form),
        )

    @abstractmethod
    def load_config(self, conn: Connection) -> ConfigT:
        """Charge depuis la base la configuration propre à la source."""

    @abstractmethod
    def harvest_all(self, window: HarvestWindow, config: ConfigT) -> PhaseMetrics:
        """Moissonne la fenêtre et renvoie les métriques."""

    def setup_logging(  # noqa: B027
        self, window: HarvestWindow, config: ConfigT
    ) -> None:
        """Écrit l'en-tête du journal propre à la source : affiliations, collections, années."""

    def run(self, window: HarvestWindow) -> PhaseMetrics:
        """Charge la configuration, écrit l'en-tête du journal, puis moissonne. Les exceptions remontent à l'appelant."""
        config = self.load_config(self.conn)
        self.setup_logging(window, config)
        return self.harvest_all(window, config)


class Harvester(Protocol):
    """Point d'entrée d'un `SourceHarvester`, seul que les orchestrateurs appellent.

    Le protocole efface les paramètres de type de `SourceHarvester`, la configuration et le client propres à chaque source.
    """

    def run(self, window: HarvestWindow) -> PhaseMetrics: ...


type HarvesterFactory = Callable[[Connection, logging.Logger], Harvester]
"""Construit le moissonneur d'une source sur la connexion de sa phase et le journal de la source."""


def run_harvest(
    ctx: PhaseContext,
    phase: str,
    source: str,
    make_harvester: HarvesterFactory,
    window: HarvestWindow,
) -> PhaseMetrics:
    """Exécute le moissonneur d'une source sur une connexion de la phase, avec le journal de la source.

    Une source sans configuration (`HarvestConfigError`) est sautée avec un signal `source_unconfigured` ; la phase continue avec les autres sources.
    """
    source_log = setup_logger(source, str(PROJECT_ROOT / "logs"))
    try:
        with ctx.open_tx() as conn:
            return make_harvester(conn, source_log).run(window)
    except HarvestConfigError as exc:
        metrics = PhaseMetrics()
        signal_source_unconfigured(metrics, source, str(exc), logger=ctx.logger, phase=phase)
        return metrics
