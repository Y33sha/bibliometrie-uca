"""
Service Journaux — accès exclusif en écriture à la table `journals`.

Les opérations sur l'agrégat Publisher vivent dans `application/publishers.py` (principe SRP). Les deux agrégats restent liés par `journals.publisher_id` (FK) mais sont manipulés par des services distincts, chacun sur son propre port.

Les routers FastAPI utilisent les mêmes repos que le pipeline (routes `def` exécutées dans le threadpool Starlette).
"""

from dataclasses import replace
from typing import cast

from application.audit import emit_event
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository, JournalUpdateFields
from application.ports.repositories.publication_repository import PublicationRepository
from application.publications import apply_corrections, refresh_from_sources
from domain.errors import ConflictError, NotFoundError, ValidationError
from domain.normalize import normalize_text
from domain.publications.aggregation import refresh_from_sources as _refresh_aggregate
from domain.sources.registry import SOURCE_PRIORITY
from domain.types import JsonValue


def find_or_create_journal(
    title: str | None,
    *,
    issn: str | None = None,
    eissn: str | None = None,
    issnl: str | None = None,
    publisher_id: int | None = None,
    openalex_id: str | None = None,
    oa_model: str | None = None,
    repo: JournalRepository,
) -> int | None:
    """Trouve ou crée un journal.

    Cascade de recherche :
    1. openalex_id (upsert si fourni) #TODO: virer ça! Osef
    2. ISSN (cherche dans issn, eissn, issnl)
    3. eISSN (idem)
    4. ISSN-L (idem)
    5. Titre normalisé (forme de nom journal)
    6. Création + enregistrement de la forme de nom

    Enrichit les métadonnées manquantes quand un journal existant est trouvé.
    Retourne journal.id ou None si title est vide.
    """
    if not title:
        return None

    title_normalized = normalize_text(title)

    def _match_and_enrich(journal_id: int, *, with_openalex: bool = True) -> int:
        """Enrichit le journal trouvé et rattache la forme de nom. Retourne son id."""
        repo.enrich_journal(
            journal_id,
            issn=issn,
            eissn=eissn,
            publisher_id=publisher_id,
            openalex_id=openalex_id if with_openalex else None,
            oa_model=oa_model if with_openalex else None,
        )
        repo.add_journal_name_form(journal_id, title_normalized, publisher_id)
        return journal_id

    # 1. Par openalex_id
    if openalex_id:
        jid = repo.find_journal_by_openalex_id(openalex_id)
        if jid:
            # Cas openalex_id : enrichit sans passer openalex_id/oa_model
            # (déjà présents par définition)
            return _match_and_enrich(jid, with_openalex=False)
        # openalex_id inconnu : on cherche quand même par ISSN/name_form
        # avant de créer, pour rattacher l'openalex_id à un journal existant

    # 2-4. Par ISSN / eISSN / ISSN-L (dans n'importe lequel des 3 champs)
    for value in (issn, eissn, issnl):
        if not value:
            continue
        jid = repo.find_journal_by_issn_any(value)
        if jid:
            return _match_and_enrich(jid)

    # 5. Par forme de nom (priorité aux journals avec eISSN)
    jid = repo.find_journal_by_name_form(title_normalized, publisher_id)
    if jid:
        repo.enrich_journal(
            jid,
            issn=issn,
            eissn=eissn,
            publisher_id=publisher_id,
            openalex_id=openalex_id,
            oa_model=oa_model,
        )
        return jid

    # 6. Créer + enregistrer la forme de nom
    journal_id = repo.create_journal(
        title=title.strip(),
        title_normalized=title_normalized,
        issn=issn,
        eissn=eissn,
        issnl=issnl,
        publisher_id=publisher_id,
        openalex_id=openalex_id,
        oa_model=oa_model,
    )
    repo.add_journal_name_form(journal_id, title_normalized, publisher_id)
    return journal_id


def update_journal(
    journal_id: int, *, fields: dict[str, JsonValue], repo: JournalRepository
) -> None:
    """Met à jour une revue. Le `title` est automatiquement normalisé en
    `title_normalized`.

    Lève NotFoundError si la revue n'existe pas.
    Lève ValidationError si `fields` est vide.
    """
    if not fields:
        raise ValidationError("Aucun champ à mettre à jour")

    if not repo.journal_exists(journal_id):
        raise NotFoundError(f"Revue {journal_id} introuvable")

    update_fields = cast(JournalUpdateFields, dict(fields))
    if "title" in update_fields:
        title = update_fields["title"]
        assert isinstance(title, str), "fields['title'] doit être un str (validé par Pydantic)"
        update_fields["title_normalized"] = normalize_text(title)
    repo.update_journal_fields(journal_id, update_fields)


def update_journal_apc(
    journal_id: int,
    *,
    apc_amount: float | None = None,
    apc_currency: str | None = None,
    is_in_doaj: bool | None = None,
    repo: JournalRepository,
) -> None:
    """Met à jour les informations APC/DOAJ d'un journal."""
    repo.update_journal_apc(
        journal_id,
        apc_amount=apc_amount,
        apc_currency=apc_currency,
        is_in_doaj=is_in_doaj,
    )


def reset_journal_apc(*, repo: JournalRepository) -> int:
    """Réinitialise les APC/DOAJ de toutes les revues avec openalex_id."""
    return repo.reset_journal_apc()


def merge_journals(
    target_id: int,
    source_id: int,
    *,
    repo: JournalRepository,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne le journal source dans le journal cible.

    Les publications du journal absorbé sont repointées vers la cible, puis
    **requalifiées** : leur `doc_type` est re-dérivé contre le `journal_type` de
    la cible (mêmes règles que `requalify_publications_for_journal` sur un
    changement de type). Fusionner une revue dans un média retype donc ses
    publications en `media`.
    """
    if target_id == source_id:
        raise ConflictError("Impossible de fusionner un journal avec lui-même")

    # Capturer les publications du source avant le repoint, pour les requalifier.
    absorbed_pub_ids = pub_repo.find_ids_by_journal_id(source_id)

    repo.merge_journal_into(target_id, source_id)

    # Les publications absorbées pointent désormais sur la cible : `refresh_from_sources`
    # re-dérive leur doc_type avec le `journal_type` de la cible (la correction lit le
    # type via la jointure sur `journal_id`, repointée par `merge_journal_into`).
    for pub_id in absorbed_pub_ids:
        refresh_from_sources(pub_id, repo=pub_repo, audit_repo=audit_repo)

    emit_event(audit_repo, "journal.merged", "journal", target_id, {"source_id": source_id})


# ── Requalification des publications d'un journal après changement d'un input éditable ──


def requalify_publications_for_journal(
    journal_id: int,
    *,
    prospective_journal_type: str | None,
    dry_run: bool,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> int:
    """Compte (et applique si `dry_run=False`) la requalification du `doc_type` des publications d'un journal suite au changement de son `journal_type`.

    Modes :

    - ``dry_run=True`` : simulation en mémoire. On charge chaque publication du journal et ses vues sources, on injecte `prospective_journal_type` sur les vues (le journal en base n'a pas encore changé) et on rejoue la cascade correction → agrégation dans une copie en mémoire. Retourne le nombre de publications dont le `doc_type` *changerait*. Aucune écriture DB. Sert au preview de la modale admin.

    - ``dry_run=False`` : application. Précondition : le `journal.journal_type` a déjà été mis à jour à `prospective_journal_type` par le caller (typiquement dans la même transaction qu'un `update_journal`). On relance `refresh_from_sources` complet sur chaque publication du journal — ce qui passe par les garde-fous habituels (conflits DOI, audit `doi_changed`, orphelins). Retourne le nombre de publications dont le `doc_type` a effectivement changé. Émet l'audit `journal.type_requalified` en fin de boucle si > 0.

    Le compte est calculé identiquement dans les deux modes (delta entre `pub.doc_type` avant / après), de sorte que le preview est honnête vis-à-vis de l'apply.
    """
    pub_ids = pub_repo.find_ids_by_journal_id(journal_id)
    if not pub_ids:
        return 0

    changed = 0
    for pub_id in pub_ids:
        pub = pub_repo.find_by_id(pub_id)
        if pub is None:
            continue
        original_doc_type = pub.doc_type

        if dry_run:
            sources = pub_repo.get_source_publications(pub_id)
            if not sources:
                continue
            adjusted = [replace(s, journal_type=prospective_journal_type) for s in sources]
            effective = [apply_corrections(s) for s in adjusted]
            _refresh_aggregate(pub, effective, source_priority=SOURCE_PRIORITY)
            new_doc_type = pub.doc_type
        else:
            refresh_from_sources(pub_id, repo=pub_repo, audit_repo=audit_repo)
            pub_after = pub_repo.find_by_id(pub_id)
            new_doc_type = pub_after.doc_type if pub_after else None

        if new_doc_type != original_doc_type:
            changed += 1

    if not dry_run and changed > 0:
        emit_event(
            audit_repo,
            "journal.type_requalified",
            "journal",
            journal_id,
            {"count": changed, "new_type": prospective_journal_type},
        )
    return changed
