"""Base class pour les orchestrateurs d'extraction de sources.

Capture le boilerplate commun aux extracteurs : logs de header et de résumé, exécution sous circuit-breaker. Chaque source hérite et implémente `load_config()` et `extract_all()` ; l'itération (cursor / search_after / firstRecord / cursorMark × pages) reste spécifique à chaque source, sans template trop contraignant.

Entry point unique `run()` : invoqué par `run_pipeline.py`, il laisse remonter les exceptions à l'orchestrateur et retourne les `PhaseMetrics`.
"""

from __future__ import annotations

import argparse
import logging
from abc import ABC, abstractmethod
from typing import ClassVar

from sqlalchemy import Connection

from application.pipeline.logging_scope import ScopedOrPlainLogger, scoped_logger
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker

__all__ = ["ExtractLogger", "ExtractionConfigError", "SourceExtractor", "scoped_logger"]


# Le préfixage `[source · scope]` est partagé avec la phase de normalisation : sa
# définition vit dans `application.pipeline.logging_scope`. Ré-exporté ici pour les
# sous-modules d'extraction qui l'importent historiquement depuis `.base`.
ExtractLogger = ScopedOrPlainLogger


class ExtractionConfigError(Exception):
    """Configuration d'extraction incomplète (IDs/affiliations manquants).

    Levée par ``load_config`` d'un extracteur quand un paramètre API
    indispensable (IDs institution, affiliations, PPN…) n'est pas
    disponible. Interrompt l'extraction proprement avec un message
    explicite au lieu d'un 400 API opaque.
    """


class SourceExtractor[ConfigT](ABC):
    """Template pour l'extraction API → staging.

    `ConfigT` (paramètre PEP 695) = type de la config chargée par `load_config`,
    propre à chaque source. Permet aux sous-classes de retourner une dataclass
    typée plutôt qu'un `dict` opaque. Le base class ne consomme jamais le contenu
    de la config — il la passe à `extract_all` qui sait l'interpréter.

    Points d'override obligatoires :
    - `SOURCE` : identifiant source (ex: "hal", "openalex")
    - `load_config(conn) -> dict` : charge la config depuis la DB (URL, auth, affiliations, etc.)
    - `extract_all(args, config) -> PhaseMetrics` : boucle d'extraction

    Points d'override optionnels :
    - `setup_logging(args, config)` : logs de header personnalisés
    - `log_summary(stats, args)` : logs de summary personnalisés
    """

    SOURCE: ClassVar[str] = ""

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
    ) -> None:
        self.conn = conn
        self.logger = logger
        # Circuit-breaker de la source (posé par `run`) : les boucles
        # `extract_all` consultent `_breaker_tripped()` pour s'arrêter quand la
        # source est à bout de budget / en panne.
        self._breaker: CircuitBreaker | None = None

    def _breaker_tripped(self) -> bool:
        """`True` si le circuit-breaker de la source a tripé (à consulter dans les
        boucles d'`extract_all` pour stopper la source)."""
        return self._breaker is not None and self._breaker.tripped

    # ── Hooks métier ────────────────────────────────────────────

    @abstractmethod
    def load_config(self, conn: Connection) -> ConfigT:
        """Charge la config DB (URL, auth, affiliations, années, etc.)."""

    @abstractmethod
    def extract_all(self, args: argparse.Namespace, config: ConfigT) -> PhaseMetrics:
        """Pilote l'extraction complète. Retourne les métriques finales."""

    def setup_logging(  # noqa: B027
        self, args: argparse.Namespace, config: ConfigT
    ) -> None:
        """Logs de header personnalisés (ex: affiliations, collections, années)."""

    def log_summary(self, metrics: PhaseMetrics, args: argparse.Namespace) -> None:
        """Logs de summary. Défaut : `=== Terminé : <as_summary> ===`."""
        self.logger.info(f"=== Terminé : {metrics.as_summary()} ===")

    # ── Entry point ─────────────────────────────────────────────

    def run(
        self,
        args: argparse.Namespace | None = None,
        *,
        breaker: CircuitBreaker | None = None,
    ) -> PhaseMetrics:
        """Exécute l'extraction : `load_config` → `setup_logging` → `extract_all` → `log_summary`.

        Invoqué par `run_pipeline.py`. Les exceptions (`ExtractionConfigError`, HTTP, `KeyboardInterrupt`) remontent à l'orchestrateur, qui décide quoi en faire (rapport partiel, exit code).

        `breaker` : circuit-breaker de la source (posé via la ContextVar par le composition root) ; les boucles `extract_all` le consultent pour stopper une source à bout de budget.
        """
        if args is None:
            args = argparse.Namespace(dry_run=False)
        self._breaker = breaker
        config = self.load_config(self.conn)
        self.logger.info(f"=== Extraction {self.SOURCE} démarrée ===")
        self.setup_logging(args, config)
        metrics = self.extract_all(args, config)
        self.log_summary(metrics, args)
        return metrics
