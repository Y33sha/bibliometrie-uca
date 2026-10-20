"""Arbitrage des identifiants de personne, avant la cascade : identifiants mal placés et conflits d'attribution.

Le consensus d'une valeur d'identifiant est le nom que contiennent strictement plus de signatures que chacun des autres (`consensus_name`). Il est calculé une fois sur le snapshot (`compute_identifier_consensus`).

Une identité dont le nom désigne une autre personne que celle du consensus contient la valeur par erreur. Ses signatures la neutralisent avec le motif `misplaced` (`requalify_misplaced_identifiers`).

Un conflit (`IdentifierConflict`) est une valeur qu'une signature du candidat contient et qu'une autre personne détient. Le même consensus le tranche (`resolve_identifier_transfers`) : la valeur va au candidat quand le consensus désigne le candidat seul. Seules les attributions `pending` sont transférables. Les signatures affectées repassent à NULL, et la cascade les re-résout.

L'arbitrage est ordre-indépendant : le consensus agrège tous les porteurs, et le calcul repart des données à chaque exécution.
"""

import logging
from collections import defaultdict
from typing import NamedTuple

from sqlalchemy import Connection

from domain.persons.identifiers import PERSON_IDENTIFIER_TYPES, IdentifierOrigin
from domain.persons.matching import (
    STRONG_PERSON_IDENTIFIER_TYPES,
    consensus_name,
    form_matches_person,
    identifier_misplaced,
)
from infrastructure.repositories.person_repository import PgPersonRepository
from pipeline.runtime.observability.libelles import (
    BRANCHE,
    DERNIERE_BRANCHE,
    accord,
    etape,
    forme,
    rien_a_faire,
)
from pipeline.runtime.observability.progression import attente
from pipeline.transformation.persons.matching import PersonsMatchingQueries

IdentifierConsensus = dict[tuple[str, str], str]
"""`{(id_type, id_value): nom du consensus}` pour les valeurs dont le consensus désigne un nom."""


def compute_identifier_consensus(
    conn: Connection, queries: PersonsMatchingQueries
) -> IdentifierConsensus:
    """Consensus de chaque valeur d'identifiant, tous types confondus."""
    consensus: IdentifierConsensus = {}
    for id_type in PERSON_IDENTIFIER_TYPES:
        for value, votes in queries.fetch_identifier_votes(conn, id_type).items():
            if (name := consensus_name(votes)) is not None:
                consensus[(id_type, value)] = name
    return consensus


def requalify_misplaced_identifiers(
    conn: Connection,
    consensus: IdentifierConsensus,
    queries: PersonsMatchingQueries,
) -> dict[str, int]:
    """Neutralise les identifiants mal placés et détache les signatures qu'ils ont pu rattacher.

    Retourne `{neutralized, detached}` : le nombre de signatures qui gagnent un identifiant neutralisé, et de celles qui sont détachées pour que la cascade les re-résolve.
    """
    misplaced: dict[int, list[str]] = defaultdict(list)
    for id_type in PERSON_IDENTIFIER_TYPES:
        for identity in queries.fetch_identity_identifiers(conn, id_type):
            if identifier_misplaced(identity.name, consensus.get((id_type, identity.value))):
                misplaced[identity.identity_id].append(id_type)

    written = queries.write_misplaced_neutralizations(conn, misplaced)
    detached = (
        queries.detach_source_authorships(conn, written.to_detach) if written.to_detach else 0
    )
    return {"neutralized": written.neutralized, "detached": detached}


class IdentifierConflict(NamedTuple):
    """Une valeur d'identifiant qu'une signature du candidat contient est déjà attribuée à une autre personne.

    L'arbitrage par consensus des porteurs la transfère au candidat si le consensus le désigne. Une attribution `confirmed` n'est jamais transférée.
    """

    id_type: str
    id_value: str
    candidate_person_id: int
    owner_person_id: int
    owner_status: str


def detect_identifier_conflicts(
    conn: Connection, queries: PersonsMatchingQueries
) -> list[IdentifierConflict]:
    """Balaye le snapshot pour tous les conflits d'attribution d'identifiant.

    Chaque personne qui détient des signatures d'une valeur d'identifiant sans en être le propriétaire attribué est un conflit. Lecture d'agrégat — le résultat ne dépend pas de la séquence de la cascade —, à confier ensuite à `resolve_identifier_transfers` qui tranche par consensus. Partagé par le pipeline (balayage frontal) et la remédiation du stock.
    """
    conflicts: list[IdentifierConflict] = []
    for id_type in STRONG_PERSON_IDENTIFIER_TYPES:
        owners = queries.fetch_identifier_owners(conn, id_type)
        if not owners:
            continue
        for id_value, bearer_person_id in queries.fetch_identifier_bearer_persons(conn, id_type):
            owner = owners.get(id_value)
            if owner is None or bearer_person_id == owner[0]:
                continue
            conflicts.append(
                IdentifierConflict(id_type, id_value, bearer_person_id, owner[0], owner[1])
            )
    return conflicts


def resolve_identifier_transfers(
    conn: Connection,
    conflicts: list[IdentifierConflict],
    *,
    consensus: IdentifierConsensus,
    queries: PersonsMatchingQueries,
    repo: PgPersonRepository,
    logger: logging.Logger,
) -> dict[str, int]:
    """Arbitre les conflits d'attribution collectés et transfère les identifiants captés, d'après le `consensus` des valeurs d'identifiant (`compute_identifier_consensus`).

    Retourne les compteurs `{conflicts, pending, transferred}`.
    """
    pending = [c for c in conflicts if c.owner_status == "pending"]
    if not pending:
        rien_a_faire(logger)
        return {"conflicts": len(conflicts), "pending": 0, "transferred": 0}

    # Nom-prénom + formes confirmées des personnes impliquées (propriétaires et candidats).
    person_ids = {c.candidate_person_id for c in pending} | {c.owner_person_id for c in pending}
    persons = queries.fetch_person_name_forms(conn, sorted(person_ids))

    # Une valeur peut apparaître dans plusieurs conflits (candidats distincts) : on regroupe pour trancher une seule fois, la personne du consensus l'emportant.
    candidates_by_value: dict[tuple[str, str], set[int]] = defaultdict(set)
    owner_by_value: dict[tuple[str, str], int] = {}
    for c in pending:
        key = (c.id_type, c.id_value)
        candidates_by_value[key].add(c.candidate_person_id)
        owner_by_value[key] = c.owner_person_id

    transferred = 0
    for key, candidates in candidates_by_value.items():
        cons = consensus.get(key)
        if cons is None:
            continue
        owner_id = owner_by_value[key]
        owner = persons.get(owner_id)
        if owner is not None and form_matches_person(cons, *owner):
            continue  # le propriétaire est la personne du consensus → on garde
        matching = [
            pid
            for pid in candidates
            if (p := persons.get(pid)) is not None and form_matches_person(cons, *p)
        ]
        if len(matching) != 1:
            continue  # aucun candidat du consensus, ou ambiguïté → triage manuel
        target = matching[0]
        id_type, id_value = key
        ident = repo.find_identifier(id_type, id_value)
        if ident is None or ident.person_id != owner_id:
            continue  # l'état a changé entre la collecte et la résolution
        ident.transfer_to(target, source=IdentifierOrigin.AUTO)
        repo.update_identifier(ident)
        # Les signatures affectées, restées sur l'ancien propriétaire et résolues par identifiant, repassent à NULL : la cascade les re-résout vers le nouveau propriétaire.
        detached = queries.null_identifier_signatures(conn, id_type, id_value, owner_id)
        logger.info(
            "%sTransfert %s=%s : personne %d → %d (consensus %r), %s %s",
            BRANCHE,
            id_type,
            id_value,
            owner_id,
            target,
            cons,
            accord(detached, "signature"),
            forme(detached, "détachée"),
        )
        transferred += 1

    # Un conflit dont l'attribution est confirmée par l'admin est tranché : seuls les autres comptent.
    logger.info(
        "%s%s à arbitrer → %s %s",
        DERNIERE_BRANCHE,
        accord(len(pending), "conflit"),
        accord(transferred, "identifiant"),
        forme(transferred, "transféré"),
    )
    return {"conflicts": len(conflicts), "pending": len(pending), "transferred": transferred}


def arbitrate_identifier_conflicts(
    conn: Connection,
    queries: PersonsMatchingQueries,
    logger: logging.Logger,
    *,
    repo: PgPersonRepository,
) -> dict[str, int]:
    """Neutralise les identifiants mal placés, puis tranche les conflits d'attribution d'identifiant par transfert.

    Retourne `{neutralized, detached, transferred}`. Le commit est laissé au caller.
    """
    etape(logger, "Identifiants mal placés et conflits d'attribution")
    with attente(BRANCHE, logger) as ligne:
        consensus = compute_identifier_consensus(conn, queries)
        requalified = requalify_misplaced_identifiers(conn, consensus, queries)
        if requalified["neutralized"]:
            ligne.conclut(
                f"{BRANCHE}Identifiants mal placés neutralisés sur "
                f"{accord(requalified['neutralized'], 'signature')}"
            )
        else:
            ligne.efface()
    with attente(BRANCHE, logger) as ligne:
        conflicts = detect_identifier_conflicts(conn, queries)
        ligne.efface()
    transferred = resolve_identifier_transfers(
        conn, conflicts, consensus=consensus, queries=queries, repo=repo, logger=logger
    )["transferred"]

    return {
        "neutralized": requalified["neutralized"],
        "detached": requalified["detached"],
        "transferred": transferred,
    }
