"""Files d'attente de recalcul (schéma `queues`) : identifiants des lignes qu'une tâche du pipeline doit traiter.

Marquer une ligne, c'est insérer son identifiant dans la file avec un nouveau numéro de marquage `seq`. Une tâche relève les couples `(id, seq)` de la file au début, puis supprime exactement ceux-là à la fin. Un marquage fait pendant la tâche change `seq`, donc reste dans la file pour l'exécution suivante.
"""

from collections.abc import Sequence
from enum import StrEnum

from sqlalchemy import Connection, text


class Queue(StrEnum):
    """Files d'attente, par nom de table."""

    SOURCE_CONTRIBUTION_COUNTRIES = "source_contribution_countries_queue"
    """Contributions sources dont les pays sont à recalculer."""
    ADDRESS_COUNTRIES = "address_countries_queue"
    """Adresses dont les pays changent : les pays de leurs contributions sources sont à recalculer."""
    ADDRESS_CANDIDATES = "address_candidates_queue"
    """Adresses dont les pays candidats sont à détecter par le texte, puis à résoudre."""
    PUBLICATION_CONTRIBUTIONS = "publication_contributions_queue"
    """Publications dont les groupes de contributions sources sont à recalculer : un enregistrement source a rejoint ou quitté la publication, ou ses contributions sources ont changé."""
    SOURCE_RECORD_KEYS = "source_record_keys_queue"
    """Enregistrements sources à réconcilier : écrits, corrigés, entrés dans le périmètre, ou voisins d'un enregistrement source supprimé."""


def enqueue_sql(queue: Queue, ids_sql: str) -> str:
    """Instruction qui marque dans `queue` les identifiants que rend la requête `ids_sql`, à une colonne. Un identifiant déjà en file reçoit un nouveau `seq`.

    L'instruction peut servir de requête d'une CTE, pour marquer les lignes qu'une autre CTE écrit.
    """
    # noqa S608 : les noms de file et de table, et `ids_sql`, viennent du code, jamais d'une entrée.
    return f"""
        INSERT INTO {queue} (id)
        SELECT DISTINCT id FROM ({ids_sql}) AS marked (id)
        ON CONFLICT (id) DO UPDATE SET seq = DEFAULT
    """  # noqa: S608


def enqueue(conn: Connection, queue: Queue, ids_sql: str, params: dict[str, object]) -> int:
    """Marque dans `queue` les identifiants que rend la requête `ids_sql`, à une colonne. Retourne le nombre d'identifiants marqués."""
    return conn.execute(text(enqueue_sql(queue, ids_sql)), params).rowcount


def snapshot(conn: Connection, queue: Queue, table: str) -> None:
    """Relève les couples `(id, seq)` de `queue` dans la table temporaire `table`, indexée par `id`.

    Une table temporaire déjà commitée survit à une exception dans la session de la connexion : un relevé antérieur de même nom est remplacé.
    """
    conn.execute(text(f"DROP TABLE IF EXISTS pg_temp.{table}"))
    conn.execute(text(f"CREATE TEMP TABLE {table} AS SELECT id, seq FROM {queue}"))  # noqa: S608
    conn.execute(text(f"ALTER TABLE {table} ADD PRIMARY KEY (id)"))
    conn.execute(text(f"ANALYZE {table}"))


def delete_processed(
    conn: Connection, queue: Queue, table: str, ids: Sequence[int] | None = None
) -> None:
    """Supprime de `queue` les couples `(id, seq)` relevés dans `table` par `snapshot`, ou seulement ceux des identifiants `ids`."""
    restriction = "" if ids is None else " AND t.id = ANY(:ids)"
    conn.execute(
        text(
            f"DELETE FROM {queue} q USING {table} t WHERE q.id = t.id AND q.seq = t.seq{restriction}"  # noqa: S608
        ),
        {} if ids is None else {"ids": list(ids)},
    )
