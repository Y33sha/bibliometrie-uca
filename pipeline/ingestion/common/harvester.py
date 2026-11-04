"""Socle des moissonneurs : patron commun et écriture d'un document dans `staging`.

Le patron gère l'en-tête et le bilan du journal, la barre de progression et l'arrêt sur source indisponible. Chaque source hérite de `SourceHarvester` et implémente `run()`. La pagination reste propre à chaque source.
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
from infrastructure.read_models.perimeters.queries import get_extraction_api_ids
from pipeline.http.circuit_breaker import SourceUnavailableError, trip_source
from pipeline.ingestion.common.pages import Page
from pipeline.ingestion.common.staging import StagingStore
from pipeline.runtime.config import YearRange, window_years
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import (
    BRANCH_CONTINUATION,
    inflect,
    quantity,
    source_branch,
)
from pipeline.runtime.observability.logging_scope import scoped_logger
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
    outcome = StagingStore(conn).stage(source, record, entry_mode=entry_mode)
    if outcome is None:
        return False
    metrics.add(**{outcome.value: 1})
    return True


def stage_pages(
    conn: Connection,
    metrics: PhaseMetrics,
    source: str,
    fetch_page: Callable[[str | None], Page],
    *,
    progress: Progress | None = None,
    keep: Callable[[Mapping[str, JsonValue]], bool] | None = None,
    entry_mode: StagingEntryMode = StagingEntryMode.BULK,
) -> int:
    """Écrit dans `staging` les documents des pages successives, un commit par page, et renvoie le nombre de documents reçus.

    `fetch_page` reçoit le jeton de la page suivante, `None` pour la première. Une page vide ou sans jeton clôt la pagination. `keep` écarte des documents ; `progress` avance d'un pas par document reçu.
    """
    received = 0
    token: str | None = None
    while True:
        page = fetch_page(token)
        for record in page.records:
            if keep is None or keep(record):
                stage_document(conn, metrics, source=source, record=record, entry_mode=entry_mode)
        conn.commit()
        received += len(page.records)
        if progress is not None:
            progress.advance(len(page.records))
        if not page.records or page.next_token is None:
            return received
        token = page.next_token


class HarvestConfigError(Exception):
    """Configuration de moissonnage incomplète : un paramètre indispensable à l'API manque (identifiants d'institution, affiliations, PPN).

    Le moissonneur la lève avant toute requête. La source est alors sautée avec un message explicite.
    """


@dataclass(frozen=True, slots=True)
class HarvestWindow:
    """Bornes d'un moissonnage."""

    years: YearRange | None = None
    """Années du run (`--years`). `None` : années par défaut (`get_years`)."""
    since: str | None = None
    """Date de modification minimale du mode incrémental, au format `YYYY-MM-DD`."""


class SourceHarvester[ClientT](ABC):
    """Patron d'un moissonneur, de l'API de la source vers `staging`.

    `ClientT` est le type du client HTTP de la source, reçu à la construction. Une sous-classe définit `SOURCE` et `run`.
    """

    SOURCE: ClassVar[str] = ""
    MISSING_API_IDS: ClassVar[str] = ""
    """Message d'une source sans identifiant dans le périmètre d'extraction : « aucune affiliation »."""
    DOCUMENT: ClassVar[str] = "document"
    """Nom des éléments rapportés par la source, au singulier."""
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
        """Renvoie les années de publication à moissonner (`window_years`). Le mode incrémental garde ces années."""
        return window_years(self.conn, window.years)

    def _label(self, scope: str | None = None) -> str:
        """Renvoie le libellé de la barre de la source, avec la colonne du périmètre en cours."""
        return source_branch(self.SOURCE, scope)

    def _harvest_by_year(
        self,
        years: list[int],
        count_year: Callable[[int], int],
        harvest_step: Callable[[int, Progress, PhaseMetrics], None],
    ) -> PhaseMetrics:
        """Moissonne les années dans l'ordre sous une seule barre, au libellé réglé sur l'année en cours.

        `count_year` donne le volume d'une année : la barre connaît son total dès le départ. `harvest_step` compte ses écritures dans les métriques reçues. Une coupure laisse sur la barre l'année interrompue, et les précédentes sont terminées.

        Une erreur sur une année est journalisée, la page en cours est annulée, et la boucle passe à l'année suivante. Une source indisponible (`SourceUnavailableError`) arrête la boucle et coupe la source : les années restantes repartent au prochain run. Les métriques des pages écrites sont gardées.
        """
        metrics = PhaseMetrics()
        if not years:
            return metrics
        total = sum(self._count(count_year, year) for year in years)
        with track_progress(total, self._label(str(years[0])), self.logger) as progress:
            for year in years:
                progress.relabel(self._label(str(year)))
                try:
                    harvest_step(year, progress, metrics)
                except SourceUnavailableError:
                    trip_source()
                    break
                except Exception as e:
                    self.conn.rollback()
                    scoped_logger(self.logger, self.SOURCE, str(year)).error(
                        "erreur : %s — passage à l'année suivante", e
                    )
            else:
                year_range = f"{years[0]}-{years[-1]}" if len(years) > 1 else str(years[0])
                progress.relabel(self._label(year_range))
        self._write_summary(metrics)
        return metrics

    @staticmethod
    def _count(count_year: Callable[[int], int], year: int) -> int:
        """Renvoie le volume d'une année, 0 sur une erreur : le moissonnage de l'année rencontre la même erreur et la journalise."""
        try:
            return count_year(year)
        except SourceUnavailableError:
            raise
        except Exception:
            return 0

    def _harvest_at_once(
        self,
        total: int,
        harvest_step: Callable[[Progress], PhaseMetrics],
        *,
        by: str | None = None,
    ) -> PhaseMetrics:
        """Moissonne un périmètre d'un seul tenant sous la barre de la source, puis écrit le bilan."""
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

    def _api_ids(self) -> list[str]:
        """Renvoie les identifiants de la source dans le périmètre d'extraction (`api_ids`).

        Raises:
            HarvestConfigError: le périmètre d'extraction est sans identifiant pour la source.
        """
        ids = get_extraction_api_ids(self.conn, self.SOURCE)
        if not ids:
            raise HarvestConfigError(
                f"{self.MISSING_API_IDS} (api_ids->'{self.SOURCE}' vide pour le périmètre d'extraction)"
            )
        return ids

    @abstractmethod
    def run(self, window: HarvestWindow) -> PhaseMetrics:
        """Moissonne la fenêtre et renvoie les métriques. Une source sans configuration lève `HarvestConfigError`."""


class Harvester(Protocol):
    """Point d'entrée d'un `SourceHarvester`, seul appelé par les orchestrateurs.

    Le protocole efface le paramètre de type de `SourceHarvester`, le client propre à chaque source.
    """

    def run(self, window: HarvestWindow) -> PhaseMetrics: ...


type HarvesterFactory = Callable[[Connection, logging.Logger], Harvester]
"""Construit le moissonneur d'une source sur la connexion de sa phase et le journal de la source."""


def run_harvest(
    ctx: PhaseContext,
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
        signal_source_unconfigured(metrics, source, str(exc), logger=ctx.logger)
        return metrics
