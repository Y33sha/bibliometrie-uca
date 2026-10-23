"""Arbitrage des identifiants de personne, avant la cascade : identifiants mal placés et conflits d'attribution.

Le consensus d'une valeur d'identifiant est le nom que contiennent strictement plus de contributions sources que chacun des autres (`consensus_name`). Il est calculé une fois sur le snapshot (`compute_identifier_consensus`).

Des informations du contributeur dont le nom désigne une autre personne que celle du consensus contiennent la valeur par erreur. Ses contributions sources la neutralisent avec le motif `misplaced` (`requalify_misplaced_identifiers`).

Un conflit (`IdentifierConflict`) est une valeur qu'une contribution source du candidat contient et qu'une autre personne détient. Le même consensus le tranche (`resolve_identifier_transfers`) : la valeur va au candidat quand le consensus désigne le candidat seul. Seules les attributions `pending` sont transférables. Les contributions sources affectées repassent à NULL, et la cascade les re-résout.

L'arbitrage est ordre-indépendant : le consensus agrège tous les porteurs, et le calcul repart des données à chaque exécution.
"""

import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from sqlalchemy import Connection, bindparam, text

from domain.persons.identifiers import (
    PERSON_IDENTIFIER_TYPES,
    AttributionStatus,
    IdentifierNeutralization,
    IdentifierOrigin,
)
from domain.persons.matching import (
    STRONG_PERSON_IDENTIFIER_TYPES,
    PersonNameForms,
    ResolutionMode,
    consensus_name,
    form_matches_person,
    identifier_misplaced,
)
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.queues import Queue, enqueue_sql
from infrastructure.repositories.person_repository import PgPersonRepository
from infrastructure.sql_fragments import (
    DETACHED_SOURCE_CONTRIBUTION,
    identifier_neutralized,
    person_source_contribution,
    pinned,
    trusted_identifier_sql,
)
from pipeline.runtime.observability.log_format import (
    BRANCH,
    LAST_BRANCH,
    inflect,
    nothing_to_do,
    quantity,
    step,
)
from pipeline.runtime.observability.progress import waiting
from pipeline.transformation.persons.store import PersonsStore

# Marque pour le groupement des auteurs les publications des contributions sources de la CTE `modifiees`.
_MARK_MODIFIED_PUBLICATIONS = enqueue_sql(
    Queue.PUBLICATION_CONTRIBUTIONS,
    """
    SELECT sr.publication_id FROM source_records sr
    WHERE sr.id IN (SELECT source_record_id FROM modifiees) AND sr.publication_id IS NOT NULL
    """,
)


class ContributorInformationIdentifier(NamedTuple):
    """Informations du contributeur qui contiennent une valeur d'identifiant, avec leur nom normalisé."""

    contributor_information_id: int
    name: str
    value: str


class MisplacedNeutralizations(NamedTuple):
    """Résultat d'une réécriture des neutralisations `misplaced`."""

    neutralized: int
    """Contributions sources qui gagnent un identifiant neutralisé."""
    to_detach: list[int]
    """Parmi elles, les contributions sources résolues par identifiant et non épinglées : leur rattachement a pu passer par l'identifiant neutralisé."""


# Condition vraie quand la contribution source `sa` neutralise l'identifiant du paramètre `:id_type`.
_ID_TYPE_NEUTRALIZED = identifier_neutralized(":id_type")

# Même condition, restreinte au partage de la valeur entre contributions sources d'un document.
_ID_TYPE_SHARED = identifier_neutralized(":id_type", reason=IdentifierNeutralization.SHARED.value)

_MISPLACED = IdentifierNeutralization.MISPLACED.value


def fetch_identifier_votes(conn: Connection, id_type: str) -> dict[str, dict[str, int]]:
    """Pour chaque valeur du type, le nombre de **contributions sources** qui la contiennent sous chaque `author_name_normalized` (poids en contributions sources, et non en lignes de `contributor_information` — 99 correctes l'emportent sur 1 corrompue). Le rapprochement part des informations du contributeur qui contiennent le type (`contributor_information`), jointes aux `source_contributions` (index `contributor_information_id`) pour le comptage.

    Une contribution source hors groupe ne vote pas. Une contribution source qui neutralise la valeur pour cause de partage ne vote pas. Une contribution source qui la neutralise comme mal placée vote : le consensus ne dépend ainsi que des données, pas des requalifications précédentes. Seuls les identifiants fiables selon leur source votent (`trusted_identifier`), comme au matching."""
    rows = conn.execute(
        text(f"""
            SELECT ci.identifiers->>:id_type AS id_value,
                   ci.author_name_normalized AS name,
                   count(*) AS votes
            FROM contributor_information ci
            JOIN source_contributions sc ON sc.contributor_information_id = ci.id
            WHERE ci.identifiers ? :id_type
              AND ci.author_name_normalized IS NOT NULL
              AND {person_source_contribution("sc")}
              AND NOT {_ID_TYPE_SHARED}
              AND {trusted_identifier_sql(id_type, "sc")}
            GROUP BY 1, 2
        """),
        {"id_type": id_type},
    ).all()
    votes: dict[str, dict[str, int]] = {}
    for r in rows:
        votes.setdefault(r.id_value, {})[r.name] = int(r.votes)
    return votes


def fetch_contributor_information_identifiers(
    conn: Connection, id_type: str
) -> list[ContributorInformationIdentifier]:
    """Informations du contributeur qui contiennent un identifiant du type, avec leur nom normalisé."""
    rows = conn.execute(
        text("""
            SELECT id, author_name_normalized AS name, identifiers->>:id_type AS value
            FROM contributor_information
            WHERE identifiers ? :id_type AND author_name_normalized IS NOT NULL
        """),
        {"id_type": id_type},
    ).all()
    return [ContributorInformationIdentifier(r.id, r.name, r.value) for r in rows]


def write_misplaced_neutralizations(
    conn: Connection, misplaced: Mapping[int, Sequence[str]]
) -> MisplacedNeutralizations:
    """Réécrit les neutralisations `misplaced` de toutes les contributions sources : celles des informations du contributeur de `misplaced` (`{contributor_information_id: types d'identifiant}`) sont posées, les autres effacées. Une neutralisation `shared` du même identifiant l'emporte. Seules les lignes dont la carte change sont écrites, et leurs publications sont marquées pour le groupement des auteurs."""
    payload = [
        {
            "contributor_information_id": contributor_information_id,
            "carte": dict.fromkeys(id_types, _MISPLACED),
        }
        for contributor_information_id, id_types in misplaced.items()
    ]
    rows = conn.execute(
        text(f"""
            WITH marques AS (
                SELECT m.contributor_information_id, m.carte
                FROM jsonb_to_recordset(:payload) AS m(contributor_information_id integer, carte jsonb)
            ),
            cibles AS (
                SELECT sc.id,
                       sc.neutralized_identifiers AS avant,
                       NULLIF(
                           coalesce(m.carte, '{{}}'::jsonb)
                           || coalesce(
                               (SELECT jsonb_object_agg(e.k, e.v)
                                  FROM jsonb_each(sc.neutralized_identifiers) AS e(k, v)
                                 WHERE e.v <> to_jsonb('{_MISPLACED}'::text)),
                               '{{}}'::jsonb),
                           '{{}}'::jsonb
                       ) AS apres
                FROM source_contributions sc
                LEFT JOIN marques m ON m.contributor_information_id = sc.contributor_information_id
                WHERE m.contributor_information_id IS NOT NULL
                   OR (sc.neutralized_identifiers IS NOT NULL
                       AND EXISTS (
                           SELECT 1 FROM jsonb_each_text(sc.neutralized_identifiers) AS e(k, v)
                           WHERE e.v = '{_MISPLACED}'
                       ))
            ),
            modifiees AS (
                UPDATE source_contributions sc
                SET neutralized_identifiers = c.apres
                FROM cibles c
                WHERE sc.id = c.id AND c.apres IS DISTINCT FROM c.avant
                RETURNING sc.id, sc.source_record_id, sc.resolution_mode, c.avant, c.apres
            ),
            regroupees AS ({_MARK_MODIFIED_PUBLICATIONS})
            SELECT id,
                   coalesce(resolution_mode = '{ResolutionMode.IDENTIFIER.value}', false)
                   AND NOT {pinned("modifiees.id")} AS a_detacher
            FROM modifiees
            WHERE EXISTS (
                SELECT 1 FROM jsonb_object_keys(coalesce(apres, '{{}}'::jsonb)) AS k
                WHERE NOT coalesce(avant ? k, false)
            )
            ORDER BY id
        """).bindparams(bindparam("payload", type_=Jsonb)),
        {"payload": payload},
    ).all()
    return MisplacedNeutralizations(
        neutralized=len(rows), to_detach=[r.id for r in rows if r.a_detacher]
    )


def fetch_person_name_forms(conn: Connection, person_ids: list[int]) -> dict[int, PersonNameForms]:
    """Les formes `confirmed` accompagnent le nom-prénom canonique pour l'arbitrage des transferts (`form_matches_person`) : une personne peut matcher le consensus par une forme validée que le canonique ne recouvre pas (changement de nom). Les formes `pending` — vecteur de contamination des captures — sont exclues."""
    if not person_ids:
        return {}
    rows = conn.execute(
        text(f"""
            SELECT p.id,
                   p.last_name_normalized AS ln,
                   p.first_name_normalized AS fn,
                   COALESCE(
                       array_agg(nf.name_form)
                           FILTER (WHERE nf.status = '{AttributionStatus.CONFIRMED.value}'),
                       ARRAY[]::text[]
                   ) AS confirmed_forms
            FROM persons p
            LEFT JOIN person_name_forms nf ON nf.person_id = p.id
            WHERE p.id = ANY(:ids)
            GROUP BY p.id, p.last_name_normalized, p.first_name_normalized
        """),
        {"ids": list(person_ids)},
    ).all()
    return {r.id: PersonNameForms(r.ln or "", r.fn or "", list(r.confirmed_forms)) for r in rows}


def fetch_identifier_owners(conn: Connection, id_type: str) -> dict[str, tuple[int, str]]:
    """Sert au balayage frontal des conflits d'attribution : le propriétaire attribué d'une valeur, à confronter aux personnes qui en ont des contributions sources."""
    rows = conn.execute(
        text(f"""
            SELECT id_value, person_id, status
            FROM person_identifiers
            WHERE id_type = :t AND status <> '{AttributionStatus.REJECTED.value}'
        """),
        {"t": id_type},
    ).all()
    return {r.id_value: (r.person_id, r.status) for r in rows}


def fetch_identifier_bearer_persons(conn: Connection, id_type: str) -> list[tuple[str, int]]:
    """Agrégat sur les contributions sources rattachées dont les informations du contributeur contiennent l'identifiant `id_type`, fiable selon sa source (`trusted_identifier`)."""
    rows = conn.execute(
        text(f"""
            SELECT ci.identifiers->>:id_type AS id_value, sc.person_id
            FROM source_contributions sc
            JOIN contributor_information ci ON ci.id = sc.contributor_information_id
            WHERE ci.identifiers ? :id_type
              AND NOT {_ID_TYPE_NEUTRALIZED}
              AND sc.person_id IS NOT NULL
              AND {trusted_identifier_sql(id_type, "sc")}
            GROUP BY 1, 2
        """),
        {"id_type": id_type},
    ).all()
    return [(r.id_value, r.person_id) for r in rows]


def null_identifier_source_contributions(
    conn: Connection, id_type: str, id_value: str, old_owner_person_id: int
) -> int:
    """Après réattribution d'une valeur de l'ancien propriétaire vers la personne du consensus, les contributions sources rattachées à l'ancien propriétaire, résolues **par identifiant** (`resolution_mode = 'identifier'`), dont les informations du contributeur contiennent cette valeur, et non épinglées, repassent à NULL : la cascade les re-résout contre la carte corrigée. Les contributions sources nominales qui contiennent la valeur ne bougent pas (leur `person_id` ne dépend pas d'elle)."""
    return conn.execute(
        text(f"""
            UPDATE source_contributions sc
            SET {DETACHED_SOURCE_CONTRIBUTION}
            FROM contributor_information ci
            WHERE sc.contributor_information_id = ci.id
              AND sc.person_id = :old_owner
              AND sc.resolution_mode = '{ResolutionMode.IDENTIFIER.value}'
              AND ci.identifiers->>:id_type = :id_value
              AND NOT {_ID_TYPE_NEUTRALIZED}
              AND NOT {pinned("sc.id")}
        """),
        {"old_owner": old_owner_person_id, "id_type": id_type, "id_value": id_value},
    ).rowcount


IdentifierConsensus = dict[tuple[str, str], str]
"""`{(id_type, id_value): nom du consensus}` pour les valeurs dont le consensus désigne un nom."""


def compute_identifier_consensus(conn: Connection) -> IdentifierConsensus:
    """Consensus de chaque valeur d'identifiant, tous types confondus."""
    consensus: IdentifierConsensus = {}
    for id_type in PERSON_IDENTIFIER_TYPES:
        for value, votes in fetch_identifier_votes(conn, id_type).items():
            if (name := consensus_name(votes)) is not None:
                consensus[(id_type, value)] = name
    return consensus


def requalify_misplaced_identifiers(
    conn: Connection,
    consensus: IdentifierConsensus,
) -> dict[str, int]:
    """Neutralise les identifiants mal placés et détache les contributions sources qu'ils ont pu rattacher.

    Retourne `{neutralized, detached}` : le nombre de contributions sources qui gagnent un identifiant neutralisé, et de celles qui sont détachées pour que la cascade les re-résolve.
    """
    misplaced: dict[int, list[str]] = defaultdict(list)
    for id_type in PERSON_IDENTIFIER_TYPES:
        for information in fetch_contributor_information_identifiers(conn, id_type):
            if identifier_misplaced(information.name, consensus.get((id_type, information.value))):
                misplaced[information.contributor_information_id].append(id_type)

    written = write_misplaced_neutralizations(conn, misplaced)
    detached = (
        PersonsStore(conn).detach_source_contributions(written.to_detach)
        if written.to_detach
        else 0
    )
    return {"neutralized": written.neutralized, "detached": detached}


class IdentifierConflict(NamedTuple):
    """Une valeur d'identifiant qu'une contribution source du candidat contient est déjà attribuée à une autre personne.

    L'arbitrage par consensus des porteurs la transfère au candidat si le consensus le désigne. Une attribution `confirmed` n'est jamais transférée.
    """

    id_type: str
    id_value: str
    candidate_person_id: int
    owner_person_id: int
    owner_status: str


def detect_identifier_conflicts(conn: Connection) -> list[IdentifierConflict]:
    """Balaye le snapshot pour tous les conflits d'attribution d'identifiant.

    Chaque personne qui détient des contributions sources d'une valeur d'identifiant sans en être le propriétaire attribué est un conflit. Lecture d'agrégat — le résultat ne dépend pas de la séquence de la cascade —, à confier ensuite à `resolve_identifier_transfers` qui tranche par consensus. Partagé par le pipeline (balayage frontal) et la remédiation du stock.
    """
    conflicts: list[IdentifierConflict] = []
    for id_type in STRONG_PERSON_IDENTIFIER_TYPES:
        owners = fetch_identifier_owners(conn, id_type)
        if not owners:
            continue
        for id_value, bearer_person_id in fetch_identifier_bearer_persons(conn, id_type):
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
    repo: PgPersonRepository,
    logger: logging.Logger,
) -> dict[str, int]:
    """Arbitre les conflits d'attribution collectés et transfère les identifiants captés, d'après le `consensus` des valeurs d'identifiant (`compute_identifier_consensus`).

    Retourne les compteurs `{conflicts, pending, transferred}`.
    """
    pending = [c for c in conflicts if c.owner_status == "pending"]
    if not pending:
        nothing_to_do(logger)
        return {"conflicts": len(conflicts), "pending": 0, "transferred": 0}

    # Nom-prénom + formes confirmées des personnes impliquées (propriétaires et candidats).
    person_ids = {c.candidate_person_id for c in pending} | {c.owner_person_id for c in pending}
    persons = fetch_person_name_forms(conn, sorted(person_ids))

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
        # Les contributions sources affectées, restées sur l'ancien propriétaire et résolues par identifiant, repassent à NULL : la cascade les re-résout vers le nouveau propriétaire.
        detached = null_identifier_source_contributions(conn, id_type, id_value, owner_id)
        logger.info(
            "%sTransfert %s=%s : personne %d → %d (consensus %r), %s %s",
            BRANCH,
            id_type,
            id_value,
            owner_id,
            target,
            cons,
            quantity(detached, "contribution source", "contributions sources"),
            inflect(detached, "détachée"),
        )
        transferred += 1

    # Un conflit dont l'attribution est confirmée par l'admin est tranché : seuls les autres comptent.
    logger.info(
        "%s%s à arbitrer → %s %s",
        LAST_BRANCH,
        quantity(len(pending), "conflit"),
        quantity(transferred, "identifiant"),
        inflect(transferred, "transféré"),
    )
    return {"conflicts": len(conflicts), "pending": len(pending), "transferred": transferred}


def arbitrate_identifier_conflicts(
    conn: Connection,
    logger: logging.Logger,
    *,
    repo: PgPersonRepository,
) -> dict[str, int]:
    """Neutralise les identifiants mal placés, puis tranche les conflits d'attribution d'identifiant par transfert.

    Retourne `{neutralized, detached, transferred}`. Le commit est laissé au caller.
    """
    step(logger, "Identifiants mal placés et conflits d'attribution")
    with waiting(BRANCH, logger) as line:
        consensus = compute_identifier_consensus(conn)
        requalified = requalify_misplaced_identifiers(conn, consensus)
        if requalified["neutralized"]:
            line.conclude(
                f"{BRANCH}Identifiants mal placés neutralisés sur "
                f"{quantity(requalified['neutralized'], 'contribution source', 'contributions sources')}"
            )
        else:
            line.erase()
    with waiting(BRANCH, logger) as line:
        conflicts = detect_identifier_conflicts(conn)
        line.erase()
    transferred = resolve_identifier_transfers(
        conn, conflicts, consensus=consensus, repo=repo, logger=logger
    )["transferred"]

    return {
        "neutralized": requalified["neutralized"],
        "detached": requalified["detached"],
        "transferred": transferred,
    }
