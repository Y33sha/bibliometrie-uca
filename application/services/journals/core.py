"""Service Journaux — écritures sur l'agrégat Journal, transaction-agnostiques.

Les opérations sur l'agrégat Publisher vivent dans `application/services/publishers/core.py` ; les deux agrégats restent liés par `journals.publisher_id` (FK), chacun manipulé par son propre service et son propre port.

Le `journal_type` d'une revue alimente des règles de correction du `doc_type` de ses publications. Après une édition ou une fusion, le pipeline rejoue ces corrections (`JournalRecompute`).
"""

from decimal import Decimal

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.journal_recompute import JournalRecompute
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository, JournalUpdate
from application.services._merge import load_merge_pair
from domain.errors import NotFoundError, ValidationError
from domain.journals.issns import (
    JournalIssn,
    validate_journal_issns,
)
from domain.journals.journal import ManualField


def update_journal(
    journal_id: int,
    *,
    update: JournalUpdate,
    repo: JournalRepository,
    audit_repo: AuditRepository | None = None,
) -> bool:
    """Charge la revue, applique les champs explicitement fournis, persiste. Retourne `True` si le `journal_type` ou le `oa_model` a effectivement changé : le command handler rejoue alors les corrections des publications de la revue.

    L'événement d'audit contient seulement les champs soumis.

    Les ISSN fournis deviennent les ISSN de la revue ; `validate_journal_issns` les normalise. Un titre, des ISSN, un type, un modèle OA ou un APC modifiés deviennent des champs saisis à la main (`ManualField`), que le pipeline laisse en l'état. L'APC saisi est en euros.

    Lève `ValidationError` si aucun champ n'est fourni ou si les ISSN sont invalides, `NotFoundError` si la revue n'existe pas.
    """
    if not update.model_fields_set:
        raise ValidationError("Aucun champ à mettre à jour")

    journal = repo.find_by_id(journal_id)
    if journal is None:
        raise NotFoundError(f"Revue {journal_id} introuvable")

    old_title = journal.title
    old_issns = list(journal.issns)
    old_type = journal.journal_type
    old_oa_model = journal.oa_model
    old_apc_amount = journal.apc_amount
    champs = update.model_dump(exclude_unset=True, mode="json")
    # Les champs de `JournalUpdate` ont les noms des attributs de l'agrégat.
    for field_name in update.model_fields_set:
        if field_name == "issns":
            journal.issns = validate_journal_issns(
                JournalIssn(**row.model_dump()) for row in update.issns or []
            )
        elif field_name == "apc_amount":
            # Montant au centime, comme la colonne : la comparaison à l'ancien montant reste exacte.
            journal.apc_amount = (
                Decimal(str(update.apc_amount)).quantize(Decimal("0.01"))
                if update.apc_amount is not None
                else None
            )
        else:
            setattr(journal, field_name, getattr(update, field_name))
    if journal.title != old_title:
        journal.manual_fields |= {ManualField.TITLE}
    if journal.issns != old_issns:
        journal.manual_fields |= {ManualField.ISSNS}
    if journal.journal_type != old_type:
        journal.manual_fields |= {ManualField.JOURNAL_TYPE}
    if journal.oa_model != old_oa_model:
        journal.manual_fields |= {ManualField.OA_MODEL}
    if journal.apc_amount != old_apc_amount:
        # Le formulaire saisit l'APC en euros.
        journal.apc_currency = "EUR" if journal.apc_amount is not None else None
        journal.manual_fields |= {ManualField.APC}
    repo.save(journal)
    emit_event(audit_repo, "journal.updated", "journal", journal_id, champs)
    return journal.journal_type != old_type or journal.oa_model != old_oa_model


def merge_journals(
    target_id: int,
    source_id: int,
    *,
    conn: Connection,
    repo: JournalRepository,
    recompute: JournalRecompute,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne la revue source dans la revue cible, par le pipeline, qui requalifie les publications absorbées.

    Lève `ValidationError` sur deux identifiants égaux, `NotFoundError` sur une revue introuvable.
    """
    load_merge_pair(target_id, source_id, repo.find_by_id, label="Revue")
    recompute.merge_journals(conn, target_id, source_id)
    emit_event(audit_repo, "journal.merged", "journal", target_id, {"source_id": source_id})


# ── Requalification des publications d'un journal après changement d'un champ éditable ──


def requalify_publications_for_journal(
    journal_id: int,
    *,
    conn: Connection,
    recompute: JournalRecompute,
    audit_repo: AuditRepository | None = None,
) -> int:
    """Requalifie, par le pipeline, le `doc_type` des publications d'une revue après un changement de son `journal_type`.

    Précondition : l'appelant a déjà écrit le `journal_type`, dans la même transaction. Retourne le nombre de publications dont le `doc_type` change, et émet l'audit `journal.type_requalified` si ce nombre est positif.

    Un appel dans un `SAVEPOINT` que l'appelant annule donne l'aperçu de la requalification.
    """
    changed = recompute.requalify_publications(conn, journal_id)
    if changed > 0:
        emit_event(
            audit_repo,
            "journal.type_requalified",
            "journal",
            journal_id,
            {"count": changed},
        )
    return changed
