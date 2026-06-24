"""Garde-fou d'instrumentation : repère le DML non committé sur une connexion.

Sert la migration des écritures API vers des command handlers qui committent
explicitement, dans la couche application (cf.
`docs/chantiers/CODE_commit-avant-reponse.md`). Un listener marque la connexion
« dirty » dès qu'un statement émet du DML (INSERT/UPDATE/DELETE), en lisant le
command tag PostgreSQL (psycopg `statusmessage` : `UPDATE n`, `INSERT 0 n`,
`DELETE n`) plutôt qu'en analysant le SQL. C'est la classification faite par la
base elle-même : robuste pour le SQL brut comme pour les constructs Core, y
compris le DML enveloppé dans un CTE (`WITH … UPDATE`), et muet sur les lectures
(une requête en méthode d'écriture qui ne fait que valider puis renvoyer un 404
n'émet aucun DML, donc ne déclenche rien). Un commit ou un rollback réarme le
flag.

`db_conn_sync` (interfaces API) lit ce flag à la fermeture : s'il reste
positionné alors qu'une transaction est encore ouverte, une écriture a échappé à
un command handler (endpoint non encore migré, ou écriture parasite dans un
routeur) et un warning est émis. La bascule finale (commit de fin → rollback) est
pilotée par l'extinction de ce warning sur tout le trafic.
"""

import logging

from sqlalchemy import Connection, Engine, event

logger = logging.getLogger(__name__)

_DIRTY_KEY = "uncommitted_dml"
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

    `cursor.statusmessage` (psycopg) porte le command tag de la dernière commande
    exécutée ; son premier mot est le verbe (`INSERT`/`UPDATE`/`DELETE`/`SELECT`/
    `COPY`…). Sur un `executemany`, le tag reste un DML (dernière commande du lot).
    """
    tag = (getattr(cursor, "statusmessage", None) or "").split(" ", 1)[0].upper()
    if tag in _DML_TAGS:
        conn.info[_DIRTY_KEY] = True


def _clear_dml_flag(conn: Connection) -> None:
    conn.info.pop(_DIRTY_KEY, None)


def install_dml_guard(engine: Engine) -> None:
    """Attache les listeners de suivi du DML non committé sur l'engine.

    Posé sur l'engine global : le suivi vaut pour toutes les connexions (API,
    pipeline, CLI), mais seule `db_conn_sync` lit le flag pour émettre le warning.
    """
    event.listen(engine, "after_cursor_execute", _mark_dml)
    event.listen(engine, "commit", _clear_dml_flag)
    event.listen(engine, "rollback", _clear_dml_flag)


def has_uncommitted_dml(conn: Connection) -> bool:
    """Vrai si la connexion a émis du DML non suivi d'un commit/rollback."""
    return bool(conn.info.get(_DIRTY_KEY))


def reset_dml_flag(conn: Connection) -> None:
    """Réinitialise le flag au checkout d'une connexion du pool.

    `conn.info` vit sur la connexion DBAPI sous-jacente, partagée par le pool ;
    repartir d'un état propre à chaque checkout évite qu'un flag résiduel d'une
    requête précédente ne fausse le garde-fou.
    """
    conn.info.pop(_DIRTY_KEY, None)
