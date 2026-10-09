"""Câblage de la phase `normalize`."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from application.pipeline.context import Phase, PhaseContext
from application.pipeline.libelles import accord
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.normalize.base import NormalizeStats, SourceNormalizer
from application.pipeline.normalize.bibliographic import BibliographicNormalizer
from interfaces.cli.phases.execution import log, open_tx

if TYPE_CHECKING:
    from sqlalchemy import Connection

# Un normaliseur se construit sur la connexion de sa phase, dont ses adaptateurs dépendent.
type ConstructeurNormalizer = Callable[[Connection], SourceNormalizer]


def build() -> Phase:
    """Normalisation du staging vers les tables sources.

    Écrit les `source_publications` avec leurs métadonnées — résumé, mots-clés, sujets, références — et leurs signatures, en laissant `publication_id` à NULL : la phase `publications` assigne le document à sa publication. Le `raw_data` du staging est vidé après traitement. Pour HAL, les structures sont enrichies et les ORCID et IdRef extraits du TEI.

    Séquence, nettoyage et VACUUM dans `application/pipeline/normalize/phase.py`.
    """
    return _NormalizeSelonOptions()


class _NormalizeSelonOptions:
    """Construit les normaliseurs selon les options du run (`--raw-store`, `--normalize-full`), puis exécute `NormalizePhase`."""

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        from application.pipeline.normalize.phase import NormalizePhase

        options = ctx.options
        registry = _normalize_builders(archive=options.raw_store, full=options.normalize_full)

        def normalize_one(source: str) -> dict[str, object]:
            return _run_normalize(source, registry[source])

        return NormalizePhase(
            ordered_sources=list(registry),
            normalize_one=normalize_one,
            prune_disappeared=_run_prune_disappeared,
            cleanup_orphan_identities=_run_cleanup_orphan_identities,
            vacuum_staging=_vacuum_staging,
        ).run(ctx)


def _run_prune_disappeared() -> int:
    from infrastructure.pipeline.normalize.staging import delete_disappeared_source_publications

    with open_tx() as conn:
        n = delete_disappeared_source_publications(conn)
    if n:
        log.info(
            "%s (disparus de leur source)", accord(n, "document supprimé", "documents supprimés")
        )
    return n


def _run_cleanup_orphan_identities() -> None:
    from infrastructure.pipeline.normalize.authorships import delete_orphan_identities

    with open_tx() as conn:
        delete_orphan_identities(conn)


def _vacuum_staging(full: bool = False) -> None:
    """VACUUM du staging, complet en mode `full` et simple sinon.

    La normalisation vide `staging.raw_data`, un JSONB volumineux. Le VACUUM simple marque l'espace réutilisable, le VACUUM complet réécrit la table et le rend au système. Ce dernier prend un verrou exclusif sur le staging, le temps de son exécution.
    """
    from sqlalchemy import text

    from infrastructure.db.engine import get_sync_engine

    sql = "VACUUM FULL staging" if full else "VACUUM staging"
    with get_sync_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(sql))


def _normalize_row(source: str, stats: NormalizeStats, duration_s: float) -> dict[str, object]:
    """Ligne « par source » de la table d'observabilité de la phase normalize."""
    return {
        "key": source,
        "processed": stats.processed,
        "skipped": stats.skipped,
        "errors": stats.errors,
        "duration_s": round(duration_s, 1),
    }


def _normalize_builders(
    *, archive: bool = True, full: bool = False
) -> dict[str, ConstructeurNormalizer]:
    """Constructeur du normaliseur de chaque source, dans l'ordre de `SOURCE_PRIORITY` : la source qui fait le plus autorité passe en premier, les suivantes complètent les métadonnées qu'elle a posées. Les sources bibliographiques partagent le câblage `_biblio` ; `theses` a le sien, sans repository de revue ni d'éditeur."""
    from application.pipeline.normalize._authorships_batch import SignatureSyncSettings
    from application.pipeline.normalize.normalize_crossref import CrossrefNormalizer
    from application.pipeline.normalize.normalize_datacite import DataciteNormalizer
    from application.pipeline.normalize.normalize_hal import HalNormalizer
    from application.pipeline.normalize.normalize_openalex import OpenalexNormalizer
    from application.pipeline.normalize.normalize_scanr import ScanrNormalizer
    from application.pipeline.normalize.normalize_theses import ThesesNormalizer
    from application.pipeline.normalize.normalize_wos import WosNormalizer
    from infrastructure.fingerprint import fingerprint
    from infrastructure.pipeline.containers import PgContainerGatewayQueries
    from infrastructure.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.pipeline.normalize.source_publications import (
        PgSourcePublicationQueries,
    )
    from infrastructure.pipeline.normalize.staging import PgStagingQueries
    from infrastructure.pipeline.publishers import PgPublisherGatewayQueries
    from infrastructure.raw_store import NullRawStore, get_raw_store

    raw_store = get_raw_store() if archive else NullRawStore()
    sync_settings = SignatureSyncSettings(fingerprint=fingerprint, normalize_full=full)

    def _biblio(cls: type[BibliographicNormalizer]) -> ConstructeurNormalizer:
        return lambda conn: cls(
            conn,
            log,
            PgStagingQueries(raw_store),
            PgSourcePublicationQueries(),
            container_repo_factory=PgContainerGatewayQueries,
            publisher_repo_factory=PgPublisherGatewayQueries,
            authorship_queries=PgAuthorshipsBatchQueries(),
            sync_settings=sync_settings,
        )

    return {
        "theses": lambda conn: ThesesNormalizer(
            conn,
            log,
            PgStagingQueries(raw_store),
            PgSourcePublicationQueries(),
            batch_queries=PgAuthorshipsBatchQueries(),
        ),
        "crossref": _biblio(CrossrefNormalizer),
        "datacite": _biblio(DataciteNormalizer),
        "scanr": _biblio(ScanrNormalizer),
        "hal": _biblio(HalNormalizer),
        "openalex": _biblio(OpenalexNormalizer),
        "wos": _biblio(WosNormalizer),
    }


def _run_normalize(source: str, build: ConstructeurNormalizer) -> dict[str, object]:
    t0 = time.time()
    with open_tx() as conn:
        stats = build(conn).run()
    return _normalize_row(source, stats, time.time() - t0)
