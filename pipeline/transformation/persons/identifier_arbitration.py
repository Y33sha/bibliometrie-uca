"""Arbitrage des identifiants de personne, avant le rattachement des groupes : identifiants mal placés et conflits d'attribution.

Le consensus de nom d'une valeur d'identifiant est le nom que contiennent strictement plus de contributions sources que chacun des autres (`strict_majority`). Il est calculé une fois sur le snapshot (`compute_identifier_consensus`). Des informations du contributeur dont le nom désigne une autre personne que celle du consensus contiennent la valeur par erreur. Ses contributions sources la neutralisent avec le motif `misplaced` (`requalify_misplaced_identifiers`). Un groupe rattaché par ce type d'identifiant dont un membre gagne la marque perd sa personne.

Un conflit (`IdentifierConflict`) est une valeur attribuée à une personne, le titulaire, et portée par un groupe d'une autre personne. Le vote des groupes le tranche (`resolve_identifier_transfers`). Chaque groupe qui porte la valeur donne une voix à sa personne. La valeur va à la personne qui a strictement plus de voix que chacune des autres. Seules les attributions `pending` sont transférables. Après un transfert, les groupes de l'ancien titulaire rattachés par ce type d'identifiant et qui portent la valeur perdent leur personne. Le rattachement des groupes (`persons.resolve_groups`) les re-décide.

L'arbitrage est ordre-indépendant : le calcul repart des données à chaque exécution.
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
    identifier_misplaced,
    strict_majority,
)
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.queues import Queue, enqueue_sql
from infrastructure.repositories.person_repository import PgPersonRepository
from infrastructure.sql_fragments import (
    DETACHED_GROUP,
    GROUP_MEMBERS,
    identifier_neutralized,
    person_source_contribution,
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


# Condition vraie quand la contribution source `sc` neutralise l'identifiant du paramètre `:id_type`.
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
) -> dict[int, list[str]]:
    """Réécrit les neutralisations `misplaced` de toutes les contributions sources : celles des informations du contributeur de `misplaced` (`{contributor_information_id: types d'identifiant}`) sont posées, les autres effacées. Une neutralisation `shared` du même identifiant l'emporte. Seules les lignes dont la carte change sont écrites, et leurs publications sont marquées pour le groupement des auteurs.

    Rend les contributions sources qui gagnent un identifiant neutralisé, avec les types d'identifiant gagnés.
    """
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
                RETURNING sc.id, sc.source_record_id, c.avant, c.apres
            ),
            regroupees AS ({_MARK_MODIFIED_PUBLICATIONS}),
            gains AS (
                SELECT id,
                       ARRAY(
                           SELECT k FROM jsonb_object_keys(coalesce(apres, '{{}}'::jsonb)) AS k
                           WHERE NOT coalesce(avant ? k, false)
                           ORDER BY k
                       ) AS types
                FROM modifiees
            )
            SELECT id, types
            FROM gains
            WHERE cardinality(types) > 0
            ORDER BY id
        """).bindparams(bindparam("payload", type_=Jsonb)),
        {"payload": payload},
    ).all()
    return {r.id: list(r.types) for r in rows}


def release_misplaced_groups(conn: Connection, gained: Mapping[int, Sequence[str]]) -> int:
    """Retire leur personne aux groupes rattachés par un type d'identifiant dont un membre gagne la marque `misplaced` pour ce type (`gained` : `{source_contribution_id: types d'identifiant}`). Rend le nombre de groupes libérés."""
    pairs = [
        (source_contribution_id, id_type)
        for source_contribution_id, id_types in gained.items()
        for id_type in id_types
    ]
    if not pairs:
        return 0
    source_contribution_ids, id_types = zip(*pairs, strict=True)
    return conn.execute(
        text(f"""
            UPDATE source_contribution_groups g
            SET {DETACHED_GROUP}
            FROM source_contribution_group_members gm
            JOIN unnest(CAST(:ids AS integer[]), CAST(:types AS text[])) AS m(source_contribution_id, id_type)
                ON m.source_contribution_id = gm.source_contribution_id
            WHERE gm.group_id = g.id AND g.resolution_mode::text = m.id_type
        """),
        {"ids": list(source_contribution_ids), "types": list(id_types)},
    ).rowcount


def fetch_identifier_owners(conn: Connection, id_type: str) -> dict[str, tuple[int, str]]:
    """Titulaire et statut de chaque valeur attribuée du type, hors attributions rejetées."""
    rows = conn.execute(
        text(f"""
            SELECT id_value, person_id, status
            FROM person_identifiers
            WHERE id_type = :t AND status <> '{AttributionStatus.REJECTED.value}'
        """),
        {"t": id_type},
    ).all()
    return {r.id_value: (r.person_id, r.status) for r in rows}


def _bears_identifier(id_type: str) -> str:
    """Condition vraie quand la contribution source `sc`, d'informations du contributeur `ci`, porte l'identifiant `id_type` (passé aussi en paramètre `:id_type`) : présent, non neutralisé, et fiable selon sa source."""
    return (
        f"ci.identifiers ? :id_type AND NOT {_ID_TYPE_NEUTRALIZED}"
        f" AND {trusted_identifier_sql(id_type, 'sc')}"
    )


def fetch_identifier_group_votes(conn: Connection, id_type: str) -> dict[str, dict[int, int]]:
    """Pour chaque valeur du type, les personnes des groupes qui la portent, avec leurs voix. Un groupe porte la valeur quand un de ses membres la porte (`_bears_identifier`), et donne une voix à sa personne."""
    rows = conn.execute(
        text(f"""
            SELECT ci.identifiers->>:id_type AS id_value, g.person_id,
                   count(DISTINCT g.id) AS votes
            FROM {GROUP_MEMBERS}
            WHERE g.person_id IS NOT NULL AND {_bears_identifier(id_type)}
            GROUP BY 1, 2
        """),
        {"id_type": id_type},
    ).all()
    votes: dict[str, dict[int, int]] = {}
    for r in rows:
        votes.setdefault(r.id_value, {})[r.person_id] = int(r.votes)
    return votes


def release_identifier_groups(conn: Connection, id_type: str, id_value: str, person_id: int) -> int:
    """Retire leur personne aux groupes de `person_id` rattachés par le type d'identifiant dont un membre porte la valeur (`_bears_identifier`). Rend le nombre de groupes libérés."""
    return conn.execute(
        text(f"""
            UPDATE source_contribution_groups
            SET {DETACHED_GROUP}
            WHERE id IN (
                SELECT g.id
                FROM {GROUP_MEMBERS}
                WHERE g.person_id = :person_id
                  AND g.resolution_mode::text = :id_type
                  AND ci.identifiers->>:id_type = :id_value
                  AND {_bears_identifier(id_type)}
            )
        """),
        {"person_id": person_id, "id_type": id_type, "id_value": id_value},
    ).rowcount


IdentifierConsensus = dict[tuple[str, str], str]
"""`{(id_type, id_value): nom du consensus}` pour les valeurs dont le consensus désigne un nom."""


def compute_identifier_consensus(conn: Connection) -> IdentifierConsensus:
    """Consensus de nom de chaque valeur d'identifiant, tous types confondus."""
    consensus: IdentifierConsensus = {}
    for id_type in PERSON_IDENTIFIER_TYPES:
        for value, votes in fetch_identifier_votes(conn, id_type).items():
            if (name := strict_majority(votes)) is not None:
                consensus[(id_type, value)] = name
    return consensus


def requalify_misplaced_identifiers(
    conn: Connection,
    consensus: IdentifierConsensus,
) -> dict[str, int]:
    """Neutralise les identifiants mal placés et libère les groupes rattachés par eux (`release_misplaced_groups`).

    Retourne `{neutralized, released_groups}` : le nombre de contributions sources qui gagnent un identifiant neutralisé, et de groupes qui perdent leur personne.
    """
    misplaced: dict[int, list[str]] = defaultdict(list)
    for id_type in PERSON_IDENTIFIER_TYPES:
        for information in fetch_contributor_information_identifiers(conn, id_type):
            if identifier_misplaced(information.name, consensus.get((id_type, information.value))):
                misplaced[information.contributor_information_id].append(id_type)

    gained = write_misplaced_neutralizations(conn, misplaced)
    return {
        "neutralized": len(gained),
        "released_groups": release_misplaced_groups(conn, gained),
    }


class IdentifierConflict(NamedTuple):
    """Valeur d'identifiant attribuée à une personne, le titulaire, et portée par un groupe d'une autre personne.

    Le vote des groupes la transfère à la personne qui a la majorité stricte des voix. Une attribution `confirmed` n'est jamais transférée.
    """

    id_type: str
    id_value: str
    owner_person_id: int
    owner_status: str
    votes: Mapping[int, int]
    """Voix de chaque personne dont un groupe porte la valeur (`fetch_identifier_group_votes`)."""


def detect_identifier_conflicts(conn: Connection) -> list[IdentifierConflict]:
    """Conflits d'attribution des identifiants forts : valeurs attribuées qu'un groupe d'une autre personne que le titulaire porte. Lecture d'agrégat, à confier ensuite à `resolve_identifier_transfers`."""
    conflicts: list[IdentifierConflict] = []
    for id_type in STRONG_PERSON_IDENTIFIER_TYPES:
        owners = fetch_identifier_owners(conn, id_type)
        if not owners:
            continue
        for id_value, votes in fetch_identifier_group_votes(conn, id_type).items():
            owner = owners.get(id_value)
            if owner is None or votes.keys() <= {owner[0]}:
                continue
            conflicts.append(IdentifierConflict(id_type, id_value, owner[0], owner[1], votes))
    return conflicts


def resolve_identifier_transfers(
    conn: Connection,
    conflicts: list[IdentifierConflict],
    *,
    repo: PgPersonRepository,
    logger: logging.Logger,
) -> dict[str, int]:
    """Tranche les conflits d'attribution par le vote des groupes. La valeur va à la personne qui a strictement plus de voix que chacune des autres (`strict_majority`), quand ce n'est pas le titulaire. Sans majorité, le conflit reste en l'état.

    Retourne les compteurs `{conflicts, pending, transferred}`.
    """
    # Un conflit dont l'attribution est confirmée par l'admin est tranché : seuls les autres comptent.
    pending = [c for c in conflicts if c.owner_status == AttributionStatus.PENDING]
    if not pending:
        nothing_to_do(logger)
        return {"conflicts": len(conflicts), "pending": 0, "transferred": 0}

    transferred = 0
    for conflict in pending:
        id_type, id_value, owner = conflict.id_type, conflict.id_value, conflict.owner_person_id
        target = strict_majority(conflict.votes)
        if target is None or target == owner:
            continue
        ident = repo.find_identifier(id_type, id_value)
        if ident is None:
            continue
        ident.transfer_to(target, source=IdentifierOrigin.AUTO)
        repo.update_identifier(ident)
        release_identifier_groups(conn, id_type, id_value, owner)
        logger.info(
            "%sTransfert %s=%s : personne %d → %d (%s contre %d)",
            BRANCH,
            id_type,
            id_value,
            owner,
            target,
            quantity(conflict.votes[target], "voix", "voix"),
            conflict.votes.get(owner, 0),
        )
        transferred += 1

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

    Retourne `{neutralized, released_groups, transferred}`. Le commit est laissé au caller.
    """
    step(logger, "Identifiants mal placés et conflits d'attribution")
    with waiting(BRANCH, logger) as line:
        requalified = requalify_misplaced_identifiers(conn, compute_identifier_consensus(conn))
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
    transferred = resolve_identifier_transfers(conn, conflicts, repo=repo, logger=logger)

    return {**requalified, "transferred": transferred["transferred"]}
