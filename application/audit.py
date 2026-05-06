"""Service d'audit — enregistre les opérations destructives dans audit_log.

Usage :
    # Depuis un service métier, après une opération destructive :
    emit_event(cur, "person.merged", "person", target_id,
               {"source_id": source_id})

Le user_id est récupéré automatiquement depuis le contexte d'authentification
(middleware HTTP). Les opérations déclenchées hors contexte (pipeline, scripts,
tests) sont silencieusement ignorées — elles ne polluent pas la table.

Pourquoi un ContextVar : pour propager le user_id à travers ~15 fonctions de
services sans ajouter `user_id: str | None = None` à toutes leurs signatures.
Les ContextVar sont async-local — chaque requête HTTP a son propre contexte,
pas de fuite entre requêtes.

Cohabitation pendant le chantier sqlalchemy-core-adoption (Phase 1) :
`async_emit_event` accepte les deux signatures (curseur psycopg legacy ou
AsyncConnection SQLAlchemy) et dispatche en interne. Branche psycopg à
supprimer en Phase 4 quand tous les call sites auront basculé en SA.
"""

import contextvars
import json
import logging
from typing import Any

from psycopg.types.json import Jsonb as Json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)


# Contexte utilisateur courant. Peuplé par le middleware d'auth, lu par
# emit_event. `default=None` → hors HTTP (pipeline/scripts/tests),
# l'audit est silencieusement no-op.
_current_user: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_user", default=None
)


def set_current_user(user_id: str | None) -> contextvars.Token:
    """Définit l'utilisateur courant pour la requête en cours.

    Retourne un Token à passer à `reset_current_user()` pour restaurer
    l'état précédent (typiquement dans un bloc try/finally du middleware).
    """
    return _current_user.set(user_id)


def reset_current_user(token: contextvars.Token) -> None:
    """Restaure l'état précédent du contexte utilisateur."""
    _current_user.reset(token)


def get_current_user() -> str | None:
    """Retourne l'utilisateur courant, ou None si hors contexte HTTP."""
    return _current_user.get()


def emit_event(
    cur: Any,
    event_type: str,
    aggregate_type: str,
    aggregate_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Enregistre un événement d'audit dans audit_log.

    Silencieusement no-op si aucun utilisateur n'est défini dans le
    contexte (pipeline, scripts, tests) : on ne veut auditer que les
    actions admin explicites.

    Args:
        cur: curseur DB (psycopg3) dans la transaction courante.
        event_type: notation pointée, ex. "person.merged",
            "publication.excluded", "structure.deleted".
        aggregate_type: type de l'entité affectée
            (person, publication, structure, journal, publisher, authorship).
        aggregate_id: id de l'entité affectée. NULL accepté si l'entité
            n'existe plus après l'opération (cas rare).
        payload: dict JSON-sérialisable de données utiles
            (source_id d'une fusion, champs modifiés, raison, etc.).
    """
    user_id = get_current_user()
    if user_id is None:
        return

    cur.execute(
        """
        INSERT INTO audit_log (event_type, aggregate_type, aggregate_id,
                               payload, user_id)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (event_type, aggregate_type, aggregate_id, Json(payload or {}), user_id),
    )


async def async_emit_event(
    conn: Any,
    event_type: str,
    aggregate_type: str,
    aggregate_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Variante async d'`emit_event`.

    Accepte deux types de connexion pendant le chantier
    sqlalchemy-core-adoption (Phase 1) :
    - `AsyncConnection` SQLAlchemy : nouveau pattern, branche cible.
    - `psycopg.AsyncCursor` : ancien pattern, conservé tant que tous
      les call sites n'ont pas basculé en SA.
    """
    user_id = get_current_user()
    if user_id is None:
        return

    if isinstance(conn, AsyncConnection):
        # SQL brut via text() : on ne peut pas importer la MetaData
        # de infrastructure/db/tables.py depuis application/ (couches
        # DDD). Le passage à un AuditRepository propre est prévu en
        # Phase 3 du chantier audit-cto.
        await conn.execute(
            text(
                "INSERT INTO audit_log "
                "(event_type, aggregate_type, aggregate_id, payload, user_id) "
                "VALUES (:event_type, :aggregate_type, :aggregate_id, "
                "        CAST(:payload AS jsonb), :user_id)"
            ),
            {
                "event_type": event_type,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "payload": json.dumps(payload or {}),
                "user_id": user_id,
            },
        )
    else:
        await conn.execute(
            """
            INSERT INTO audit_log (event_type, aggregate_type, aggregate_id,
                                   payload, user_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (event_type, aggregate_type, aggregate_id, Json(payload or {}), user_id),
        )
