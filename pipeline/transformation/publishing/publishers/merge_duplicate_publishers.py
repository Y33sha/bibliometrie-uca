"""Sous-étape de la phase `publishing` : fusion des autres noms d'un éditeur dans le titulaire de ses préfixes.

Un éditeur nommé par les sources, sans préfixe DOI, rejoint le titulaire des préfixes Crossref de ses enregistrements sources quand leurs noms sont compatibles (`domain.publishers.aliases`). Les préfixes des plateformes d'éditeurs sont écartés : ils désignent la plateforme. La fusion est celle de l'administration des éditeurs, sans les revues homonymes : les formes de nom passent au titulaire, retrouvé ensuite par ce nom. Le journal garde les deux noms.
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.platforms.registry import is_publisher_platform_prefix
from domain.publishers.aliases import compatible_publisher_names, prefix_holder
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics

LABEL = "Autres noms des éditeurs"
"""Libellé de la sous-étape dans le journal de la phase."""

MergePublishers = Callable[[int, int], None]
"""`(cible, source)` : fusionne l'éditeur source dans la cible et valide la transaction."""

# Enregistrements sources qui nomment un éditeur sans préfixe DOI, par titulaire du préfixe Crossref de leur publication.
_EVIDENCE = text("""
    SELECT sr.publisher_id AS named_id, dp.publisher_id AS holder_id, dp.prefix, count(*) AS records
    FROM source_records sr
    JOIN publications p ON p.id = sr.publication_id
    JOIN doi_prefixes dp ON dp.prefix = p.doi_prefix AND dp.ra = 'Crossref'
    WHERE sr.publisher_id IS NOT NULL
      AND dp.publisher_id IS NOT NULL
      AND dp.publisher_id <> sr.publisher_id
      AND NOT EXISTS (SELECT 1 FROM doi_prefixes own WHERE own.publisher_id = sr.publisher_id)
    GROUP BY 1, 2, 3
""")

_NAMES = text("SELECT id, name FROM publishers WHERE id = ANY(:ids)")


class PublisherAlias(NamedTuple):
    """Un autre nom d'un éditeur : l'éditeur nommé, absorbé par le titulaire du préfixe."""

    named_id: int
    named: str
    holder_id: int
    holder: str


def find_publisher_aliases(conn: Connection) -> list[PublisherAlias]:
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
        PublisherAlias(named_id, names[named_id], holder_id, names[holder_id])
        for named_id, holder_id in sorted(pairs.items())
        if compatible_publisher_names(names[named_id], names[holder_id])
    ]


def run_merge_duplicate_publishers(
    conn: Connection, logger: logging.Logger, *, merge: MergePublishers
) -> PhaseMetrics:
    """Fusionne chaque autre nom dans son titulaire et journalise chacun."""
    aliases = find_publisher_aliases(conn)
    metrics = PhaseMetrics()
    for alias in aliases:
        merge(alias.holder_id, alias.named_id)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Éditeur fusionné : %d « %s » → %d « %s »",
            alias.named_id,
            alias.named,
            alias.holder_id,
            alias.holder,
            extra={"detail": True},
        )
    metrics.add(seen=len(aliases), publishers_merged=len(aliases))
    if aliases:
        metrics.report = quantity(len(aliases), "éditeur fusionné", "éditeurs fusionnés")
    return metrics
