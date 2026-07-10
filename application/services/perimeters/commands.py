"""Command handlers des écritures API sur les périmètres : la frontière transactionnelle.

Une écriture API est une commande (intention courte d'un acteur). Chaque handler
reçoit la connexion de la requête, compose les briques agnostiques de `core.py`
et `conn.commit()` au succès — pour que la donnée soit persistée avant l'envoi de
la réponse (cf. `docs/chantiers/CODE_commit-avant-reponse.md`). Les briques
composées restent transaction-agnostiques (réutilisées par les CLI) ; seul le
command handler commit.
"""

from sqlalchemy import Connection

from application.ports.config import ConfigStore
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import PerimeterRepository
from application.services.perimeters import core as perimeters_service
from domain.types import JsonValue


def create_perimeter(
    conn: Connection,
    *,
    code: str,
    name: str,
    repo: PerimeterRepository,
) -> int:
    """Crée un périmètre. Retourne l'id créé."""
    pid = perimeters_service.create_perimeter(code=code, name=name, repo=repo)
    conn.commit()
    return pid


def update_perimeter(
    conn: Connection,
    perimeter_id: int,
    *,
    fields: dict[str, JsonValue],
    repo: PerimeterRepository,
) -> None:
    """Met à jour un périmètre (champs sélectifs : name, structure_ids)."""
    perimeters_service.update_perimeter(perimeter_id, fields=fields, repo=repo)
    repo.refresh_structures()
    conn.commit()


def delete_perimeter(
    conn: Connection,
    perimeter_id: int,
    *,
    repo: PerimeterRepository,
    config: ConfigStore,
    audit_repo: AuditRepository,
) -> None:
    """Supprime un périmètre (interdit s'il est référencé par la config pipeline)."""
    perimeters_service.delete_perimeter(
        perimeter_id, repo=repo, config=config, audit_repo=audit_repo
    )
    conn.commit()


def add_perimeter_structure(
    conn: Connection,
    perimeter_id: int,
    structure_id: int,
    *,
    repo: PerimeterRepository,
) -> str:
    """Ajoute une structure racine au périmètre. Retourne "added"/"already_present"."""
    status = perimeters_service.add_perimeter_structure(perimeter_id, structure_id, repo=repo)
    repo.refresh_structures()
    conn.commit()
    return status


def remove_perimeter_structure(
    conn: Connection,
    perimeter_id: int,
    structure_id: int,
    *,
    repo: PerimeterRepository,
) -> None:
    """Retire une structure racine du périmètre."""
    perimeters_service.remove_perimeter_structure(perimeter_id, structure_id, repo=repo)
    repo.refresh_structures()
    conn.commit()
