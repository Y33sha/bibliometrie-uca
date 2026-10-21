"""Phase `relations` — population de `publication_relations` depuis les relations déclarées.

Tourne après `publications` : les `source_records` sont rattachées à leur publication canonique, et les DOI cibles sont résolus en `publication_id` quand ils sont au corpus.

Trois signaux peuplent la table :

- **Signal #1 — relations déclarées par les sources** : DataCite `source_extras.related_identifiers` et Crossref `source_extras.relation`, converties vers le vocabulaire canonique par `domain.publications.relations`.
- **Signal #2 — clés de confirmation partagées** : deux publications distinctes qui partagent une clé (hal_id, arXiv, PMID, NNT) sont apparentées ; le type se déduit de leur couple de `doc_type` (`infer_shared_key_relation`).
- **Signal #3 — rapprochement par titre** : une publication dépendante sans relation déclarée ni clé partagée est reliée à l'œuvre dont elle dépend par le titre — un erratum à l'article qu'il corrige (`is_correction_of`, titre parent en suffixe après « Erratum: »…), un preprint à sa version publiée (`is_preprint_of`, titre identique). Sous garde d'ambiguïté (un seul parent substantiel au même titre). La sélection (avec sa garde) vit dans le SQL du port.

Les relations de même œuvre (versions, formes variantes, pièces de package) relèvent de la déduplication, à la phase `metadata_correction`. Quand `IsVersionOf` ou `IsVariantFormOf` relient deux œuvres (cf. `meme_oeuvre_declaree`), le signal #1 les type par leur couple de `doc_type`, comme un preprint arXiv et l'article publié.

Reconstruction complète à chaque run (table dérivée) : la table est purgée puis réécrite depuis les trois signaux réunis, en une transaction — idempotent et sans dérive.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

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
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH, inflect, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.publications.relations_queries import (
    DeclaredRelationSource,
    DoiPublication,
    PublicationRelationsQueries,
    RelationEdge,
    RelationsRebuild,
    SharedKeyPair,
    TitleMatch,
)


def _build_declared_edges(sources: list[DeclaredRelationSource]) -> list[RelationEdge]:
    edges: list[RelationEdge] = []
    for source_record in sources:
        if source_record.source == "datacite":
            relations = extract_datacite_relations(source_record.source_extras)
        elif source_record.source == "crossref":
            relations = extract_crossref_relations(source_record.source_extras)
        else:
            continue
        edges.extend(
            RelationEdge(
                source_record.publication_id, rel_type.value, target_doi, source_record.source
            )
            for rel_type, target_doi in relations
        )
    return edges


def _distinct_work_targets(sources: list[DeclaredRelationSource]) -> list[str]:
    """DOI que les enregistrements sources DataCite déclarent comme autre forme de leur œuvre, chez un autre registrant."""
    return sorted(
        {
            doi
            for source_record in sources
            if source_record.source == "datacite"
            for doi in extract_datacite_distinct_works(
                source_record.source_extras, source_record.doi, source_record.source_record_doc_type
            )
        }
    )


def _build_distinct_work_edges(
    sources: list[DeclaredRelationSource], publications_by_doi: dict[str, DoiPublication]
) -> list[RelationEdge]:
    """Relie un enregistrement source DataCite à la forme d'un autre registrant qu'il déclare de la même œuvre.

    Le type se déduit du couple de `doc_type`, comme pour une clé partagée : un preprint face à l'article publié donne `is_preprint_of`. Une cible absente du corpus a un type inconnu : face à elle, un preprint donne `is_preprint_of`, les autres enregistrements sources `is_related_to`.
    """
    edges: list[RelationEdge] = []
    for source_record in sources:
        if source_record.source != "datacite":
            continue
        for target_doi in extract_datacite_distinct_works(
            source_record.source_extras, source_record.doi, source_record.source_record_doc_type
        ):
            target = publications_by_doi.get(target_doi)
            inferred = infer_shared_key_relation(
                source_record.doc_type, target.doc_type if target else None
            )
            if inferred is None:
                continue
            relation, subject = inferred
            if subject == "b":
                # Une cible typée est au corpus : c'est elle qui porte la relation dirigée.
                assert target is not None
                edges.append(
                    RelationEdge(
                        target.id,
                        relation.value,
                        source_record.doi,
                        "datacite",
                        target_publication_id=source_record.publication_id,
                    )
                )
            else:
                edges.append(
                    RelationEdge(
                        source_record.publication_id, relation.value, target_doi, "datacite"
                    )
                )
    return edges


def _declared_pairs(
    edges: list[RelationEdge], publications_by_doi: dict[str, DoiPublication]
) -> set[frozenset[int]]:
    """Paires de publications que relient les relations déclarées (signal #1), la cible résolue par son DOI."""
    pairs: set[frozenset[int]] = set()
    for edge in edges:
        target = edge.target_publication_id
        if target is None and edge.target_doi is not None:
            resolved = publications_by_doi.get(edge.target_doi)
            target = resolved.id if resolved else None
        if target is not None:
            pairs.add(frozenset((edge.from_publication_id, target)))
    return pairs


def _build_shared_key_edges(
    pairs: list[SharedKeyPair], declared_pairs: set[frozenset[int]]
) -> list[RelationEdge]:
    """Une arête dirigée par paire partageant une clé. La cible est désignée par son `publication_id`, avec son DOI quand elle en a un. `infer_shared_key_relation` donne le type et le sujet (`"a"`, `"b"`, ou `"sym"` symétrique — orienté depuis A, le plus petit id). Les paires hors scope (peer-review) sont écartées, ainsi que les `is_related_to` (type vague « à qualifier ») sur une paire déjà typée précisément par le signal #1 — sinon doublon redondant."""
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
            from_id, target_id, target_doi = pair.b_id, pair.a_id, pair.a_doi
        else:  # "a" ou "sym" : A est le sujet (a_id < b_id rend l'orientation stable)
            from_id, target_id, target_doi = pair.a_id, pair.b_id, pair.b_doi
        edges.append(
            RelationEdge(
                from_id,
                relation.value,
                clean_doi(target_doi) if target_doi else None,
                "shared_key",
                target_publication_id=target_id,
            )
        )
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


@dataclass(frozen=True)
class RelationsPhase:
    queries: PublicationRelationsQueries

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute la tâche `relations.rebuild`."""
        return run_tasks("relations", {"relations.rebuild": TaskStep(self._rebuild)}, ctx)[
            "relations.rebuild"
        ]

    def _rebuild(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        """Reconstruit `publication_relations` depuis les trois signaux, en une transaction, et retourne les compteurs de la phase (répartition par type de relation dans `details`)."""
        queries = self.queries
        with ctx.open_tx() as conn:
            sources = queries.fetch_declared_relation_sources(conn)
            declared_edges = _build_declared_edges(sources)
            publications_by_doi = queries.fetch_publications_by_doi(
                conn,
                sorted(
                    {
                        *_distinct_work_targets(sources),
                        *(edge.target_doi for edge in declared_edges if edge.target_doi),
                    }
                ),
            )
            declared_edges += _build_distinct_work_edges(sources, publications_by_doi)

            pairs = queries.fetch_shared_key_pairs(conn)
            shared_edges = _build_shared_key_edges(
                pairs, _declared_pairs(declared_edges, publications_by_doi)
            )

            erratum_matches = queries.fetch_erratum_title_matches(conn)
            preprint_matches = queries.fetch_preprint_title_matches(conn)
            title_edges = _build_title_match_edges(
                erratum_matches, DEPENDENT_DOC_TYPE_RELATIONS["erratum"]
            ) + _build_title_match_edges(preprint_matches, DEPENDENT_DOC_TYPE_RELATIONS["preprint"])

            # L'ordre déclarées → clés partagées → titre fixe la priorité de dédup (`ON CONFLICT`).
            rebuild = queries.rebuild_relations(conn, declared_edges + shared_edges + title_edges)
            by_type = queries.count_by_relation_type(conn)

        _log_changes(rebuild, ctx.logger)

        metrics = PhaseMetrics()
        metrics.add(new=sum(count for _, count in rebuild.added_by_type))
        metrics.details["table"] = {
            "rows": [{"key": relation_type, "count": count} for relation_type, count in by_type]
        }
        return metrics


def _log_changes(rebuild: RelationsRebuild, logger: logging.Logger) -> None:
    """Écrit ce que la reconstruction a changé : les relations ajoutées par nature du lien, puis celles qui ont disparu.

    La table étant reconstruite entière à chaque run, le nombre d'arêtes écrites ne dit rien : presque toutes s'y trouvaient déjà. Seul l'écart avec l'état précédent porte une information.
    """
    ajoutees = _count_by_pair_label(rebuild.added_by_type)
    total = sum(ajoutees.values())
    if total:
        step(
            logger,
            "%s entre publications",
            quantity(total, "nouvelle relation", "nouvelles relations"),
        )
        logger.info("")
        largeur = max(len(str(count)) for count in ajoutees.values())
        for label, count in ajoutees.items():
            logger.info("     %s %s", str(count).rjust(largeur), label)
    else:
        step(logger, "Relations entre publications")

    if rebuild.removed:
        if total:
            logger.info("")
        logger.info(
            "%s%s %s",
            LAST_BRANCH,
            quantity(rebuild.removed, "relation"),
            inflect(rebuild.removed, "retirée"),
        )
    elif not total:
        logger.info("%saucun changement", LAST_BRANCH)


def _count_by_pair_label(added_by_type: list[tuple[str, int]]) -> dict[str, int]:
    """Regroupe les compteurs par nature du lien : un type et son inverse désignent le même."""
    par_libelle: dict[str, int] = {}
    for relation_type, count in added_by_type:
        label = RELATION_PAIR_LABELS.get(RelationType(relation_type), relation_type)
        par_libelle[label] = par_libelle.get(label, 0) + count
    return dict(sorted(par_libelle.items(), key=lambda item: item[1], reverse=True))


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return RelationsPhase(PublicationRelationsQueries())
