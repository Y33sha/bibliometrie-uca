"""Câblage de la phase `normalize`."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from interfaces.cli.phases.execution import log, open_tx
from pipeline.context import Phase, PhaseContext
from pipeline.metrics import PhaseMetrics
from pipeline.sources.normalize import BibliographicNormalizer, NormalizeStats, SourceNormalizer

if TYPE_CHECKING:
    from sqlalchemy import Connection

# Un normaliseur se construit sur la connexion de sa phase, dont ses adaptateurs dépendent.
type ConstructeurNormalizer = Callable[[Connection], SourceNormalizer]


def build() -> Phase:
    """Normalisation du staging vers les tables sources.

    Écrit les `source_publications` avec leurs métadonnées — résumé, mots-clés, sujets, références — et leurs signatures, en laissant `publication_id` à NULL : la phase `publications` assigne le document à sa publication. Le `raw_data` du staging est vidé après traitement. Pour HAL, les structures sont enrichies et les ORCID et IdRef extraits du TEI.

    Séquence, nettoyage et VACUUM dans `pipeline/sources/normalize.py`.
    """
    return _NormalizeSelonOptions()


class _NormalizeSelonOptions:
    """Construit les normaliseurs selon les options du run (`--raw-store`, `--normalize-full`), puis exécute `NormalizePhase`."""

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        from pipeline.sources.normalize import NormalizePhase

        options = ctx.options
        registry = _normalize_builders(archive=options.raw_store, full=options.normalize_full)

        def normalize_one(source: str) -> NormalizeStats:
            return _run_normalize(registry[source])

        return NormalizePhase(
            ordered_sources=list(registry),
            normalize_one=normalize_one,
            prune_disappeared=_run_prune_disappeared,
            cleanup_orphan_identities=_run_cleanup_orphan_identities,
            vacuum_staging=_vacuum_staging,
        ).run(ctx)


def _run_prune_disappeared() -> int:
    from pipeline.sources.staging import delete_disappeared_source_publications

    with open_tx() as conn:
        return delete_disappeared_source_publications(conn)


def _run_cleanup_orphan_identities() -> None:
    from pipeline.sources.signature_queries import delete_orphan_identities

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


def _normalize_builders(
    *, archive: bool = True, full: bool = False
) -> dict[str, ConstructeurNormalizer]:
    """Constructeur du normaliseur de chaque source, dans l'ordre de `SOURCE_PRIORITY` : la source qui fait le plus autorité passe en premier, les suivantes complètent les métadonnées qu'elle a posées. Les sources bibliographiques partagent le câblage `_biblio` ; `theses` a le sien, sans repository de revue ni d'éditeur."""
    from infrastructure.fingerprint import fingerprint
    from infrastructure.pipeline.containers import PgContainerGatewayQueries
    from infrastructure.pipeline.publishers import PgPublisherGatewayQueries
    from infrastructure.raw_store import NullRawStore, get_raw_store
    from pipeline.sources.crossref.normalize import CrossrefNormalizer
    from pipeline.sources.datacite.normalize import DataciteNormalizer
    from pipeline.sources.hal.normalize import HalNormalizer
    from pipeline.sources.openalex.normalize import OpenalexNormalizer
    from pipeline.sources.scanr.normalize import ScanrNormalizer
    from pipeline.sources.signature_queries import AuthorshipsBatchQueries
    from pipeline.sources.signatures import SignatureSyncSettings
    from pipeline.sources.source_publications import (
        SourcePublicationQueries,
    )
    from pipeline.sources.staging import StagingQueries
    from pipeline.sources.theses.normalize import ThesesNormalizer
    from pipeline.sources.wos.normalize import WosNormalizer

    raw_store = get_raw_store() if archive else NullRawStore()
    sync_settings = SignatureSyncSettings(fingerprint=fingerprint, normalize_full=full)

    def _biblio(cls: type[BibliographicNormalizer]) -> ConstructeurNormalizer:
        return lambda conn: cls(
            conn,
            log,
            StagingQueries(raw_store),
            SourcePublicationQueries(),
            container_repo_factory=PgContainerGatewayQueries,
            publisher_repo_factory=PgPublisherGatewayQueries,
            authorship_queries=AuthorshipsBatchQueries(),
            sync_settings=sync_settings,
        )

    return {
        "theses": lambda conn: ThesesNormalizer(
            conn,
            log,
            StagingQueries(raw_store),
            SourcePublicationQueries(),
            batch_queries=AuthorshipsBatchQueries(),
            sync_settings=sync_settings,
        ),
        "crossref": _biblio(CrossrefNormalizer),
        "datacite": _biblio(DataciteNormalizer),
        "scanr": _biblio(ScanrNormalizer),
        "hal": _biblio(HalNormalizer),
        "openalex": _biblio(OpenalexNormalizer),
        "wos": _biblio(WosNormalizer),
    }


def _run_normalize(build: ConstructeurNormalizer) -> NormalizeStats:
    with open_tx() as conn:
        return build(conn).run()
