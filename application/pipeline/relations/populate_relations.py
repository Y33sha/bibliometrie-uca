"""Phase `relations` — population de `publication_relations` depuis les relations déclarées.

Tourne après `publications` : les `source_publications` sont rattachées à leur publication
canonique, et les DOI cibles sont résolus en `publication_id` quand ils sont au corpus.

Source des relations à ce stade : les relations **déclarées par les sources** (signal #1) —
DataCite `meta.related_identifiers` et Crossref `meta.relation` — converties vers le
vocabulaire canonique par `domain.publications.relations`. Les relations même-œuvre
(versions, formes variantes, pièces de package) en sont absentes : elles sont traitées en
déduplication à la phase `metadata_correction`, en amont.

Reconstruction complète à chaque run (table dérivée) : la passe purge les relations
déclarées puis les réécrit, donc idempotente et sans dérive.
"""

import logging

from sqlalchemy import Connection

from application.ports.pipeline.relations import PublicationRelationsQueries, RelationEdge
from domain.publications.relations import (
    extract_crossref_relations,
    extract_datacite_relations,
)


def run(conn: Connection, queries: PublicationRelationsQueries, logger: logging.Logger) -> None:
    sources = queries.fetch_declared_relation_sources(conn)
    edges: list[RelationEdge] = []
    for sp in sources:
        if sp.source == "datacite":
            relations = extract_datacite_relations(sp.meta)
        elif sp.source == "crossref":
            relations = extract_crossref_relations(sp.meta)
        else:
            continue
        edges.extend(
            RelationEdge(sp.publication_id, rel_type.value, target_doi, sp.source)
            for rel_type, target_doi in relations
        )

    written = queries.replace_declared_relations(conn, edges)
    conn.commit()
    logger.info(
        "✓ relations : %d relations écrites (%d arêtes candidates depuis %d source_publications)",
        written,
        len(edges),
        len(sources),
    )
