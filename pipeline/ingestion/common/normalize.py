"""Phase `normalize` : normalisation du staging vers `source_publications`, `source_authorships` et `addresses`. Nœuds `normalize.<source>`.

La phase enchaîne ses nœuds (`pipeline.graph`) :

1. la normalisation de chaque source retenue, dans l'ordre de `SOURCE_PRIORITY` ;
2. la suppression des `source_publications` dont le staging porte `disappeared_at` ;
3. le nettoyage des identités d'auteur orphelines (la normalisation réassigne des signatures et la suppression précédente en retire, laissant des `author_identifying_keys` que plus aucune signature ne référence) ;
4. le nettoyage des adresses orphelines, pour la même raison. Sa maintenance, lancée par l'exécuteur, est le `VACUUM` du staging (`raw_data` vidé après normalisation) : `VACUUM FULL` en mode full, simple sinon.

Chaque source hérite de `SourceNormalizer` (`pipeline/ingestion/<source>/normalize.py`). Le patron porte la boucle : chargement des lignes à traiter, un SAVEPOINT par notice (une erreur isolée ne perd pas le lot en cours), commit périodique, progression et bilan. Les requêtes sur `staging`, `source_publications` et les signatures sont injectées à la construction.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, NamedTuple, cast

from sqlalchemy import Connection

from domain.publications.metadata import has_minimal_publication_metadata
from domain.sources.registry import SOURCE_PRIORITY
from infrastructure.db.savepoint import rollback_unless_invalidated, savepoint
from pipeline.ingestion.common.signature_queries import AuthorshipsBatchQueries
from pipeline.ingestion.common.source_publications import SourcePublicationQueries
from pipeline.ingestion.common.staging import StagingQueries, StagingRow
from pipeline.node_runner import NodeRun, NodeStep, run_nodes
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import (
    DERNIERE_BRANCHE,
    SUITE_DE_BRANCHE,
    accord,
    branche_de_source,
)
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import progression
from pipeline.transformation.publishing.containers import ContainerGatewayQueries
from pipeline.transformation.publishing.publishers.publishers import PublisherGatewayQueries

if TYPE_CHECKING:
    from sqlalchemy import Connection


class NormalizeStats(NamedTuple):
    """Bilan d'une normalisation de source : works normalisés, ignorés (rien à écrire / non pertinents), en erreur."""

    processed: int
    skipped: int
    errors: int


class SourceNormalizer(ABC):
    """Template method pour la normalisation source → tables structurées.

    Points d'override :
    - `SOURCE` : identifiant source (obligatoire, ex: "hal", "openalex")
    - `DEFAULT_BATCH_SIZE` : taille de commit (défaut 500)
    - `FETCH_SUB_BATCH` : taille des sous-lots de fetch staging (défaut 50)
    - `minimal_metadata(row)` : abstrait, titre et année de la notice
    - `normalize_record(conn, row) -> bool | None` : abstrait, logique métier d'une notice complète
    - `preload_caches(conn)` : pré-chargement optionnel
    - `cleanup()` : libération des caches après commit final
    """

    SOURCE: ClassVar[str] = ""
    DEFAULT_BATCH_SIZE: ClassVar[int] = 500
    # Taille des sous-lots de fetch staging : charger tous les staging d'un coup fait exploser la RAM côté Python (JSONB désérialisés, overhead ~3-5× la taille brute).
    FETCH_SUB_BATCH: ClassVar[int] = 50

    def __init__(
        self, conn: Connection, logger: logging.Logger, staging_queries: StagingQueries
    ) -> None:
        self.conn = conn
        self.logger = logger
        self._staging = staging_queries

    # ── Hooks métier ────────────────────────────────────────────

    @abstractmethod
    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        """Titre et année de la notice, lus dans son payload."""

    @abstractmethod
    def normalize_record(self, conn: Connection, row: StagingRow) -> bool | None:
        """Normalise une notice qui porte les métadonnées minimales et marque sa ligne traitée. Retourne True (ok), None (skip) ou False (notice refusée, sans rien écrire)."""

    def process_work(self, conn: Connection, row: StagingRow) -> bool | None:
        """Traite une ligne staging. Retourne True (ok), None (skip), False (notice refusée).

        Une notice vide est sautée. Une notice sans titre ou sans année, ou refusée par la source (`normalize_record` rend False), ne fonde aucune publication (`_reject`).
        """
        if not row.raw_data:
            self._staging.mark_done(conn, row.id)
            return None
        title, pub_year = self.minimal_metadata(row)
        if not has_minimal_publication_metadata(title, pub_year):
            return self._reject(conn, row)
        result = self.normalize_record(conn, row)
        if result is False:
            return self._reject(conn, row)
        return result

    def _reject(self, conn: Connection, row: StagingRow) -> bool:
        """Écarte une notice refusée : l'enregistrement qu'elle avait produit est supprimé, sa ligne marquée traitée. Rend False, compté comme notice incomplète."""
        self._staging.discard_source_publication(conn, row.id)
        self._staging.mark_done(conn, row.id)
        return False

    def preload_caches(self, conn: Connection) -> None:  # noqa: B027 (hook optionnel)
        """Pré-chargement optionnel, avant la boucle sur les notices."""

    def cleanup(self) -> None:  # noqa: B027 (hook optionnel)
        """Libération des caches in-memory."""

    # ── Template method ────────────────────────────────────────

    def _count_pending(self, conn: Connection) -> int:
        return self._staging.count_pending_staging(conn, self.SOURCE)

    def _iter_rows(self, conn: Connection) -> Iterator[StagingRow]:
        """Itère toutes les lignes à traiter par sous-lots de `FETCH_SUB_BATCH`."""
        work_ids = self._staging.fetch_pending_staging_ids(conn, self.SOURCE)
        for start in range(0, len(work_ids), self.FETCH_SUB_BATCH):
            batch_ids = work_ids[start : start + self.FETCH_SUB_BATCH]
            yield from self._staging.fetch_staging_by_ids(conn, batch_ids)

    def _process_one(self, conn: Connection, row: StagingRow) -> bool | None:
        """Enveloppe process_work dans un SAVEPOINT : un work en erreur est annulé sans abandonner le batch en cours."""
        with savepoint(conn, on_rollback_failure=self.conn.rollback):
            return self.process_work(conn, row)

    def _recapitule_incomplets(self, identifiants: list[str]) -> None:
        """Récapitule sous la barre de la source les documents qu'elle a laissés de côté.

        Le trait vertical se prolonge d'une ligne à l'autre : le récapitulatif appartient à la branche de sa source, et la liste des sources reste d'un seul tenant. Le logger nu porte ces lignes, celui de la source les préfixerait de son nom et romprait l'alignement.
        """
        if not identifiants:
            return
        self.logger.info(
            "%s%s aux métadonnées incomplètes",
            SUITE_DE_BRANCHE,
            accord(len(identifiants), "document"),
        )
        for identifiant in identifiants:
            self.logger.info("%s%s", SUITE_DE_BRANCHE, identifiant)

    def run(self) -> NormalizeStats:
        """Entry point : pilote la boucle de normalisation."""
        self.conn.rollback()

        # Préfixe `[source]` sur les lignes de la boucle (progression, bilan) : dans un run multi-sources, chaque batch reste rattaché à sa source sans remonter au bandeau.
        slog = scoped_logger(self.logger, self.SOURCE)

        try:
            total = self._count_pending(self.conn)
            if total == 0:
                return NormalizeStats(0, 0, 0)

            self.preload_caches(self.conn)

            processed = 0
            skipped = 0
            errors = 0
            # Documents que `process_work` laisse de côté faute de métadonnées exploitables :
            # récapitulés sous la barre plutôt qu'écrits un par un au fil de la boucle.
            incomplets: list[str] = []

            with progression(total, branche_de_source(self.SOURCE), slog) as avancement:
                for row in self._iter_rows(self.conn):
                    avancement.avance()
                    try:
                        result = self._process_one(self.conn, row)
                    except Exception as e:
                        slog.error(f"Erreur sur {row.source_id}: {e}")
                        errors += 1
                        continue

                    if result is True:
                        processed += 1
                    elif result is None:
                        skipped += 1
                    else:
                        errors += 1
                        incomplets.append(row.source_id)

                    done = processed + skipped
                    if done > 0 and done % self.DEFAULT_BATCH_SIZE == 0:
                        self.conn.commit()

            self.conn.commit()
            self.cleanup()

            self._recapitule_incomplets(incomplets)
            return NormalizeStats(processed, skipped, errors)

        except KeyboardInterrupt:
            # Ctrl+C frappe souvent en plein `conn.execute()` : la transaction est alors avortée et `commit()` lèverait `PendingRollbackError`.
            # On rollback (le batch en cours, incomplet, est jeté ; les batches committés tous les `batch_size` sont durables) puis on re-raise pour laisser `run_pipeline.main()` faire l'arrêt propre (rapport partiel + exit 130).
            # Sans le `raise`, la phase « réussirait » et le pipeline enchaînerait sur la source suivante.
            rollback_unless_invalidated(self.conn)
            slog.warning("Interruption — batches déjà committés conservés.")
            raise
        except Exception as e:
            rollback_unless_invalidated(self.conn)
            slog.error(f"Erreur fatale : {e}")
            raise


class BibliographicNormalizer(SourceNormalizer):
    """Normaliseur d'une source bibliographique : `SourceNormalizer` doté des repositories conteneur (revue et monographie) / éditeur."""

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: SourcePublicationQueries,
        container_repo_factory: Callable[[Connection], ContainerGatewayQueries],
        publisher_repo_factory: Callable[[Connection], PublisherGatewayQueries],
        authorship_queries: AuthorshipsBatchQueries,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._container_repo_factory = container_repo_factory
        self._container_repo: ContainerGatewayQueries | None = None
        self._publisher_repo_factory = publisher_repo_factory
        self._publisher_repo: PublisherGatewayQueries | None = None
        self._authorship_queries = authorship_queries

    def preload_caches(self, conn: Connection) -> None:
        """Instancie les repositories sur la connexion prête, une fois avant la boucle de traitement."""
        self._container_repo = self._container_repo_factory(conn)
        self._publisher_repo = self._publisher_repo_factory(conn)

    def _require_repos(
        self,
    ) -> tuple[ContainerGatewayQueries, PublisherGatewayQueries]:
        """Les deux repositories, garantis chargés par `preload_caches`."""
        assert self._container_repo is not None and self._publisher_repo is not None, (
            "preload_caches doit être appelé avant process_work"
        )
        return self._container_repo, self._publisher_repo


NormalizeOne = Callable[[PhaseContext, str], NormalizeStats]
"""Normalise une source (connexion + normaliseur câblé) et rend son bilan."""


def _retenue(source: str) -> Callable[[PhaseContext], bool]:
    """Condition d'exécution du nœud de `source` : la source fait partie des sources du run."""
    return lambda ctx: source in ctx.options.sources


@dataclass(frozen=True)
class NormalizePhase:
    """Le run normalise les sources de ses options, toutes quand il n'en restreint aucune, dans l'ordre de `SOURCE_PRIORITY`."""

    normalize_one: NormalizeOne
    prune_disappeared: Callable[[PhaseContext], int]
    cleanup_orphan_identities: Callable[[PhaseContext], int]
    cleanup_orphan_addresses: Callable[[PhaseContext], int]

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Normalise les sources retenues, retire les documents disparus, nettoie les identités et les adresses orphelines ; l'exécuteur lance ensuite le `VACUUM` du staging."""
        sources = [source.value for source in SOURCE_PRIORITY]
        steps = {
            f"normalize.{source}": NodeStep(
                self._normalize_node(source), section="Normalisation", when=_retenue(source)
            )
            for source in sources
        }
        steps["normalize.prune_disappeared"] = NodeStep(self._prune, section="Normalisation")
        steps["normalize.cleanup_orphan_identities"] = NodeStep(
            self._cleanup, section="Maintenance des tables", libelle="Identités d'auteur orphelines"
        )
        steps["normalize.cleanup_orphan_addresses"] = NodeStep(
            self._cleanup_addresses, section="Maintenance des tables", libelle="Adresses orphelines"
        )
        by_node = run_nodes("normalize", steps, ctx)

        rows = [
            {
                **cast("dict[str, object]", node.details["row"]),
                "duration_s": node.duration_s,
            }
            for source in sources
            if "row" in (node := by_node[f"normalize.{source}"]).details
        ]
        metrics = PhaseMetrics()
        normalises = sum(cast("int", row["processed"]) for row in rows)
        metrics.add(total=normalises)
        metrics.resume = f"{accord(normalises, 'document normalisé', 'documents normalisés')}"
        metrics.details["table"] = {"rows": rows}
        metrics.details["disappeared_pruned"] = by_node["normalize.prune_disappeared"].extras.get(
            "disappeared", 0
        )
        return metrics

    def _normalize_node(self, source: str) -> NodeRun:
        """Nœud `normalize.<source>` : normalise la source et garde sa ligne de la table d'observabilité."""

        def run(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            stats = self.normalize_one(ctx, source)
            metrics = PhaseMetrics()
            metrics.details["row"] = {
                "key": source,
                "processed": stats.processed,
                "skipped": stats.skipped,
                "errors": stats.errors,
            }
            return metrics

        return run

    def _prune(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        """Supprime les documents disparus de leur source, et ferme la section de normalisation."""
        disparues = self.prune_disappeared(ctx)
        if disparues:
            ctx.logger.info(
                "%s%s (disparus de leur source)",
                DERNIERE_BRANCHE,
                accord(disparues, "document supprimé", "documents supprimés"),
            )
        else:
            ctx.logger.info("%saucun document disparu de sa source", DERNIERE_BRANCHE)
        return PhaseMetrics(extras={"disappeared": disparues})

    def _cleanup(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        supprimees = self.cleanup_orphan_identities(ctx)
        metrics = PhaseMetrics()
        if supprimees:
            metrics.resume = f"{accord(supprimees, 'identité supprimée', 'identités supprimées')}"
        return metrics

    def _cleanup_addresses(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        supprimees = self.cleanup_orphan_addresses(ctx)
        metrics = PhaseMetrics()
        if supprimees:
            metrics.resume = f"{accord(supprimees, 'adresse supprimée', 'adresses supprimées')}"
        return metrics


# ── Câblage ───────────────────────────────────────────────────


type ConstructeurNormalizer = Callable[[Connection, logging.Logger], SourceNormalizer]


def build() -> Phase:
    """Normalisation du staging vers les tables sources.

    Écrit les `source_publications` avec leurs métadonnées — résumé, mots-clés, sujets, références — et leurs signatures, en laissant `publication_id` à NULL : la phase `publications` assigne le document à sa publication. Le `raw_data` du staging est vidé après traitement. Pour HAL, les ORCID et IdRef sont extraits du TEI.
    """
    return _NormalizeSelonOptions()


class _NormalizeSelonOptions:
    """Construit les normaliseurs selon les options du run (`--raw-store`), puis exécute `NormalizePhase`.

    Avec `--normalize-full`, chaque source marque d'abord toutes ses notices à resynchroniser.
    """

    def run(self, ctx: PhaseContext) -> PhaseMetrics:

        options = ctx.options
        registry = _normalize_builders(archive=options.raw_store)

        def normalize_one(ctx: PhaseContext, source: str) -> NormalizeStats:
            if options.normalize_full:
                _run_mark_signatures_to_resync(ctx, source)
            return _run_normalize(ctx, registry[source])

        return NormalizePhase(
            normalize_one=normalize_one,
            prune_disappeared=_run_prune_disappeared,
            cleanup_orphan_identities=_run_cleanup_orphan_identities,
            cleanup_orphan_addresses=_run_cleanup_orphan_addresses,
        ).run(ctx)


def _run_mark_signatures_to_resync(ctx: PhaseContext, source: str) -> None:
    from pipeline.ingestion.common.signature_queries import mark_signatures_to_resync

    with ctx.open_tx() as conn:
        mark_signatures_to_resync(conn, source)


def _run_prune_disappeared(ctx: PhaseContext) -> int:
    from pipeline.ingestion.common.staging import delete_disappeared_source_publications

    with ctx.open_tx() as conn:
        return delete_disappeared_source_publications(conn)


def _run_cleanup_orphan_identities(ctx: PhaseContext) -> int:
    from pipeline.ingestion.common.signature_queries import delete_orphan_identities

    with ctx.open_tx() as conn:
        return delete_orphan_identities(conn)


def _run_cleanup_orphan_addresses(ctx: PhaseContext) -> int:
    from pipeline.ingestion.common.signature_queries import delete_orphan_addresses

    with ctx.open_tx() as conn:
        return delete_orphan_addresses(conn)


def _normalize_builders(*, archive: bool = True) -> dict[str, ConstructeurNormalizer]:
    """Constructeur du normaliseur de chaque source. Les sources bibliographiques partagent le câblage `_biblio` ; `theses` a le sien, sans repository de revue ni d'éditeur."""
    from infrastructure.raw_store import NullRawStore, get_raw_store
    from pipeline.ingestion.common.signature_queries import AuthorshipsBatchQueries
    from pipeline.ingestion.common.source_publications import (
        SourcePublicationQueries,
    )
    from pipeline.ingestion.common.staging import StagingQueries
    from pipeline.ingestion.crossref.normalize import CrossrefNormalizer
    from pipeline.ingestion.datacite.normalize import DataciteNormalizer
    from pipeline.ingestion.hal.normalize import HalNormalizer
    from pipeline.ingestion.openalex.normalize import OpenalexNormalizer
    from pipeline.ingestion.scanr.normalize import ScanrNormalizer
    from pipeline.ingestion.theses.normalize import ThesesNormalizer
    from pipeline.ingestion.wos.normalize import WosNormalizer
    from pipeline.transformation.publishing.containers import ContainerGatewayQueries
    from pipeline.transformation.publishing.publishers.publishers import PublisherGatewayQueries

    raw_store = get_raw_store() if archive else NullRawStore()

    def _biblio(cls: type[BibliographicNormalizer]) -> ConstructeurNormalizer:
        return lambda conn, logger: cls(
            conn,
            logger,
            StagingQueries(raw_store),
            SourcePublicationQueries(),
            container_repo_factory=ContainerGatewayQueries,
            publisher_repo_factory=PublisherGatewayQueries,
            authorship_queries=AuthorshipsBatchQueries(),
        )

    return {
        "theses": lambda conn, logger: ThesesNormalizer(
            conn,
            logger,
            StagingQueries(raw_store),
            SourcePublicationQueries(),
            batch_queries=AuthorshipsBatchQueries(),
        ),
        "crossref": _biblio(CrossrefNormalizer),
        "datacite": _biblio(DataciteNormalizer),
        "scanr": _biblio(ScanrNormalizer),
        "hal": _biblio(HalNormalizer),
        "openalex": _biblio(OpenalexNormalizer),
        "wos": _biblio(WosNormalizer),
    }


def _run_normalize(ctx: PhaseContext, build: ConstructeurNormalizer) -> NormalizeStats:
    with ctx.open_tx() as conn:
        return build(conn, ctx.logger).run()
