"""Garde-fou d'instrumentation : repère le DML non committé sur une connexion.

Un listener marque la connexion « dirty » dès qu'un statement émet du DML (INSERT/UPDATE/DELETE), en lisant le command tag PostgreSQL (psycopg `statusmessage` : `UPDATE n`, `INSERT 0 n`, `DELETE n`) plutôt qu'en analysant le SQL. C'est la classification faite par la base elle-même : robuste pour le SQL brut comme pour les constructs Core, y compris le DML enveloppé dans un CTE (`WITH … UPDATE`), et muet sur les lectures (une requête qui ne fait que valider puis renvoyer un 404 n'émet aucun DML, donc ne déclenche rien). Un commit ou un rollback réarme le flag.

Les écritures applicatives passent par des command handlers qui committent explicitement. `db_conn_sync` (interfaces API) lit ce flag à la fermeture de la connexion : s'il reste positionné alors qu'une transaction est encore ouverte, une écriture a échappé à ce commit explicite (écriture parasite dans un routeur) et un warning est émis.
"""

import logging

from sqlalchemy import Connection, Engine, event

logger = logging.getLogger(__name__)

_DIRTY_KEY = "uncommitted_dml"
_STACK_KEY = "uncommitted_dml_savepoints"
_DML_TAGS = frozenset({"INSERT", "UPDATE", "DELETE"})


def _mark_dml(
    conn: Connection,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """Marque la connexion dirty si le command tag PostgreSQL est un DML.

    `cursor.statusmessage` (psycopg) porte le command tag de la dernière commande exécutée ; son premier mot est le verbe (`INSERT`/`UPDATE`/`DELETE`/`SELECT`/ `COPY`…). Sur un `executemany`, le tag reste un DML (dernière commande du lot).
    """
    tag = (getattr(cursor, "statusmessage", None) or "").split(" ", 1)[0].upper()
    if tag in _DML_TAGS:
        conn.info[_DIRTY_KEY] = True


def _clear_dml_flag(conn: Connection) -> None:
    conn.info.pop(_DIRTY_KEY, None)
    conn.info.pop(_STACK_KEY, None)


def _on_savepoint(conn: Connection, name: str) -> None:
    # Mémorise l'état du flag à l'ouverture du savepoint : un rollback ultérieur ramènera la connexion à cet état (le DML émis depuis sera annulé).
    conn.info.setdefault(_STACK_KEY, []).append(bool(conn.info.get(_DIRTY_KEY)))


def _on_rollback_savepoint(conn: Connection, name: str, context: object) -> None:
    stack = conn.info.get(_STACK_KEY)
    if not stack:
        return
    if stack.pop():
        conn.info[_DIRTY_KEY] = True
    else:
        # Aucun DML non committé avant le savepoint : ce qui a été émis depuis est annulé (cas d'un preview écrit puis rollbacké), le flag retombe à zéro.
        conn.info.pop(_DIRTY_KEY, None)


def _on_release_savepoint(conn: Connection, name: str, context: object) -> None:
    # Savepoint relâché (ses écritures intégrées à la transaction) : on garde le flag courant, on dépile seulement.
    stack = conn.info.get(_STACK_KEY)
    if stack:
        stack.pop()


def install_dml_guard(engine: Engine) -> None:
    """Attache les listeners de suivi du DML non committé sur l'engine.

    Posé sur l'engine global : le suivi vaut pour toutes les connexions (API, pipeline, CLI), mais seule `db_conn_sync` lit le flag pour émettre le warning.
    """
    event.listen(engine, "after_cursor_execute", _mark_dml)
    event.listen(engine, "commit", _clear_dml_flag)
    event.listen(engine, "rollback", _clear_dml_flag)
    event.listen(engine, "savepoint", _on_savepoint)
    event.listen(engine, "rollback_savepoint", _on_rollback_savepoint)
    event.listen(engine, "release_savepoint", _on_release_savepoint)


def has_uncommitted_dml(conn: Connection) -> bool:
    """Vrai si la connexion a émis du DML non suivi d'un commit/rollback."""
    return bool(conn.info.get(_DIRTY_KEY))


def reset_dml_flag(conn: Connection) -> None:
    """Réinitialise le flag au checkout d'une connexion du pool.

    `conn.info` vit sur la connexion DBAPI sous-jacente, partagée par le pool ; repartir d'un état propre à chaque checkout évite qu'un flag résiduel d'une requête précédente ne fausse le garde-fou.
    """
    conn.info.pop(_DIRTY_KEY, None)
    conn.info.pop(_STACK_KEY, None)
