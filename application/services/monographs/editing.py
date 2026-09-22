"""Service Monographies : édition à la main d'une monographie."""

from application.audit_log import emit_event
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.monograph_repository import MonographRepository, MonographUpdate
from domain.errors import NotFoundError, ValidationError


def update_monograph(
    monograph_id: int,
    *,
    update: MonographUpdate,
    repo: MonographRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Charge la monographie, applique les champs fournis, persiste. L'événement d'audit porte les seuls champs soumis.

    Lève `ValidationError` si aucun champ n'est fourni ou si le titre est vide, `NotFoundError` si la monographie n'existe pas.
    """
    if not update.model_fields_set:
        raise ValidationError("Aucun champ à mettre à jour")
    if "title" in update.model_fields_set and not (update.title or "").strip():
        raise ValidationError("Le titre ne peut pas être vide")

    monograph = repo.find_by_id(monograph_id)
    if monograph is None:
        raise NotFoundError(f"Monographie {monograph_id} introuvable")

    for field_name, value in update.model_dump(exclude_unset=True).items():
        setattr(monograph, field_name, value.strip() if isinstance(value, str) else value)
    repo.save(monograph)
    emit_event(
        audit_repo,
        "monograph.updated",
        "monograph",
        monograph_id,
        update.model_dump(exclude_unset=True, mode="json"),
    )
