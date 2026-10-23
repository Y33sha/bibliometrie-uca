"""Moissonnage HAL : tâche `harvest.hal`.

Interroge l'**union** des collections du périmètre en une seule requête Solr (`fq=collCode_s:(C1 OR … OR Cn)`), paginée en `cursorMark`. Solr dédoublonne l'union côté serveur : chaque document est récupéré une fois, quel que soit le nombre de collections du périmètre auxquelles il appartient.

Le routage new/updated/unchanged vient de l'écriture dans `staging`, pilotée par `raw_hash` : un `raw_hash=null` en base force le réimport (nouveau téléchargement → empreinte recalculée → contenu réécrit + `processed=FALSE`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.types import as_mapping, as_sequence, as_str, at_path
from infrastructure.read_models.perimeters import get_hal_collections
from pipeline.ingestion.common.harvester import (
    HarvestConfigError,
    HarvestWindow,
    SourceHarvester,
    stage_document,
)
from pipeline.ingestion.hal.api import HalClient
from pipeline.ingestion.hal.fields import extract_doi, extract_id
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress


@dataclass(frozen=True)
class HalHarvestConfig:
    """Configuration du moissonnage HAL, lue en base."""

    # {code → libellé} des collections HAL des structures du périmètre d'extraction.
    all_collections: Mapping[str, str]


def build_query(years: list[int] | None, since: str | None = None) -> str:
    """Requête Solr (`q`) : années de publication et/ou date de dernière modification.

    - `years` borne `producedDateY_i:[min TO max]`.
    - `since` (`YYYY-MM-DD`) borne `modifiedDate_tdate:[since TO *]`, date de dernière modification du dépôt, qui vaut la date de dépôt pour un dépôt jamais modifié.

    Les deux filtres se combinent en AND. Au moins un des deux est requis.
    """
    if not years and not since:
        raise ValueError("build_query requires either `since` or a non-empty `years` list")
    parts: list[str] = []
    if years:
        parts.append(f"producedDateY_i:[{min(years)} TO {max(years)}]")
    if since:
        parts.append(f"modifiedDate_tdate:[{since}T00:00:00Z TO *]")
    return " AND ".join(parts)


def build_collections_fq(collection_codes: list[str]) -> str:
    """Filtre Solr `collCode_s:("C1" OR "C2" …)` sur toutes les collections. Les codes sont entre guillemets : certains contiennent un tiret (`CHU-CLERMONTFERRAND`), que Solr lirait comme un opérateur."""
    terms = " OR ".join(f'"{code}"' for code in collection_codes)
    return f"collCode_s:({terms})"


def harvest_union(
    client: HalClient,
    config: HalHarvestConfig,
    conn: Connection,
    progress: Progress,
    *,
    years: list[int] | None = None,
    since: str | None = None,
) -> PhaseMetrics:
    """Moissonne l'union des collections pour un périmètre temporel, page après page jusqu'à stabilisation du marqueur.

    Chaque document est écrit une fois dans `staging` et fait avancer `progress`. Retourne `PhaseMetrics(new, updated, unchanged, total)`.
    """
    query = build_query(years=years, since=since)
    fq = build_collections_fq(list(config.all_collections))

    metrics = PhaseMetrics()
    cursor = "*"
    while True:
        data = client.fetch_page_cursor(query, fq, cursor)
        docs = [as_mapping(d) for d in as_sequence(at_path(data, "response").get("docs"))]

        for doc in docs:
            hal_id = extract_id(doc)
            if not hal_id:
                continue
            stage_document(
                conn, metrics, source="hal", source_id=hal_id, doi=extract_doi(doc), raw_data=doc
            )
        conn.commit()

        progress.advance(len(docs))

        # Fin de pagination : Solr renvoie le marqueur reçu une fois l'union épuisée. Une page vide
        # borne aussi la boucle, en cas d'incohérence du serveur.
        next_cursor = as_str(data.get("nextCursorMark")) or cursor
        if next_cursor == cursor or not docs:
            break
        cursor = next_cursor

    return metrics


class HalHarvester(SourceHarvester[HalHarvestConfig, HalClient]):
    """Moissonnage HAL : l'union des collections du périmètre, année par année ou depuis une date."""

    SOURCE = "hal"

    def load_config(self, conn: Connection) -> HalHarvestConfig:
        collections = get_hal_collections(conn)
        if not collections:
            raise HarvestConfigError(
                "aucune collection HAL (aucune structure du périmètre d'extraction n'a de hal_collection)"
            )
        return HalHarvestConfig(all_collections=dict(collections))

    def harvest_all(self, window: HarvestWindow, config: HalHarvestConfig) -> PhaseMetrics:
        """Moissonne l'union des collections, périmètre temporel par périmètre.

        En mode incrémental, un seul périmètre : les dépôts modifiés depuis la date, dans la plage d'années du mode complet. Sinon une passe par année, qui permet une reprise ciblée par `--year` : un document n'a qu'une année de publication.
        """
        client = self._client
        fq = build_collections_fq(list(config.all_collections))
        years = self._years(window)

        if window.since:
            return self._harvest_at_once(
                client.count(build_query(years=years, since=window.since), fq),
                lambda progress: harvest_union(
                    client,
                    config,
                    self.conn,
                    progress,
                    years=years,
                    since=window.since,
                ),
            )

        def count_year(year: int) -> int:
            return client.count(build_query(years=[year]), fq)

        def harvest_step(year: int, progress: Progress) -> PhaseMetrics:
            return harvest_union(
                client,
                config,
                self.conn,
                progress,
                years=[year],
            )

        return self._harvest_by_year(years, count_year, harvest_step)
