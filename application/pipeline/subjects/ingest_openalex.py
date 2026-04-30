"""Ingestion des sujets OpenAlex.

Source format (cf normalize_openalex.py:133-149, 370-377) :
- `keywords` : list[str] (déjà extraits du dict `keyword`+`score`, score perdu
  en l'état actuel — on traite comme libre sans langue, pour permettre la
  déduplication inter-sources sur lower(label)).
- `topics`   : list[dict] avec keys `domain`, `field`, `subfield`, `topic` (chacune
  un display_name) + `score` (score du topic feuille).

L'extraction actuelle ne conserve PAS les IDs OpenAlex stables : on utilise
`lower(display_name)` comme `ontology_id`. C'est un compromis ; si OpenAlex
renomme un concept, on créera un nouveau concept distinct. À revoir si on
étend `normalize_openalex.py` pour conserver les IDs (Phase ultérieure).

Hiérarchie : on lie la publication aux **4 niveaux** (domain, field, subfield,
topic) en parent_id chaîné. Le score du topic est appliqué uniquement au topic
feuille ; les niveaux supérieurs sont liés sans score.
"""

from typing import Any

from application.pipeline.subjects._common import SubjectCache, dedup_strs
from domain.subject import ONTOLOGY_OPENALEX_TOPIC

SOURCE = "openalex"

# Niveaux OpenAlex dans l'ordre hiérarchique. Le `level` stocké en DB suit
# cet ordre : domain=0, field=1, subfield=2, topic=3.
_LEVELS = ("domain", "field", "subfield", "topic")


def ingest(
    cur: Any,
    *,
    publication_id: int,
    keywords: list[str] | None,
    topics: Any,
    cache: SubjectCache,
) -> int:
    """Ingère keywords (libres EN) et topics hiérarchiques.
    Retourne le nombre de liens créés."""
    links: list[tuple[int, int, float | None]] = []

    for kw in dedup_strs(keywords):
        sid = cache.get_or_upsert(cur, label=kw)
        links.append((publication_id, sid, None))

    if isinstance(topics, list):
        for entry in topics:
            _collect_topic_chain(cur, cache, publication_id, entry, links)

    return cache.link_bulk(cur, source=SOURCE, rows=links)


def _collect_topic_chain(
    cur: Any,
    cache: SubjectCache,
    publication_id: int,
    entry: Any,
    links: list[tuple[int, int, float | None]],
) -> None:
    """Construit/upsert chaque niveau et collecte les liens à insérer.

    Le score (porté par le topic feuille) est appliqué seulement au lien
    du niveau le plus profond observé.
    """
    if not isinstance(entry, dict):
        return

    score = entry.get("score") if isinstance(entry.get("score"), (int, float)) else None

    levels_present: list[tuple[str, str, int]] = []
    for idx, name in enumerate(_LEVELS):
        label = entry.get(name)
        if isinstance(label, str) and label.strip():
            levels_present.append((name, label.strip(), idx))

    if not levels_present:
        return

    parent_label: str | None = None
    deepest_idx = levels_present[-1][2]
    for _name, label, idx in levels_present:
        ontology_entry: dict[str, Any] = {
            "codes": [label.lower()],
            "level": idx,
        }
        if parent_label is not None:
            ontology_entry["parent"] = parent_label
        sid = cache.get_or_upsert(
            cur,
            label=label,
            language="en",
            ontologies={ONTOLOGY_OPENALEX_TOPIC: ontology_entry},
        )
        links.append((publication_id, sid, score if idx == deepest_idx else None))
        parent_label = label
