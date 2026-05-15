"""Service d'audit — enregistre les opérations destructives dans audit_log.

Usage :
    # Depuis un service métier, après une opération destructive :
    emit_event(audit_repo, "person.merged", "person", target_id,
               {"source_id": source_id})

Le user_id est récupéré automatiquement depuis le contexte d'authentification
(middleware HTTP). Les opérations déclenchées hors contexte (pipeline, scripts,
tests) sont silencieusement ignorées — elles ne polluent pas la table.

Pourquoi un ContextVar : pour propager le user_id à travers ~15 fonctions de
services sans ajouter `user_id: str | None = None` à toutes leurs signatures.
Les ContextVar sont async-local — chaque requête HTTP a son propre contexte,
pas de fuite entre requêtes.

L'écriture SQL elle-même passe par le port `AuditRepository` (cf.
`application/ports/repositories/audit_repository.py`), pas par un `cur.execute` inline :
règle DDD `application ⊥ infrastructure`.
"""

import contextvars
import logging

from application.ports.repositories.audit_repository import AuditRepository
from domain.json_types import JsonValue

logger = logging.getLogger(__name__)


# Contexte utilisateur courant. Peuplé par le middleware d'auth, lu par
# emit_event. `default=None` → hors HTTP (pipeline/scripts/tests),
# l'audit est silencieusement no-op.
_current_user: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_user", default=None
)


def set_current_user(user_id: str | None) -> contextvars.Token[str | None]:
    """Définit l'utilisateur courant pour la requête en cours.

    Retourne un Token à passer à `reset_current_user()` pour restaurer
    l'état précédent (typiquement dans un bloc try/finally du middleware).
    """
    return _current_user.set(user_id)


def reset_current_user(token: contextvars.Token[str | None]) -> None:
    """Restaure l'état précédent du contexte utilisateur."""
    _current_user.reset(token)


def get_current_user() -> str | None:
    """Retourne l'utilisateur courant, ou None si hors contexte HTTP."""
    return _current_user.get()


def emit_event(
    repo: AuditRepository | None,
    event_type: str,
    aggregate_type: str,
    aggregate_id: int | None = None,
    payload: dict[str, JsonValue] | None = None,
) -> None:
    """Enregistre un événement d'audit dans audit_log.

    Silencieusement no-op si :
    - aucun utilisateur n'est défini dans le contexte (pipeline,
      scripts, tests qui n'auditent pas) ;
    - `repo` est None (caller hors HTTP qui n'a pas de repo audit
      câblé — typiquement le pipeline).

    Args:
        repo: AuditRepository lié à la transaction courante. None
            accepté pour les callers pipeline/CLI qui ne sont pas en
            contexte HTTP : l'audit est de toute façon no-op (user_id
            absent), aucun intérêt à câbler un repo.
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
    if user_id is None or repo is None:
        return
    repo.record_event(event_type, aggregate_type, aggregate_id, payload or {}, user_id)
