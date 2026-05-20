"""Base class pour les orchestrateurs d'extraction de sources.

Capture le boilerplate commun aux 5 extractors :
- parsing CLI
- chargement de `existing_ids` en staging (via `StagingQueries` port)
- gestion des exceptions (HTTPError → log + exit 1, KeyboardInterrupt → log + exit 0)
- logs de header + summary

Chaque source hérite et implémente `load_config()` + `extract_all()`. L'itération
(cursor / search_after / firstRecord / collections × pages) reste spécifique à
chaque source — pas de template trop contraignant.

Deux entry points :
- `run(argv)` : CLI standalone, gère exit codes et logs d'erreur.
- `run_as_phase()` : depuis `run_pipeline.py`, lève les exceptions à
  l'orchestrateur et retourne `PhaseMetrics`.

Le wiring du `StagingQueries` (adapter PostgreSQL) est de la responsabilité
du composition root (CLI ou run_pipeline) — l'orchestrateur ne connaît
que le Protocol.
"""

from __future__ import annotations

import argparse
import logging
import sys
from abc import ABC, abstractmethod
from typing import ClassVar, Generic, TypeVar

import requests
from sqlalchemy import Connection

from application.ports.pipeline.staging import StagingQueries
from domain.pipeline_metrics import PhaseMetrics

ConfigT = TypeVar("ConfigT")
"""Type de la config chargée par `load_config`, propre à chaque source.

Permet aux sous-classes de retourner une dataclass typée plutôt qu'un
`dict[str, Any]` opaque. Le base class ne consomme jamais le contenu
de la config — il la passe à `extract_all` qui sait l'interpréter.
"""


class ExtractionConfigError(Exception):
    """Configuration d'extraction incomplète (IDs/affiliations manquants).

    Levée par ``load_config`` d'un extracteur quand un paramètre API
    indispensable (IDs institution, affiliations, PPN…) n'est pas
    disponible. Interrompt l'extraction proprement avec un message
    explicite au lieu d'un 400 API opaque.
    """


class SourceExtractor(ABC, Generic[ConfigT]):
    """Template pour l'extraction API → staging.

    Points d'override obligatoires :
    - `SOURCE` : identifiant source (ex: "hal", "openalex")
    - `DESCRIPTION` : description CLI
    - `load_config(conn) -> dict` : charge la config depuis la DB (URL, auth, affiliations, etc.)
    - `extract_all(args, config, existing_ids) -> PhaseMetrics` : boucle d'extraction

    Points d'override optionnels :
    - `add_cli_args(parser)` : args spécifiques au-delà de --dry-run
    - `setup_logging(args, config)` : logs de header personnalisés
    - `log_summary(stats, args)` : logs de summary personnalisés
    """

    SOURCE: ClassVar[str] = ""
    DESCRIPTION: ClassVar[str] = ""

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging: StagingQueries,
    ) -> None:
        self.conn = conn
        self.logger = logger
        self._staging = staging

    # ── Hooks métier ────────────────────────────────────────────

    @abstractmethod
    def load_config(self, conn: Connection) -> ConfigT:
        """Charge la config DB (URL, auth, affiliations, années, etc.)."""

    @abstractmethod
    def extract_all(
        self, args: argparse.Namespace, config: ConfigT, existing_ids: set[str]
    ) -> PhaseMetrics:
        """Pilote l'extraction complète. Retourne les métriques finales."""

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:  # noqa: B027
        """Ajoute les args CLI spécifiques à la source (au-delà de --dry-run)."""

    def setup_logging(  # noqa: B027
        self, args: argparse.Namespace, config: ConfigT
    ) -> None:
        """Logs de header personnalisés (ex: affiliations, collections, années)."""

    def log_summary(self, metrics: PhaseMetrics, args: argparse.Namespace) -> None:
        """Logs de summary. Défaut : `=== Terminé : <as_summary> ===`."""
        self.logger.info(f"=== Terminé : {metrics.as_summary()} ===")

    # ── Entry point pipeline (imports) ──────────────────────────

    def run_as_phase(self, args: argparse.Namespace | None = None) -> PhaseMetrics:
        """Variante non-CLI : pas de sys.exit, laisse remonter les exceptions.

        Utilisée par `run_pipeline.py` quand la phase est invoquée par
        import direct. Les exceptions (`ExtractionConfigError`, HTTP,
        `KeyboardInterrupt`) remontent à l'orchestrateur qui décide quoi
        en faire (rapport partiel, exit code).
        """
        if args is None:
            args = argparse.Namespace(dry_run=False)
        config = self.load_config(self.conn)
        self.logger.info(f"=== Extraction {self.SOURCE} démarrée ===")
        self.setup_logging(args, config)
        existing_ids = (
            self._staging.fetch_existing_source_ids(self.conn, self.SOURCE)
            if not args.dry_run
            else set()
        )
        self.logger.info(f"{len(existing_ids)} documents déjà en staging")
        metrics = self.extract_all(args, config, existing_ids)
        self.log_summary(metrics, args)
        return metrics

    # ── Entry point CLI (subprocess / standalone) ──────────────

    def parse_args(self, argv: list[str] | None = None) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description=self.DESCRIPTION)
        parser.add_argument("--dry-run", action="store_true", help="Compter sans insérer")
        self.add_cli_args(parser)
        return parser.parse_args(argv)

    def run(self, argv: list[str] | None = None) -> None:
        """Entry point CLI : parse, run_as_phase, exit codes."""
        args = self.parse_args(argv)
        try:
            self.run_as_phase(args)
        except ExtractionConfigError as e:
            self.logger.error(f"Extraction {self.SOURCE} interrompue : {e}")
            sys.exit(2)
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Erreur API : {e}")
            if e.response is not None:
                self.logger.error(f"Réponse : {e.response.text[:500]}")
            sys.exit(1)
        except KeyboardInterrupt:
            self.logger.warning(
                "Interruption utilisateur — les données déjà insérées sont conservées."
            )
            sys.exit(0)
        finally:
            self.conn.close()
