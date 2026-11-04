"""Sous-étape de la phase `publishing` : fusion des autres noms d'un éditeur.

Un éditeur nommé par les sources, sans préfixe DOI, rejoint le titulaire des préfixes DOI de ses enregistrements sources quand leurs noms sont compatibles (`domain.publishers.aliases`). Les préfixes des plateformes d'éditeurs sont écartés : ils désignent la plateforme. Les éditeurs de même nom réduit fusionnent ensuite (`same_name_merges`). La fusion est celle de l'administration des éditeurs, sans les revues homonymes : les formes de nom passent à l'éditeur gardé, retrouvé ensuite par ce nom. Le journal garde les deux noms.
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.platforms.registry import is_publisher_platform_prefix
from domain.publishers.aliases import (
    NamedPublisher,
    compatible_publisher_names,
    prefix_holder,
    same_name_merges,
)
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics

LABEL = "Autres noms des éditeurs"
"""Libellé de la sous-étape dans le journal de la phase."""

MergePublishers = Callable[[int, int], None]
"""`(cible, source)` : fusionne l'éditeur source dans la cible et valide la transaction."""

_EVIDENCE = text("""
    SELECT sr.publisher_id AS named_id, dp.publisher_id AS holder_id, dp.prefix, count(*) AS records
    FROM source_records sr
    JOIN publications p ON p.id = sr.publication_id
    JOIN doi_prefixes dp ON dp.prefix = p.doi_prefix
    WHERE sr.publisher_id IS NOT NULL
      AND dp.publisher_id IS NOT NULL
      AND dp.publisher_id <> sr.publisher_id
      AND NOT EXISTS (SELECT 1 FROM doi_prefixes own WHERE own.publisher_id = sr.publisher_id)
    GROUP BY 1, 2, 3
""")
"""Enregistrements sources qui nomment un éditeur sans préfixe DOI, par titulaire du préfixe DOI de leur publication."""

_NAMES = text("SELECT id, name FROM publishers WHERE id = ANY(:ids)")

_PUBLISHERS = text("""
    SELECT p.id, p.name, coalesce(r.records, 0) AS records, h.publisher_id IS NOT NULL AS holds_prefix
    FROM publishers p
    LEFT JOIN (
        SELECT publisher_id, count(*) AS records FROM source_records
        WHERE publisher_id IS NOT NULL GROUP BY 1
    ) r ON r.publisher_id = p.id
    LEFT JOIN (SELECT DISTINCT publisher_id FROM doi_prefixes) h ON h.publisher_id = p.id
""")


class PublisherMerge(NamedTuple):
    """Fusion d'un éditeur dans un autre, avec leurs noms."""

    source_id: int
    source: str
    target_id: int
    target: str


def find_publisher_aliases(conn: Connection) -> list[PublisherMerge]:
    """Renvoie les éditeurs nommés par les sources qui sont un autre nom du titulaire de leurs préfixes."""
    holders: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for r in conn.execute(_EVIDENCE):
        if not is_publisher_platform_prefix(r.prefix):
            holders[r.named_id][r.holder_id] += r.records
    pairs = {
        named_id: holder_id
        for named_id, counts in holders.items()
        if (holder_id := prefix_holder(counts)) is not None
    }
    ids = list({*pairs, *pairs.values()})
    names = {r.id: r.name for r in conn.execute(_NAMES, {"ids": ids})}
    return [
        PublisherMerge(named_id, names[named_id], holder_id, names[holder_id])
        for named_id, holder_id in sorted(pairs.items())
        if compatible_publisher_names(names[named_id], names[holder_id])
    ]


def find_same_name_publishers(conn: Connection) -> list[PublisherMerge]:
    """Renvoie les fusions des éditeurs de même nom réduit (`same_name_merges`)."""
    publishers = {
        r.id: NamedPublisher(r.id, r.name, r.records, r.holds_prefix)
        for r in conn.execute(_PUBLISHERS)
    }
    return [
        PublisherMerge(source, publishers[source].name, target, publishers[target].name)
        for source, target in same_name_merges(publishers.values())
    ]


def run_merge_duplicate_publishers(
    conn: Connection, logger: logging.Logger, *, merge: MergePublishers
) -> PhaseMetrics:
    """Fusionne chaque autre nom dans son titulaire, puis les éditeurs de même nom réduit, et journalise chaque fusion."""
    merges = find_publisher_aliases(conn)
    _apply(merges, logger, merge)
    same_name = find_same_name_publishers(conn)
    _apply(same_name, logger, merge)
    merged = len(merges) + len(same_name)
    metrics = PhaseMetrics()
    metrics.add(seen=merged, publishers_merged=merged)
    if merged:
        metrics.report = quantity(merged, "éditeur fusionné", "éditeurs fusionnés")
    return metrics


def _apply(merges: list[PublisherMerge], logger: logging.Logger, merge: MergePublishers) -> None:
    for m in merges:
        merge(m.target_id, m.source_id)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Éditeur fusionné : %d « %s » → %d « %s »",
            m.source_id,
            m.source,
            m.target_id,
            m.target,
            extra={"detail": True},
        )
