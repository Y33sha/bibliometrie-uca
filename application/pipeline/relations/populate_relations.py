"""Phase `relations` — population de `publication_relations` depuis les relations déclarées.

Tourne après `publications` : les `source_publications` sont rattachées à leur publication
canonique, et les DOI cibles sont résolus en `publication_id` quand ils sont au corpus.

Trois signaux peuplent la table :

- **Signal #1 — relations déclarées par les sources** : DataCite `meta.related_identifiers` et
  Crossref `meta.relation`, converties vers le vocabulaire canonique par
  `domain.publications.relations`.
- **Signal #2 — clés de confirmation partagées** : deux publications distinctes (DOI distincts)
  qui partagent une clé (hal_id, arXiv, PMID, NNT) sans avoir fusionné sont apparentées ; le type
  se déduit de leur couple de `doc_type` (`infer_shared_key_relation`).
- **Signal #3 — rapprochement erratum par titre** : un erratum sans relation déclarée ni clé
  partagée est relié à l'œuvre qu'il corrige quand son titre en reproduit le titre verbatim (le
  `title_normalized` du parent est un suffixe), sous garde d'ambiguïté (un seul parent substantiel
  au même titre). Type `is_correction_of`. La sélection (avec sa garde) vit dans le SQL du port.

Les relations même-œuvre (versions, formes variantes, pièces de package) sont absentes des trois
signaux : elles sont traitées en déduplication à la phase `metadata_correction`, en amont.

Reconstruction complète à chaque run (table dérivée) : chaque signal purge ses propres relations
(par `source`) puis les réécrit, donc idempotent et sans dérive.
"""

import logging

from sqlalchemy import Connection

from application.ports.pipeline.relations import (
    DeclaredRelationSource,
    ErratumTitleMatch,
    PublicationRelationsQueries,
    RelationEdge,
    SharedKeyPair,
)
from domain.publications.identifiers import clean_doi
from domain.publications.relations import (
    RelationType,
    extract_crossref_relations,
    extract_datacite_relations,
    infer_shared_key_relation,
)


def _build_declared_edges(sources: list[DeclaredRelationSource]) -> list[RelationEdge]:
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
    return edges


def _build_shared_key_edges(
    pairs: list[SharedKeyPair], declared_pairs: set[frozenset[int]]
) -> list[RelationEdge]:
    """Une arête dirigée par paire partageant une clé. `infer_shared_key_relation` donne le type et
    le sujet (`"a"`, `"b"`, ou `"sym"` symétrique — orienté depuis A, le plus petit id). Les paires
    hors scope (peer-review) sont écartées, ainsi que les `is_related_to` (type vague « à qualifier »)
    sur une paire déjà typée précisément par le signal #1 — sinon doublon redondant."""
    edges: list[RelationEdge] = []
    for pair in pairs:
        inferred = infer_shared_key_relation(pair.a_doc_type, pair.b_doc_type)
        if inferred is None:
            continue
        relation, subject = inferred
        if (
            relation is RelationType.IS_RELATED_TO
            and frozenset((pair.a_id, pair.b_id)) in declared_pairs
        ):
            continue
        if subject == "b":
            from_id, target = pair.b_id, pair.a_doi
        else:  # "a" ou "sym" : A est le sujet (a_id < b_id rend l'orientation stable)
            from_id, target = pair.a_id, pair.b_doi
        cleaned = clean_doi(target)
        if cleaned:
            edges.append(RelationEdge(from_id, relation.value, cleaned, "shared_key"))
    return edges


def _build_title_match_edges(matches: list[ErratumTitleMatch]) -> list[RelationEdge]:
    """Une arête `erratum is_correction_of parent` par rapprochement de titre. La cible est le DOI
    du parent (résolu en `publication_id` à l'insertion). Un DOI parent malformé est écarté."""
    edges: list[RelationEdge] = []
    for match in matches:
        cleaned = clean_doi(match.parent_doi)
        if cleaned:
            edges.append(
                RelationEdge(
                    match.erratum_id, RelationType.IS_CORRECTION_OF.value, cleaned, "title_match"
                )
            )
    return edges


def run(conn: Connection, queries: PublicationRelationsQueries, logger: logging.Logger) -> None:
    sources = queries.fetch_declared_relation_sources(conn)
    declared_edges = _build_declared_edges(sources)
    written_declared = queries.replace_declared_relations(conn, declared_edges)

    pairs = queries.fetch_shared_key_pairs(conn)
    declared_pairs = queries.fetch_declared_related_pairs(conn)
    shared_edges = _build_shared_key_edges(pairs, declared_pairs)
    written_shared = queries.replace_shared_key_relations(conn, shared_edges)

    matches = queries.fetch_erratum_title_matches(conn)
    title_edges = _build_title_match_edges(matches)
    written_title = queries.replace_title_match_relations(conn, title_edges)

    conn.commit()
    logger.info(
        "✓ relations : déclarées %d (%d arêtes / %d source_publications) ; "
        "clés partagées %d (%d paires) ; erratums par titre %d (%d rapprochements)",
        written_declared,
        len(declared_edges),
        len(sources),
        written_shared,
        len(pairs),
        written_title,
        len(matches),
    )
