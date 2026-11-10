"""Moissonnage OPS : tâche `harvest.ops`.

Les graphies des déposants du périmètre (`api_ids.ops`) servent de termes de recherche (`pa all "…"`), réduites aux graphies minimales (`search_forms`). Une publication trouvée est gardée si l'un de ses déposants a exactement l'une de ces graphies, et si l'une de ses priorités tombe dans la fenêtre d'années, ou à défaut de date de priorité. La famille INPADOC de chaque publication gardée est lue, puis écrite dans `staging` sous le numéro de sa priorité la plus ancienne (`family_key`), si cette priorité tombe dans la fenêtre. Plusieurs familles docdb d'une même famille INPADOC donnent un seul document.
"""

from __future__ import annotations

from collections.abc import Mapping

from domain.normalize import normalize_text
from domain.types import JsonValue
from pipeline.ingestion.common.harvester import HarvestWindow, SourceHarvester, stage_document
from pipeline.ingestion.ops.api import (
    SEARCH_MAX,
    SEARCH_PAGE,
    SEARCH_PATH,
    SearchHit,
    family_path,
    get_json,
    search_page,
    search_params,
)
from pipeline.ingestion.ops.family import family_key, family_members, first_priority
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress, track_progress


def family_document(body: JsonValue, key: str) -> dict[str, JsonValue]:
    """Renvoie le document écrit dans `staging` : l'identifiant de la famille et sa réponse OPS."""
    return {"id": key, "family": body}


def search_query(form: str) -> str:
    """Construit la recherche CQL des publications dont un déposant contient tous les mots de `form`."""
    return f'pa all "{form}"'


def search_forms(forms: frozenset[str]) -> list[str]:
    """Renvoie les graphies à chercher : une graphie dont les mots contiennent tous ceux d'une autre est couverte par la recherche de celle-ci."""
    words = {f: frozenset(f.split()) for f in forms}
    return sorted(f for f in forms if not any(other < words[f] for other in words.values()))


def kept_hit(hit: SearchHit, forms: frozenset[str], years: frozenset[int]) -> bool:
    """Indique si une publication trouvée a un déposant du périmètre et une priorité dans la fenêtre, ou aucune date de priorité."""
    if not any(normalize_text(a.split("[")[0]) in forms for a in hit.applicants):
        return False
    dated = [int(d[:4]) for d in hit.priority_dates if d[:4].isdigit()]
    return not dated or any(y in years for y in dated)


class OpsHarvester(SourceHarvester[None]):
    """Moissonnage des familles de brevets dont un déposant est une structure du périmètre."""

    SOURCE = "ops"
    MISSING_API_IDS = "aucune graphie de déposant"
    DOCUMENT = "famille"
    FEMININE = True

    def run(self, window: HarvestWindow) -> PhaseMetrics:
        forms = frozenset(normalize_text(f) for f in self._api_ids())
        years = frozenset(self._years(window))
        publications: dict[str, str] = {}
        searched = search_forms(forms)
        with track_progress(len(searched), self._label("recherche"), self.logger) as progress:
            for form in searched:
                for hit in self._search(form):
                    if kept_hit(hit, forms, years):
                        publications.setdefault(hit.family_id, hit.publication)
                progress.advance()
        return self._harvest_at_once(
            len(publications), lambda progress: self._stage_families(publications, years, progress)
        )

    def _search(self, form: str) -> list[SearchHit]:
        hits: list[SearchHit] = []
        start = 1
        while start <= SEARCH_MAX:
            body = get_json(
                SEARCH_PATH, search_params(search_query(form), start), label=f"recherche {form}"
            )
            if body is None:
                break
            total, page = search_page(body)
            hits.extend(page)
            start += SEARCH_PAGE
            if start > total or not page:
                break
        return hits

    def _stage_families(
        self, publications: Mapping[str, str], years: frozenset[int], progress: Progress
    ) -> PhaseMetrics:
        metrics = PhaseMetrics()
        staged: set[str] = set()
        for publication in publications.values():
            progress.advance()
            body = get_json(family_path(publication), label=f"famille {publication}")
            if body is None:
                continue
            members = family_members(body if isinstance(body, Mapping) else {})
            key = family_key(members)
            priority = first_priority(members)
            if (
                key is None
                or key in staged
                or (priority and priority.date and priority.date.year not in years)
            ):
                continue
            staged.add(key)
            stage_document(
                self.conn, metrics, source=self.SOURCE, record=family_document(body, key)
            )
            self.conn.commit()
        return metrics
