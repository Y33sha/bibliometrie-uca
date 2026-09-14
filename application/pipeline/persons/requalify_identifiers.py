"""Phase personnes — consensus des porteurs d'identifiant et requalification des identifiants mal placés.

Le consensus d'une valeur d'identifiant est le nom que portent strictement plus de signatures que chacun des autres (`consensus_name`). Une identité dont le nom ne désigne pas la personne du consensus porte la valeur par erreur : ses signatures la neutralisent avec le motif `misplaced`. Le calcul repart des données à chaque exécution, si bien qu'une neutralisation disparaît quand le consensus change.
"""

import logging
from collections import defaultdict

from sqlalchemy import Connection

from application.pipeline.libelles import BRANCHE, accord
from application.ports.pipeline.persons.matching import PersonsMatchingQueries
from domain.persons.identifiers import PERSON_IDENTIFIER_TYPES
from domain.persons.matching import consensus_name, identifier_misplaced

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
    logger: logging.Logger,
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
    detached = queries.detach_authorships(conn, written.to_detach) if written.to_detach else 0
    logger.info(
        "%sIdentifiants mal placés neutralisés sur %s",
        BRANCHE,
        accord(written.neutralized, "signature"),
    )
    return {"neutralized": written.neutralized, "detached": detached}
