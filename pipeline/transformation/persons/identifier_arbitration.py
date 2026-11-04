"""Arbitrage des identifiants de personne, avant le rattachement des contributions : neutralisation des identifiants mal placés.

Le consensus de nom d'une valeur d'identifiant est le nom contenu dans strictement plus de contributions sources que chacun des autres (`strict_majority`). Il est calculé une fois sur le snapshot (`compute_identifier_consensus`). Une valeur est mal placée dans des informations du contributeur au nom désignant une autre personne que le consensus. Les contributions sources de ces informations neutralisent la valeur avec le motif `misplaced` (`requalify_misplaced_identifiers`). Une contribution rattachée par ce type d'identifiant, et dont une contribution source gagne la marque, est marquée pour la redécision de sa personne (`Queue.CONTRIBUTION_RESOLUTION`).

Une valeur neutralisée ne fait ni entrer une contribution source dans le périmètre par la fiche RH d'une personne, ni passer à la personne d'une contribution rattachée. Une valeur contenue dans les contributions de plusieurs personnes figure dans la file d'administration des conflits d'identifiants.

L'arbitrage est indépendant de l'ordre de traitement : le calcul repart des données à chaque exécution.
"""

import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from sqlalchemy import Connection, bindparam, text

from domain.persons.identifiers import IdentifierNeutralization, PersonIdentifierType
from domain.persons.source_contribution_matching import identifier_misplaced, strict_majority
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.queues import Queue, enqueue, enqueue_sql
from infrastructure.sql_fragments import (
    identifier_neutralized,
    person_source_contribution,
    trusted_identifier_sql,
)
from pipeline.runtime.observability.log_format import LAST_BRANCH, inflect, quantity
from pipeline.runtime.observability.progress import waiting

_MARK_MODIFIED_PUBLICATIONS = enqueue_sql(
    Queue.PUBLICATION_CONTRIBUTIONS,
    """
    SELECT sr.publication_id FROM source_records sr
    WHERE sr.id IN (SELECT source_record_id FROM modifiees) AND sr.publication_id IS NOT NULL
    """,
)
"""Marque pour le groupement des auteurs les publications des contributions sources de la CTE `modifiees`."""


class ContributorInformationIdentifier(NamedTuple):
    """Informations du contributeur contenant une valeur d'identifiant, avec leur nom normalisé."""

    contributor_information_id: int
    name: str
    value: str


IdentifierKey = tuple[str, str]
"""`(id_type, id_value)`."""

_IDENTIFIERS = "CROSS JOIN LATERAL jsonb_each_text(ci.identifiers) AS k(id_type, id_value)"
"""Identifiants des informations du contributeur `ci`, une ligne par type : `k.id_type`, `k.id_value`. Une requête lit ainsi les tables une seule fois pour tous les types."""


def _trusted_identifier_of_types(id_types: Sequence[str]) -> str:
    """Renvoie la condition vraie quand l'identifiant `k` est d'un des types `id_types`, et fiable pour la source de la contribution source `sc` (`trusted_identifier_sql`)."""
    return (
        "("
        + " OR ".join(
            f"(k.id_type = '{t}' AND {trusted_identifier_sql(t, 'sc')})" for t in id_types
        )
        + ")"
    )


_MISPLACED = IdentifierNeutralization.MISPLACED.value


def fetch_identifier_votes(conn: Connection) -> dict[IdentifierKey, dict[str, int]]:
    """Renvoie, pour chaque valeur d'identifiant, le nombre de contributions sources contenant la valeur, par `author_name_normalized`.

    Votent les contributions sources rattachées à une contribution, de source fiable pour l'identifiant (`trusted_identifier`), et sans neutralisation de la valeur pour partage. Une contribution source neutralisant la valeur comme mal placée vote : le consensus dépend seulement des données.
    """
    shared = identifier_neutralized("k.id_type", reason=IdentifierNeutralization.SHARED.value)
    rows = conn.execute(
        text(f"""
            SELECT k.id_type, k.id_value,
                   ci.author_name_normalized AS name,
                   count(*) AS votes
            FROM contributor_information ci
            {_IDENTIFIERS}
            JOIN source_contributions sc ON sc.contributor_information_id = ci.id
            WHERE ci.author_name_normalized IS NOT NULL
              AND {_trusted_identifier_of_types(tuple(PersonIdentifierType))}
              AND {person_source_contribution("sc")}
              AND NOT {shared}
            GROUP BY 1, 2, 3
        """)
    ).all()
    votes: dict[IdentifierKey, dict[str, int]] = {}
    for r in rows:
        votes.setdefault((r.id_type, r.id_value), {})[r.name] = int(r.votes)
    return votes


def fetch_contributor_information_identifiers(
    conn: Connection, id_type: str
) -> list[ContributorInformationIdentifier]:
    """Renvoie les informations du contributeur contenant un identifiant du type, avec leur nom normalisé."""
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
    """Réécrit les neutralisations `misplaced` de toutes les contributions sources. Renvoie les contributions sources gagnant un identifiant neutralisé, avec les types d'identifiant gagnés.

    Les neutralisations des informations du contributeur de `misplaced` sont posées, les autres effacées. Une neutralisation `shared` du même identifiant l'emporte. Seules les lignes aux neutralisations changées sont écrites, et leurs publications sont marquées pour le groupement des auteurs.

    Args:
        misplaced: `{contributor_information_id: types d'identifiant}`.
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
            -- Deux branches indexées : les contributions sources des informations marquées, et celles déjà neutralisées (`source_contributions_neutralized_idx`).
            candidates AS (
                SELECT sc.id
                FROM marques m
                JOIN source_contributions sc ON sc.contributor_information_id = m.contributor_information_id
                UNION
                SELECT sc.id
                FROM source_contributions sc
                WHERE sc.neutralized_identifiers IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM jsonb_each_text(sc.neutralized_identifiers) AS e(k, v)
                      WHERE e.v = '{_MISPLACED}'
                  )
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
                FROM candidates c
                JOIN source_contributions sc ON sc.id = c.id
                LEFT JOIN marques m ON m.contributor_information_id = sc.contributor_information_id
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


def mark_misplaced_contributions(conn: Connection, gained: Mapping[int, Sequence[str]]) -> int:
    """Marque pour la redécision de leur personne (`Queue.CONTRIBUTION_RESOLUTION`) les contributions rattachées par un type d'identifiant, quand une de leurs contributions sources gagne la marque `misplaced` pour ce type. Renvoie le nombre de contributions marquées.

    Args:
        gained: `{source_contribution_id: types d'identifiant}`.
    """
    pairs = [
        (source_contribution_id, id_type)
        for source_contribution_id, id_types in gained.items()
        for id_type in id_types
    ]
    if not pairs:
        return 0
    source_contribution_ids, id_types = zip(*pairs, strict=True)
    return enqueue(
        conn,
        Queue.CONTRIBUTION_RESOLUTION,
        """
            SELECT g.id
            FROM contributions g
            JOIN aligned_source_contributions gm ON gm.contribution_id = g.id
            JOIN unnest(CAST(:ids AS integer[]), CAST(:types AS text[])) AS m(source_contribution_id, id_type)
                ON m.source_contribution_id = gm.source_contribution_id
            WHERE g.resolution_mode::text = m.id_type
        """,
        {"ids": list(source_contribution_ids), "types": list(id_types)},
    )


IdentifierConsensus = dict[IdentifierKey, str]
"""`{(id_type, id_value): nom du consensus}` pour les valeurs pourvues d'un consensus."""


def compute_identifier_consensus(conn: Connection) -> IdentifierConsensus:
    """Renvoie le consensus de nom de chaque valeur d'identifiant, tous types confondus."""
    return {
        key: name
        for key, votes in fetch_identifier_votes(conn).items()
        if (name := strict_majority(votes)) is not None
    }


def requalify_misplaced_identifiers(
    conn: Connection,
    consensus: IdentifierConsensus,
) -> dict[str, int]:
    """Neutralise les identifiants mal placés et marque pour la redécision de leur personne les contributions rattachées par ces identifiants (`mark_misplaced_contributions`).

    Renvoie `{neutralized, marked_contributions}` : nombres d'identifiants neutralisés et de contributions marquées.
    """
    misplaced: dict[int, list[str]] = defaultdict(list)
    for id_type in PersonIdentifierType:
        for information in fetch_contributor_information_identifiers(conn, id_type):
            if identifier_misplaced(information.name, consensus.get((id_type, information.value))):
                misplaced[information.contributor_information_id].append(id_type)

    gained = write_misplaced_neutralizations(conn, misplaced)
    return {
        "neutralized": sum(len(id_types) for id_types in gained.values()),
        "marked_contributions": mark_misplaced_contributions(conn, gained),
    }


def arbitrate_identifier_conflicts(conn: Connection, logger: logging.Logger) -> dict[str, int]:
    """Neutralise les identifiants mal placés (`requalify_misplaced_identifiers`).

    Renvoie `{neutralized, marked_contributions}`. L'appelant commite.
    """
    with waiting(LAST_BRANCH, logger) as line:
        requalified = requalify_misplaced_identifiers(conn, compute_identifier_consensus(conn))
        neutralized = requalified["neutralized"]
        line.conclude(
            f"{LAST_BRANCH}Identifiants portés sous le nom d'une autre personne : "
            + (
                f"{quantity(neutralized, 'identifiant')} {inflect(neutralized, 'neutralisé')}"
                if neutralized
                else "rien à faire"
            )
        )
    return requalified
