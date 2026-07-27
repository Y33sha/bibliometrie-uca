"""Base des normaliseurs de sources bibliographiques.

Étend `SourceNormalizer` avec la plomberie commune aux sources qui alimentent les référentiels journal, éditeur et publication (crossref, datacite, scanr, hal, openalex, wos) : les factories de repository, instanciées au `preload_caches` quand la connexion est prête, et un accès typé garanti chargé. Chaque source concrète n'implémente que `process_work`, qui délègue à sa logique de normalisation propre.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.normalize.base import SourceNormalizer
from application.ports.pipeline.journals import JournalFindOrCreateQueries
from application.ports.pipeline.normalize.authorships import AuthorshipsBatchQueries
from application.ports.pipeline.normalize.source_publications import SourcePublicationQueries
from application.ports.pipeline.normalize.staging import StagingQueries
from application.ports.pipeline.publishers import PublisherFindOrCreateQueries
from application.ports.repositories.publication_repository import PublicationRepository


class BibliographicNormalizer(SourceNormalizer):
    """Normaliseur d'une source bibliographique : `SourceNormalizer` doté des repositories journal / éditeur / publication."""

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: SourcePublicationQueries,
        journal_repo_factory: Callable[[Connection], JournalFindOrCreateQueries],
        publisher_repo_factory: Callable[[Connection], PublisherFindOrCreateQueries],
        publication_repo_factory: Callable[[Connection], PublicationRepository],
        authorship_queries: AuthorshipsBatchQueries,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._journal_repo_factory = journal_repo_factory
        self._journal_repo: JournalFindOrCreateQueries | None = None
        self._publisher_repo_factory = publisher_repo_factory
        self._publisher_repo: PublisherFindOrCreateQueries | None = None
        self._publication_repo_factory = publication_repo_factory
        self._publication_repo: PublicationRepository | None = None
        self._authorship_queries = authorship_queries

    def preload_caches(self, conn: Connection) -> None:
        """Instancie les repositories sur la connexion prête, une fois avant la boucle de traitement."""
        self._journal_repo = self._journal_repo_factory(conn)
        self._publisher_repo = self._publisher_repo_factory(conn)
        self._publication_repo = self._publication_repo_factory(conn)

    def _require_repos(
        self,
    ) -> tuple[JournalFindOrCreateQueries, PublisherFindOrCreateQueries, PublicationRepository]:
        """Les trois repositories, garantis chargés par `preload_caches`."""
        assert (
            self._journal_repo is not None
            and self._publisher_repo is not None
            and self._publication_repo is not None
        ), "preload_caches doit être appelé avant process_work"
        return self._journal_repo, self._publisher_repo, self._publication_repo
