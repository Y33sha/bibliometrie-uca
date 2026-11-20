"""Phase `suspect_attributions` : attributions suspectes, recalculées à chaque run dans `suspect_contributions`.

Les publications des personnes à fiche RH forment des clusters par la partition de Leiden (`igraph`). Les clusters signalés par la règle du domaine (`signaled_clusters`) donnent le motif `cluster`. Pour les personnes ayant au moins un rejet, la cascade de départage désigne les publications proches des publications rejetées (`resembles_rejected`) : motif `rejected_publications`.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Mapping

import igraph
from sqlalchemy import Connection

from domain.persons.suspect_attributions import (
    SuspectReason,
    resembles_rejected,
    signaled_clusters,
)
from pipeline.graph import Block, Phase, Task, in_transaction
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.persons.store import (
    fetch_contribution_contexts,
    fetch_person_profiles,
)
from pipeline.transformation.persons.suspect_store import (
    fetch_candidate_contributions,
    fetch_clue_frequencies,
    fetch_publication_clues,
    fetch_rejected_profiles,
    write_suspect_contributions,
)

_SEED = 0
"""Graine de la partition de Leiden : un même graphe donne les mêmes clusters d'un run à l'autre."""


def leiden(n: int, weights: Mapping[tuple[int, int], float], resolution: float) -> list[int]:
    """Renvoie le cluster de chaque sommet du graphe pondéré, par la partition de Leiden (modularité)."""
    graph = igraph.Graph(n=n, edges=list(weights))
    graph.es["weight"] = list(weights.values())
    igraph.set_random_number_generator(random.Random(_SEED))  # noqa: S311 - partition reproductible
    partition = graph.community_leiden(
        objective_function="modularity", weights="weight", resolution=resolution, n_iterations=-1
    )
    return list(partition.membership)


def detect(conn: Connection, _logger: logging.Logger) -> PhaseMetrics:
    """Calcule les attributions suspectes et les écrit dans `suspect_contributions`."""
    rows: list[tuple[int, int, SuspectReason, int | None]] = []
    frequencies = fetch_clue_frequencies(conn)
    for person_id, publications in sorted(fetch_publication_clues(conn).items()):
        for number, cluster in enumerate(signaled_clusters(publications, frequencies, leiden), 1):
            rows += [(c, person_id, SuspectReason.CLUSTER, number) for c in cluster]
    in_clusters = {row[0] for row in rows}
    cluster_rows = len(rows)

    rejected_profiles = fetch_rejected_profiles(conn)
    candidates = [
        (c, p)
        for c, p in fetch_candidate_contributions(conn, rejected_profiles)
        if c not in in_clusters
    ]
    contexts = fetch_contribution_contexts(conn, [c for c, _ in candidates])
    own_profiles = fetch_person_profiles(conn, rejected_profiles)
    for contribution_id, person_id in candidates:
        context = contexts.get(contribution_id)
        if context is not None and resembles_rejected(
            person_id, context, own_profiles.get(person_id, []), rejected_profiles[person_id]
        ):
            rows.append((contribution_id, person_id, SuspectReason.REJECTED_PUBLICATIONS, None))

    write_suspect_contributions(conn, rows)
    persons = len({row[1] for row in rows})
    resembling = len(rows) - cluster_rows
    return PhaseMetrics(
        extras={
            "suspect_persons": persons,
            "suspect_in_clusters": cluster_rows,
            "suspect_resembling_rejected": resembling,
        },
        report=(
            f"{quantity(persons, 'personne')} : {quantity(cluster_rows, 'publication')} en clusters isolés,"
            f" {resembling} proches des publications rejetées"
        ),
    )


_CHILDREN = (
    Task(
        "detect_suspect_attributions",
        reads=(
            "contributions.id",
            "contributions.publication_id",
            "contributions.person_id",
            "contributions.resolution_mode",
            "contributions.roles",
            "aligned_source_contributions",
            "source_contributions.source_record_id",
            "source_contributions.contributor_information_id",
            "source_contribution_structures",
            "structures.structure_type",
            "source_contribution_hal_structures",
            "hal_structures",
            "source_records.publication_id",
            "source_records.source",
            "source_records.source_id",
            "contributor_information",
            "publications.id",
            "publications.serial_id",
            "publications.publication_year",
            "publication_subjects",
            "subjects.id",
            "subjects.vocabulary",
            "subjects.level",
            "persons",
            "hr_records",
            "rejected_contributions",
        ),
        writes=("suspect_contributions",),
        previous_runs=(
            # Publications, contributions, alignements et sujets supprimés, enregistrements sources détachés par `finalize.purge_publications`.
            "publications.id",
            "publications.serial_id",
            "publications.publication_year",
            "contributions",
            "aligned_source_contributions",
            "publication_subjects",
            "source_records.publication_id",
        ),
        run=in_transaction(detect),
        label="Attributions suspectes",
    ),
)


PHASE = Phase(
    "suspect_attributions",
    "Attributions suspectes : clusters isolés, ressemblance avec les publications rejetées",
    _CHILDREN,
    Block.ENTITIES,
)
