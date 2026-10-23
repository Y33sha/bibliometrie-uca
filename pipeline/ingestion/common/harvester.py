"""Socle des moissonneurs : patron commun, écriture d'un document dans `staging`.

Le patron porte l'en-tête et le bilan du journal, la barre de progression et l'arrêt sur source indisponible. Chaque source hérite de `SourceHarvester` et implémente `load_config()` et `harvest_all()` ; la pagination (curseur, `search_after`, `firstRecord`, `cursorMark`) reste propre à chaque source.

Point d'entrée unique `run()` : invoqué par `run_pipeline`, il laisse remonter les exceptions à l'orchestrateur et retourne les `PhaseMetrics`.
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
from pipeline.runtime.config import get_years
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import (
    BRANCH_CONTINUATION,
    inflect,
    quantity,
    source_branch,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress, track_progress

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
    """Écrit un document reçu d'une réponse de liste dans `staging` et le compte dans `metrics` : nouveau, mis à jour ou inchangé. Rend `False` pour un document sans identifiant, ni écrit ni compté."""
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
    """Configuration d'extraction incomplète (IDs/affiliations manquants).

    Levée par `load_config` d'un moissonneur quand un paramètre API
    indispensable (IDs institution, affiliations, PPN…) n'est pas
    disponible. Interrompt l'extraction proprement avec un message
    explicite au lieu d'un 400 API opaque.
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
    """Template pour l'extraction API → staging.

    `ConfigT` (paramètre PEP 695) = type de la config chargée par `load_config`, propre à chaque source. Permet aux sous-classes de retourner une dataclass typée plutôt qu'un `dict` opaque. Le base class ne consomme jamais le contenu de la config — il la passe à `harvest_all` qui sait l'interpréter.

    `ClientT` (paramètre PEP 695) = type du client HTTP de la source, injecté à la construction et stocké en `self._client`.

    Points d'override obligatoires :
    - `SOURCE` : identifiant source (ex: "hal", "openalex")
    - `load_config(conn) -> ConfigT` : charge la config depuis la DB (URL, auth, affiliations, etc.)
    - `harvest_all(window, config) -> PhaseMetrics` : boucle d'extraction

    Points d'override optionnels :
    - `setup_logging(window, config)` : logs de header personnalisés
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
        """Années de publication à extraire : `--year`, sinon `[start_year … année courante]` (`get_years`). Le mode incrémental garde cette plage."""
        return [window.year] if window.year else get_years(self.conn, start_year=window.start_year)

    # ── Barre et bilan de la source ─────────────────────────────

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

    # ── Hooks métier ────────────────────────────────────────────

    @abstractmethod
    def load_config(self, conn: Connection) -> ConfigT:
        """Charge la config DB (URL, auth, affiliations, années, etc.)."""

    @abstractmethod
    def harvest_all(self, window: HarvestWindow, config: ConfigT) -> PhaseMetrics:
        """Pilote l'extraction complète. Retourne les métriques finales."""

    def setup_logging(  # noqa: B027
        self, window: HarvestWindow, config: ConfigT
    ) -> None:
        """Logs de header personnalisés (ex: affiliations, collections, années)."""

    # ── Entry point ─────────────────────────────────────────────

    def run(self, window: HarvestWindow) -> PhaseMetrics:
        """Exécute l'extraction : `load_config` → `setup_logging` → `harvest_all`.

        Invoqué par `run_pipeline`. Les exceptions (`HarvestConfigError`, HTTP, `KeyboardInterrupt`) remontent à l'orchestrateur, qui décide quoi en faire (rapport partiel, exit code).
        """
        config = self.load_config(self.conn)
        self.setup_logging(window, config)
        return self.harvest_all(window, config)


class Harvester(Protocol):
    """Point d'entrée d'un `SourceHarvester`, seul que les orchestrateurs appellent.

    Le protocole efface les paramètres de type de `SourceHarvester`, la configuration et le client propres à chaque source.
    """

    def run(self, window: HarvestWindow) -> PhaseMetrics: ...


type HarvesterFactory = Callable[[Connection, logging.Logger], Harvester]
"""Construit le moissonneur d'une source sur la connexion de sa phase et le journal scopé à la source."""


def run_harvest(
    ctx: PhaseContext, source: str, make_harvester: HarvesterFactory, window: HarvestWindow
) -> PhaseMetrics:
    """Exécute le moissonneur de `make_harvester` sur une connexion de la phase, avec le journal de la source."""
    source_log = setup_logger(source, str(PROJECT_ROOT / "logs"))
    with ctx.open_tx() as conn:
        return make_harvester(conn, source_log).run(window)
