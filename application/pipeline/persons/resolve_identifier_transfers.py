"""Passe de résolution : arbitrage par consensus des conflits d'attribution d'identifiant.

Après la cascade personnes, les conflits collectés (`IdentifierConflict` : une valeur qu'une signature du candidat porte, déjà attribuée à un autre propriétaire) sont arbitrés par le **consensus** des porteurs — l'`author_name_normalized` majoritaire de la valeur. La valeur est transférée au candidat si, et seulement si, le consensus le désigne, lui et pas le propriétaire actuel (`form_matches_person`). Seules les attributions `pending` sont transférables ; les `confirmed` (verrou admin) sont laissées.

Ordre-indépendant : le consensus est un agrégat de tous les porteurs, insensible à la séquence d'ingestion. Conservateur : un consensus qui désigne le propriétaire — ou ni l'un ni l'autre, ou plusieurs candidats à la fois — ne déclenche aucun transfert.

La remédiation du stock déjà rattaché (déplacer les captures historiques et recomputer les formes des personnes délestées) est un chantier séparé, en oneshot sur la base de prod.
"""

import logging
from collections import defaultdict

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.persons_create import PersonsCreateQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.person_repository import PersonRepository
from application.services.persons.core import IdentifierConflict
from domain.persons.matching import ORCID_MATCH_SOURCES, form_matches_person

# Types d'identifiant forts soumis à l'arbitrage de conflit.
_CONFLICT_ID_TYPES = ("orcid", "idref", "hal_person_id")


def detect_identifier_conflicts(
    conn: Connection, queries: PersonsCreateQueries
) -> list[IdentifierConflict]:
    """Balaye le snapshot pour tous les conflits d'attribution d'identifiant.

    Chaque personne qui détient des signatures d'une valeur d'identifiant sans en être le propriétaire attribué est un conflit. Lecture d'agrégat — le résultat ne dépend pas de la séquence de la cascade —, à confier ensuite à `resolve_identifier_transfers` qui tranche par consensus. Partagé par le pipeline (balayage frontal) et la remédiation du stock.
    """
    conflicts: list[IdentifierConflict] = []
    for id_type in _CONFLICT_ID_TYPES:
        owners = queries.fetch_identifier_owners(conn, id_type)
        if not owners:
            continue
        sources = tuple(ORCID_MATCH_SOURCES) if id_type == "orcid" else None
        for id_value, bearer_person_id in queries.fetch_identifier_bearer_persons(
            conn, id_type, sources
        ):
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
    queries: PersonsCreateQueries,
    repo: PersonRepository,
    logger: logging.Logger,
    audit_repo: AuditRepository | None = None,
) -> dict[str, int]:
    """Arbitre les conflits d'attribution collectés et transfère les identifiants captés.

    Retourne les compteurs `{conflicts, pending, transferred}`.
    """
    pending = [c for c in conflicts if c.owner_status == "pending"]
    if not pending:
        return {"conflicts": len(conflicts), "pending": 0, "transferred": 0}

    # Consensus des seules valeurs en conflit (query ciblée, par type d'identifiant).
    values_by_type: dict[str, set[str]] = defaultdict(set)
    for c in pending:
        values_by_type[c.id_type].add(c.id_value)
    consensus: dict[tuple[str, str], str] = {}
    for id_type, values in values_by_type.items():
        for value, form in queries.fetch_identifier_consensus(
            conn, id_type, sorted(values)
        ).items():
            consensus[(id_type, value)] = form

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
        ident.transfer_to(target, source="auto")
        repo.update_identifier(ident)
        # Les signatures affectées, restées sur l'ancien propriétaire et résolues par identifiant, repassent à NULL : la cascade les re-résout vers le nouveau propriétaire.
        detached = queries.null_identifier_signatures(conn, id_type, id_value, owner_id)
        logger.info(
            "Transfert %s=%s : personne %d → %d (consensus %r), %d signature(s) détachée(s)",
            id_type,
            id_value,
            owner_id,
            target,
            cons,
            detached,
        )
        emit_event(
            audit_repo,
            "person_identifier.transferred",
            "person",
            target,
            {"id_type": id_type, "id_value": id_value, "from_person_id": owner_id},
        )
        transferred += 1

    logger.info(
        "Transferts par consensus : %d conflits (%d pending) → %d identifiants transférés",
        len(conflicts),
        len(pending),
        transferred,
    )
    return {"conflicts": len(conflicts), "pending": len(pending), "transferred": transferred}
