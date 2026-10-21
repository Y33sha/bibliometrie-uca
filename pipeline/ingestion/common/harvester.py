"""Socle des moissonneurs : patron commun, écriture d'un document dans `staging`.

Le patron porte l'en-tête et le bilan du journal, la barre de progression et l'arrêt sur circuit-breaker. Chaque source hérite de `SourceHarvester` et implémente `load_config()` et `harvest_all()` ; la pagination (curseur, `search_after`, `firstRecord`, `cursorMark`) reste propre à chaque source.

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
from pipeline.http.circuit_breaker import SourceCircuitBreaker, SourceUnavailableError
from pipeline.ingestion.common.staging import UpsertOutcome, upsert_staging
from pipeline.runtime.config import get_years
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
    "stage_document",
]


type Formes = tuple[str, str]
"""Singulier et pluriel d'un mot du bilan."""

_FORMES_DU_BILAN: dict[bool, tuple[Formes, Formes, Formes, Formes]] = {
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
    source_id: str,
    doi: str | None,
    raw_data: Mapping[str, JsonValue],
    authors_truncated: bool = False,
    entry_mode: StagingEntryMode = StagingEntryMode.BULK,
) -> None:
    """Écrit un document dans `staging` et le compte dans `metrics` : nouveau, mis à jour ou inchangé."""
    inserted, changed = upsert_staging(
        conn,
        source=source,
        source_id=source_id,
        doi=doi,
        raw_data=raw_data,
        authors_truncated=authors_truncated,
        entry_mode=entry_mode,
    )
    match UpsertOutcome.of(inserted=inserted, changed=changed):
        case UpsertOutcome.NEW:
            metrics.add(new=1)
        case UpsertOutcome.UPDATED:
            metrics.add(updated=1)
        case UpsertOutcome.UNCHANGED:
            metrics.add(unchanged=1)


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
    FEMININ: ClassVar[bool] = False
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
        # Circuit-breaker de la source (posé par `run`) : les boucles `harvest_all` consultent `_breaker_tripped()` pour s'arrêter quand la source est à bout de budget / en panne.
        self._breaker: SourceCircuitBreaker | None = None

    def _years(self, window: HarvestWindow) -> list[int]:
        """Années de publication à extraire : `--year`, sinon `[start_year … année courante]` (`get_years`). Le mode incrémental garde cette plage."""
        return [window.year] if window.year else get_years(self.conn, start_year=window.start_year)

    def _breaker_tripped(self) -> bool:
        """`True` si le circuit-breaker de la source a tripé (à consulter dans les boucles d'`harvest_all` pour stopper la source)."""
        return self._breaker is not None and self._breaker.tripped

    def _stop_on_tripped(self, remaining: str) -> bool:
        """`True`, avec avertissement, si le circuit-breaker a tripé : à tester en tête de boucle d'items pour stopper la source. `remaining` nomme les items non traités (accordé par l'appelant), qui repartent au prochain run."""
        if self._breaker_tripped():
            self._warn_stopped(remaining)
            return True
        return False

    def _warn_stopped(self, remaining: str) -> None:
        self.logger.warning(
            "%s à bout (429/5xx répétés) — %s (retry au prochain run)", self.SOURCE, remaining
        )

    # ── Barre et bilan de la source ─────────────────────────────

    def _label(self, scope: str | None = None) -> str:
        """Libellé de la barre de la source, avec la colonne du périmètre en cours."""
        return source_branch(self.SOURCE, scope)

    def _extrait_par_annee(
        self,
        annees: list[int],
        compte: Callable[[int], int],
        extrait: Callable[[int, Progress], PhaseMetrics],
    ) -> PhaseMetrics:
        """Extrait les années dans l'ordre sous une seule barre, dont le libellé suit l'année en cours.

        `compte` donne le volume d'une année : la barre connaît son total dès le départ. Une coupure laisse sur la barre l'année interrompue, et les précédentes sont terminées.

        Une source indisponible (`SourceUnavailableError`) arrête la boucle : les années restantes repartent au prochain run, les métriques des années extraites sont gardées.
        """
        metrics = PhaseMetrics()
        if not annees:
            return metrics
        total = sum(compte(annee) for annee in annees)
        with track_progress(total, self._label(str(annees[0])), self.logger) as progress:
            for i, annee in enumerate(annees):
                restantes = annees[i:]
                sautees = (
                    f"{inflect(len(restantes), 'année')} {', '.join(map(str, restantes))} "
                    f"{inflect(len(restantes), 'sautée')}"
                )
                if self._stop_on_tripped(sautees):
                    break
                progress.relabel(self._label(str(annee)))
                try:
                    metrics.merge(extrait(annee, progress))
                except SourceUnavailableError:
                    self._warn_stopped(sautees)
                    break
            else:
                plage = f"{annees[0]}-{annees[-1]}" if len(annees) > 1 else str(annees[0])
                progress.relabel(self._label(plage))
        self._ecrit_bilan(metrics)
        return metrics

    def _extrait_d_un_tenant(
        self,
        total: int,
        extrait: Callable[[Progress], PhaseMetrics],
        *,
        par: str | None = None,
    ) -> PhaseMetrics:
        """Extrait un périmètre d'un seul tenant sous la barre de la source, puis écrit le bilan."""
        with track_progress(total, self._label(), self.logger) as progress:
            metrics = extrait(progress)
        self._ecrit_bilan(metrics, par=par)
        return metrics

    def _ecrit_bilan(
        self,
        metrics: PhaseMetrics,
        *,
        trouves: int | None = None,
        par: str | None = None,
    ) -> None:
        """Écrit sous la barre le nombre de documents trouvés, ventilé en nouveaux, mis à jour et inchangés.

        `trouves` donne le nombre du bilan quand un filtre retient une partie des documents parcourus. `par` nomme le critère de recherche : « trouvés par ORCID ».
        """
        trouve, nouveau, mis_a_jour, inchange = _FORMES_DU_BILAN[self.FEMININ]
        n = metrics.total if trouves is None else trouves
        self.logger.info(
            "%s%s %s%s : %s, %s, %s",
            BRANCH_CONTINUATION,
            quantity(n, self.DOCUMENT),
            inflect(n, *trouve),
            f" par {par}" if par else "",
            quantity(metrics.new, *nouveau),
            quantity(metrics.updated, *mis_a_jour),
            quantity(metrics.unchanged, *inchange),
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

    def run(
        self,
        window: HarvestWindow,
        *,
        breaker: SourceCircuitBreaker | None = None,
    ) -> PhaseMetrics:
        """Exécute l'extraction : `load_config` → `setup_logging` → `harvest_all`.

        Invoqué par `run_pipeline`. Les exceptions (`HarvestConfigError`, HTTP, `KeyboardInterrupt`) remontent à l'orchestrateur, qui décide quoi en faire (rapport partiel, exit code).

        `breaker` : circuit-breaker de la source (posé via la ContextVar par le composition root) ; les boucles `harvest_all` le consultent pour stopper une source à bout de budget.
        """
        self._breaker = breaker
        config = self.load_config(self.conn)
        self.setup_logging(window, config)
        return self.harvest_all(window, config)


class Harvester(Protocol):
    """Point d'entrée d'un `SourceHarvester`, seul que les orchestrateurs appellent.

    Le protocole efface les paramètres de type de `SourceHarvester`, la configuration et le client propres à chaque source.
    """

    def run(
        self,
        window: HarvestWindow,
        *,
        breaker: SourceCircuitBreaker | None = None,
    ) -> PhaseMetrics: ...


type HarvesterFactory = Callable[[Connection, logging.Logger], Harvester]
"""Construit le moissonneur d'une source sur la connexion de sa phase et le journal scopé à la source."""
