"""Journal d'audit : consigne dans `audit_log` les décisions prises par une utilisatrice de l'administration.

Un service émet l'événement après l'écriture qu'il décrit : `emit_event("person.merged", "person", target_id, {"source_id": source_id})`.

L'événement rejoint la file de la requête en cours. `db_conn` écrit cette file dans `audit_log` juste avant le commit de la requête (`record_pending_events`) : la trace partage le sort de l'écriture qu'elle décrit.

La requête et son utilisatrice vivent dans un ContextVar, posé par le middleware d'authentification. Hors requête d'administration (pipeline, scripts, tests qui n'auditent pas), `emit_event` ne consigne rien. Chaque requête HTTP a son propre contexte. Une copie du contexte, celle d'un thread du threadpool, contient la même file.
"""

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from application.ports.repositories.audit_repository import AuditRepository
from domain.types import JsonValue


@dataclass(frozen=True, slots=True)
class _AuditEvent:
    event_type: str
    aggregate_type: str
    aggregate_id: int | None
    payload: dict[str, JsonValue]


@dataclass(slots=True)
class _AuditSession:
    """Utilisatrice de la requête en cours, et événements émis en attente d'écriture."""

    user_id: str
    events: list[_AuditEvent] = field(default_factory=list)


_session: contextvars.ContextVar[_AuditSession | None] = contextvars.ContextVar(
    "audit_session", default=None
)


def set_current_user(user_id: str | None) -> contextvars.Token[_AuditSession | None]:
    """Ouvre la session d'audit de la requête en cours, au nom de l'utilisatrice (aucune avec `None`), et rend le jeton qui restaure l'état précédent (`reset_current_user`)."""
    return _session.set(_AuditSession(user_id) if user_id is not None else None)


def reset_current_user(token: contextvars.Token[_AuditSession | None]) -> None:
    """Restaure l'état précédent du contexte d'audit."""
    _session.reset(token)


def get_current_user() -> str | None:
    """Utilisatrice de la requête en cours, ou `None` hors requête d'administration."""
    session = _session.get()
    return session.user_id if session is not None else None


def emit_event(
    event_type: str,
    aggregate_type: str,
    aggregate_id: int | None = None,
    payload: dict[str, JsonValue] | None = None,
) -> None:
    """Ajoute un événement à la file de la requête en cours ; sans requête d'administration, ne consigne rien.

    `event_type` est en notation pointée (`person.merged`, `structure.deleted`), `aggregate_type` est le type de l'entité touchée (person, publication, structure, serial, publisher, address…). `aggregate_id` est nul quand l'entité disparaît sans équivalent, ou quand l'événement concerne un lot. `payload` contient les données utiles, sérialisables en JSON (source d'une fusion, champs modifiés…).
    """
    session = _session.get()
    if session is not None:
        session.events.append(_AuditEvent(event_type, aggregate_type, aggregate_id, payload or {}))


@contextmanager
def discarded_events() -> Iterator[None]:
    """Écarte les événements émis dans le bloc : l'écriture qu'ils décrivent y est annulée (aperçu dans un `SAVEPOINT`)."""
    session = _session.get()
    mark = len(session.events) if session is not None else 0
    try:
        yield
    finally:
        if session is not None:
            del session.events[mark:]


def record_pending_events(repo: AuditRepository) -> None:
    """Écrit par `repo` les événements en attente de la requête en cours, puis vide la file."""
    session = _session.get()
    if session is None:
        return
    for event in session.events:
        repo.record_event(
            event.event_type,
            event.aggregate_type,
            event.aggregate_id,
            event.payload,
            session.user_id,
        )
    session.events.clear()
