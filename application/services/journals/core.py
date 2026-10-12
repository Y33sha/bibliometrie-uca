"""Service Journaux — écritures sur l'agrégat Journal, transaction-agnostiques.

Les opérations sur l'agrégat Publisher vivent dans `application/services/publishers/core.py` ; les deux agrégats restent liés par `journals.publisher_id` (FK), chacun manipulé par son propre service et son propre port.

Un champ éditable d'une revue commande le `doc_type` de ses publications : le `journal_type` alimente des règles de correction. D'où `requalify_publications_for_journal` et le volet requalification de `merge_journals`, qui rejouent ces corrections sur le stock après une édition.
"""

from decimal import Decimal

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository, JournalUpdate
from application.ports.repositories.publication_repository import PublicationRepository
from application.services._merge import load_merge_pair
from application.services.publications.core import refresh_from_sources
from domain.errors import NotFoundError, ValidationError
from domain.journals.issns import (
    JournalIssn,
    validate_journal_issns,
)
from domain.journals.journal import ManualField
from pipeline.publications.correct_unary import (
    compute_updates,
    hal_origin_ids,
)


def update_journal(
    journal_id: int,
    *,
    update: JournalUpdate,
    repo: JournalRepository,
    audit_repo: AuditRepository | None = None,
) -> bool:
    """Charge la revue, applique les champs explicitement fournis, persiste. Retourne `True` si le `journal_type` a effectivement changé — déclencheur de la requalification des publications, orchestrée par le command handler.

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
    return journal.journal_type != old_type


def _correct_for_journal(
    conn: Connection, queries: MetadataCorrectionQueries, journal_id: int
) -> int:
    """Recalcule et persiste les corrections unaires des `source_publications` d'un journal, après un changement de son `journal_type`. Retourne le nombre de `source_publications` corrigées.

    À enchaîner avec `refresh_from_sources` des publications du journal, qui repart de la colonne `source_publication` rafraîchie ici.
    """
    rows = queries.fetch_for_unary_correction_by_journal(conn, journal_id)
    hal_rows = {
        row.source_id: row
        for row in queries.fetch_for_unary_correction_by_hal_ids(conn, hal_origin_ids(rows))
    }
    language_forms = queries.fetch_language_forms(conn)
    updates = compute_updates(rows, hal_rows, language_forms)
    return queries.persist_corrections(conn, updates)


def merge_journals(
    target_id: int,
    source_id: int,
    *,
    conn: Connection,
    correction_queries: MetadataCorrectionQueries,
    repo: JournalRepository,
    publication_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne le journal source dans le journal cible.

    Les `source_publications` et publications du journal absorbé sont repointées vers la cible (`merge_journal_into`), puis **requalifiées** contre le `journal_type` de la cible : on recalcule en place les corrections des `source_publications` de la cible (`_correct_for_journal`, qui voit alors les enregistrements absorbés via le `journal_id` repointé), puis on rafraîchit les publications absorbées. Fusionner une revue dans un média retype ses publications en `media`.

    Lève `ValidationError` sur deux identifiants égaux, `NotFoundError` sur une revue introuvable.
    """
    load_merge_pair(target_id, source_id, repo.find_by_id, label="Revue")

    # Capturer les publications du source avant le repoint, pour les rafraîchir.
    absorbed_pub_ids = publication_repo.find_ids_by_journal_id(source_id)

    repo.merge_journal_into(target_id, source_id)

    # Les enregistrements absorbés ont alors `journal_id = target` : recalcule en
    # place leurs corrections (le `journal_type` lu est celui de la cible), puis refresh des
    # publications absorbées (qui lisent les colonnes `source_publication` fraîchement corrigées).
    _correct_for_journal(conn, correction_queries, target_id)
    for pub_id in absorbed_pub_ids:
        refresh_from_sources(pub_id, repo=publication_repo)

    emit_event(audit_repo, "journal.merged", "journal", target_id, {"source_id": source_id})


# ── Requalification des publications d'un journal après changement d'un champ éditable ──


def requalify_publications_for_journal(
    journal_id: int,
    *,
    conn: Connection,
    correction_queries: MetadataCorrectionQueries,
    publication_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> int:
    """Requalifie le `doc_type` des publications d'un journal après changement de son `journal_type`.

    Précondition : le `journal.journal_type` a déjà été mis à jour par l'appelant (dans la même transaction qu'un `update_journal`). Deux temps :

    1. `_correct_for_journal` recalcule **en place** les corrections des `source_publications` du journal. `refresh_from_sources` repart de la colonne corrigée (pas du brut) ; ce recalcul préalable garantit qu'elle reflète le `journal_type` mis à jour.
    2. `refresh_from_sources` sur chaque publication du journal ré-agrège les colonnes `source_publication` fraîchement corrigées (garde-fous habituels : conflits DOI, audit `doi_changed`, orphelins).

    Retourne le nombre de publications dont le `doc_type` a effectivement changé, par comparaison de deux relevés encadrant la boucle ; émet l'audit `journal.type_requalified` si > 0.

    Le **preview** (combien changeraient sans appliquer) s'obtient en enveloppant cet appel dans un `SAVEPOINT` que l'appelant annule : preview et apply partagent alors exactement la même logique.
    """
    pub_ids = publication_repo.find_ids_by_journal_id(journal_id)
    if not pub_ids:
        return 0

    before = publication_repo.find_doc_types_by_ids(pub_ids)
    _correct_for_journal(conn, correction_queries, journal_id)
    for pub_id in pub_ids:
        refresh_from_sources(pub_id, repo=publication_repo)
    after = publication_repo.find_doc_types_by_ids(pub_ids)

    # Une publication que le refresh a supprimée (orpheline, hors périmètre) manque d'`after` :
    # elle n'est pas requalifiée, elle a disparu.
    changed = sum(
        1 for pub_id, doc_type in before.items() if after.get(pub_id, doc_type) != doc_type
    )

    if changed > 0:
        emit_event(
            audit_repo,
            "journal.type_requalified",
            "journal",
            journal_id,
            {"count": changed},
        )
    return changed
