"""Base class pour les extracteurs de sources.

Capture le boilerplate commun aux 5 extractors :
- parsing CLI
- cycle connexion (ouverture, config loading, close)
- chargement de `existing_ids` en staging
- gestion des exceptions (HTTPError → log + exit 1, KeyboardInterrupt → log + exit 0)
- logs de header + summary

Chaque source hérite et implémente `load_config()` + `extract_all()`.
L'itération (cursor / search_after / firstRecord / collections × pages)
reste spécifique à chaque source — pas de template trop contraignant.
"""

from __future__ import annotations

import argparse
import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import requests
from sqlalchemy import Connection

from infrastructure.db.engine import get_sync_engine
from infrastructure.sources.common import get_existing_ids


class ExtractionConfigError(Exception):
    """Configuration d'extraction incomplète (IDs/affiliations manquants).

    Levée par ``load_config`` d'un extracteur quand un paramètre API
    indispensable (IDs institution, affiliations, PPN…) n'est pas
    disponible. Interrompt l'extraction proprement avec un message
    explicite au lieu d'un 400 API opaque.
    """


class ExtractionStats:
    """Résultat d'une extraction. Les sources peuvent étendre/customiser."""

    def __init__(self, new: int = 0, updated: int = 0, total: int = 0) -> None:
        self.new = new
        self.updated = updated
        self.total = total

    def add(self, new: int = 0, updated: int = 0, total: int = 0) -> None:
        self.new += new
        self.updated += updated
        self.total += total


class SourceExtractor(ABC):
    """Template pour l'extraction API → staging.

    Points d'override obligatoires :
    - `SOURCE` : identifiant source (ex: "hal", "openalex")
    - `DESCRIPTION` : description CLI
    - `load_config(conn) -> dict` : charge la config depuis la DB (URL, auth, affiliations, etc.)
    - `extract_all(args, config, existing_ids) -> ExtractionStats` : boucle d'extraction

    Points d'override optionnels :
    - `add_cli_args(parser)` : args spécifiques au-delà de --dry-run
    - `setup_logging(args, config)` : logs de header personnalisés
    - `log_summary(stats, args)` : logs de summary personnalisés
    """

    SOURCE: ClassVar[str] = ""
    DESCRIPTION: ClassVar[str] = ""

    def __init__(self, conn: Connection, logger: logging.Logger) -> None:
        self.conn = conn
        self.logger = logger

    # ── Hooks métier ────────────────────────────────────────────

    @abstractmethod
    def load_config(self, conn: Connection) -> dict[str, Any]:
        """Charge la config DB (URL, auth, affiliations, années, etc.)."""

    @abstractmethod
    def extract_all(
        self, args: argparse.Namespace, config: dict[str, Any], existing_ids: set
    ) -> ExtractionStats:
        """Pilote l'extraction complète. Retourne les stats finales."""

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:  # noqa: B027
        """Ajoute les args CLI spécifiques à la source (au-delà de --dry-run)."""

    def setup_logging(  # noqa: B027
        self, args: argparse.Namespace, config: dict[str, Any]
    ) -> None:
        """Logs de header personnalisés (ex: affiliations, collections, années)."""

    def log_summary(self, stats: ExtractionStats, args: argparse.Namespace) -> None:
        """Logs de summary. Défaut : `=== Terminé : X nouveaux, Y mis à jour ===`."""
        parts = [f"{stats.new} nouveaux"]
        if stats.updated:
            parts.append(f"{stats.updated} mis à jour")
        self.logger.info(f"=== Terminé : {', '.join(parts)} ===")

    # ── Template method ────────────────────────────────────────

    def parse_args(self, argv: list[str] | None = None) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description=self.DESCRIPTION)
        parser.add_argument("--dry-run", action="store_true", help="Compter sans insérer")
        self.add_cli_args(parser)
        return parser.parse_args(argv)

    def run(self, argv: list[str] | None = None) -> None:
        """Entry point : parse, load config, extract, handle errors, close."""
        args = self.parse_args(argv)

        try:
            config = self.load_config(self.conn)
        except ExtractionConfigError as e:
            self.logger.error(f"Extraction {self.SOURCE} interrompue : {e}")
            self.conn.close()
            sys.exit(2)

        self.logger.info(f"=== Extraction {self.SOURCE} démarrée ===")
        self.setup_logging(args, config)

        try:
            existing_ids = get_existing_ids(self.conn, self.SOURCE) if not args.dry_run else set()
            self.logger.info(f"{len(existing_ids)} documents déjà en staging")

            stats = self.extract_all(args, config, existing_ids)
            self.log_summary(stats, args)

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


def run_extractor(cls: type[SourceExtractor], logger: logging.Logger) -> None:
    """Helper pour les entry points : instancie et lance."""
    conn = get_sync_engine().connect()
    cls(conn, logger).run()
