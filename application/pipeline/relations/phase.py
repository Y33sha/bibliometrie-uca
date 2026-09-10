"""Phase `relations` — population de `publication_relations` depuis les relations déclarées.

Tourne après `publications` : les `source_publications` sont rattachées à leur publication canonique, et les DOI cibles sont résolus en `publication_id` quand ils sont au corpus.

Trois signaux peuplent la table :

- **Signal #1 — relations déclarées par les sources** : DataCite `meta.related_identifiers` et Crossref `meta.relation`, converties vers le vocabulaire canonique par `domain.publications.relations`.
- **Signal #2 — clés de confirmation partagées** : deux publications distinctes (DOI distincts) qui partagent une clé (hal_id, arXiv, PMID, NNT) sans avoir fusionné sont apparentées ; le type se déduit de leur couple de `doc_type` (`infer_shared_key_relation`).
- **Signal #3 — rapprochement par titre** : une publication dépendante sans relation déclarée ni clé partagée est reliée à l'œuvre dont elle dépend par le titre — un erratum à l'article qu'il corrige (`is_correction_of`, titre parent en suffixe après « Erratum: »…), un preprint à sa version publiée (`is_preprint_of`, titre identique). Sous garde d'ambiguïté (un seul parent substantiel au même titre). La sélection (avec sa garde) vit dans le SQL du port.

Les relations de même œuvre à préfixe égal (versions, formes variantes, pièces de package) relèvent de la déduplication, à la phase `metadata_correction`. Entre deux registrants, `IsVersionOf` et `IsVariantFormOf` relient deux œuvres : quand les deux ont leur publication au corpus, le signal #1 les type par leur couple de `doc_type`, comme un preprint arXiv et l'article publié.

Reconstruction complète à chaque run (table dérivée) : la table est purgée puis réécrite depuis les trois signaux réunis, en une transaction — idempotent et sans dérive.
"""

import logging

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape, forme
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.relations import (
    DeclaredRelationSource,
    DoiPublication,
    PublicationRelationsQueries,
    RelationEdge,
    RelationsRebuild,
    SharedKeyPair,
    TitleMatch,
)
from application.ports.pipeline.transaction import OpenTransaction
from domain.publications.identifiers import clean_doi
from domain.publications.relations import (
    DEPENDENT_DOC_TYPE_RELATIONS,
    RELATION_PAIR_LABELS,
    RelationType,
    extract_crossref_relations,
    extract_datacite_distinct_works,
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


def _distinct_work_targets(sources: list[DeclaredRelationSource]) -> list[str]:
    """DOI que les notices DataCite déclarent comme autre forme de leur œuvre, chez un autre registrant."""
    return sorted(
        {
            doi
            for sp in sources
            if sp.source == "datacite"
            for doi in extract_datacite_distinct_works(sp.meta, sp.doi)
        }
    )


def _build_distinct_work_edges(
    sources: list[DeclaredRelationSource], publications_by_doi: dict[str, DoiPublication]
) -> list[RelationEdge]:
    """Relie une notice DataCite à la forme d'un autre registrant qu'elle déclare de la même œuvre, quand cette forme a sa publication au corpus.

    Le type se déduit du couple de `doc_type`, comme pour une clé partagée : un preprint face à l'article publié donne `is_preprint_of`.
    """
    edges: list[RelationEdge] = []
    for sp in sources:
        if sp.source != "datacite":
            continue
        for target_doi in extract_datacite_distinct_works(sp.meta, sp.doi):
            target = publications_by_doi.get(target_doi)
            if target is None:
                continue
            inferred = infer_shared_key_relation(sp.doc_type, target.doc_type)
            if inferred is None:
                continue
            relation, subject = inferred
            if subject == "b":
                edges.append(
                    RelationEdge(
                        target.id,
                        relation.value,
                        sp.doi,
                        "datacite",
                        target_publication_id=sp.publication_id,
                    )
                )
            else:
                edges.append(
                    RelationEdge(sp.publication_id, relation.value, target_doi, "datacite")
                )
    return edges


def _build_shared_key_edges(
    pairs: list[SharedKeyPair], declared_pairs: set[frozenset[int]]
) -> list[RelationEdge]:
    """Une arête dirigée par paire partageant une clé. `infer_shared_key_relation` donne le type et le sujet (`"a"`, `"b"`, ou `"sym"` symétrique — orienté depuis A, le plus petit id). Les paires hors scope (peer-review) sont écartées, ainsi que les `is_related_to` (type vague « à qualifier ») sur une paire déjà typée précisément par le signal #1 — sinon doublon redondant."""
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


def _build_title_match_edges(
    matches: list[TitleMatch], relation_type: RelationType
) -> list[RelationEdge]:
    """Une arête `enfant relation_type parent` par rapprochement de titre. La cible est désignée par le `publication_id` du parent (au corpus), avec son DOI quand il en a un — l'unicité dédoublonne alors contre une éventuelle relation déjà posée vers ce même parent par un autre signal."""
    return [
        RelationEdge(
            match.child_id,
            relation_type.value,
            clean_doi(match.parent_doi) if match.parent_doi else None,
            "title_match",
            target_publication_id=match.parent_id,
        )
        for match in matches
    ]


def run(
    open_tx: OpenTransaction, queries: PublicationRelationsQueries, logger: logging.Logger
) -> PhaseMetrics:
    """Reconstruit `publication_relations` depuis les trois signaux, en une transaction, et retourne les compteurs de la phase (répartition par type de relation dans `details`)."""
    with open_tx() as conn:
        sources = queries.fetch_declared_relation_sources(conn)
        declared_edges = _build_declared_edges(sources)
        publications_by_doi = queries.fetch_publications_by_doi(
            conn, _distinct_work_targets(sources)
        )
        declared_edges += _build_distinct_work_edges(sources, publications_by_doi)

        pairs = queries.fetch_shared_key_pairs(conn)
        declared_pairs = queries.fetch_declared_related_pairs(conn)
        shared_edges = _build_shared_key_edges(pairs, declared_pairs)

        erratum_matches = queries.fetch_erratum_title_matches(conn)
        preprint_matches = queries.fetch_preprint_title_matches(conn)
        title_edges = _build_title_match_edges(
            erratum_matches, DEPENDENT_DOC_TYPE_RELATIONS["erratum"]
        ) + _build_title_match_edges(preprint_matches, DEPENDENT_DOC_TYPE_RELATIONS["preprint"])

        # L'ordre déclarées → clés partagées → titre fixe la priorité de dédup (`ON CONFLICT`).
        rebuild = queries.rebuild_relations(conn, declared_edges + shared_edges + title_edges)
        by_type = queries.count_by_relation_type(conn)

    _log_changes(rebuild, logger)

    metrics = PhaseMetrics()
    metrics.add(new=sum(count for _, count in rebuild.added_by_type))
    metrics.details["table"] = {
        "rows": [{"key": relation_type, "count": count} for relation_type, count in by_type]
    }
    # La sous-étape porte le détail des nouvelles relations : une ligne de clôture le répéterait.
    metrics.resume = ""
    return metrics


def _log_changes(rebuild: RelationsRebuild, logger: logging.Logger) -> None:
    """Écrit ce que la reconstruction a changé : les relations ajoutées par nature du lien, puis celles qui ont disparu.

    La table étant reconstruite entière à chaque run, le nombre d'arêtes écrites ne dit rien : presque toutes s'y trouvaient déjà. Seul l'écart avec l'état précédent porte une information.
    """
    ajoutees = _count_by_pair_label(rebuild.added_by_type)
    total = sum(ajoutees.values())
    if total:
        etape(
            logger,
            "%s entre publications",
            accord(total, "nouvelle relation", "nouvelles relations"),
        )
        logger.info("")
        largeur = max(len(str(count)) for count in ajoutees.values())
        for libelle, count in ajoutees.items():
            logger.info("     %s %s", str(count).rjust(largeur), libelle)
    else:
        etape(logger, "Relations entre publications")

    if rebuild.removed:
        if total:
            logger.info("")
        logger.info(
            "%s%s %s",
            DERNIERE_BRANCHE,
            accord(rebuild.removed, "relation"),
            forme(rebuild.removed, "retirée"),
        )
    elif not total:
        logger.info("%saucun changement", DERNIERE_BRANCHE)


def _count_by_pair_label(added_by_type: list[tuple[str, int]]) -> dict[str, int]:
    """Regroupe les compteurs par nature du lien : un type et son inverse désignent le même."""
    par_libelle: dict[str, int] = {}
    for relation_type, count in added_by_type:
        libelle = RELATION_PAIR_LABELS.get(RelationType(relation_type), relation_type)
        par_libelle[libelle] = par_libelle.get(libelle, 0) + count
    return dict(sorted(par_libelle.items(), key=lambda item: item[1], reverse=True))
