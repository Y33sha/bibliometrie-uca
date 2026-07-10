"""
Service Journaux — accès exclusif en écriture à la table `journals`.

Les opérations sur l'agrégat Publisher vivent dans `application/publishers/core.py` (principe SRP). Les deux agrégats restent liés par `journals.publisher_id` (FK) mais sont manipulés par des services distincts, chacun sur son propre port.

Les routers FastAPI utilisent les mêmes repos que le pipeline (routes `def` exécutées dans le threadpool Starlette).
"""

from typing import cast

from sqlalchemy import Connection

from application.audit import emit_event
from application.pipeline.metadata_correction.correct_unary import correct_for_journal
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository, JournalUpdateFields
from application.ports.repositories.publication_repository import PublicationRepository
from application.services.publications.core import refresh_from_sources
from domain.errors import ConflictError, NotFoundError, ValidationError
from domain.normalize import normalize_text
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
    repo: JournalRepository,
) -> None:
    """Met à jour les informations APC d'un journal."""
    repo.update_journal_apc(
        journal_id,
        apc_amount=apc_amount,
        apc_currency=apc_currency,
    )


def merge_journals(
    target_id: int,
    source_id: int,
    *,
    conn: Connection,
    correction_queries: MetadataCorrectionQueries,
    repo: JournalRepository,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne le journal source dans le journal cible.

    Les `source_publications` et publications du journal absorbé sont repointées vers
    la cible (`merge_journal_into`), puis **requalifiées** contre le `journal_type` de
    la cible : on recompute en place les corrections des SP de la cible
    (`correct_for_journal`, qui voit désormais les SP absorbées via le `journal_id`
    repointé), puis on rafraîchit les publications absorbées. Fusionner une revue dans
    un média retype donc ses publications en `media`.
    """
    if target_id == source_id:
        raise ConflictError("Impossible de fusionner un journal avec lui-même")

    # Capturer les publications du source avant le repoint, pour les rafraîchir.
    absorbed_pub_ids = pub_repo.find_ids_by_journal_id(source_id)

    repo.merge_journal_into(target_id, source_id)

    # Les SP absorbées portent désormais `journal_id = target` : recompute en place leurs
    # corrections (le `journal_type` lu par la correction est celui de la cible), puis
    # refresh des publications absorbées (qui lisent les colonnes SP fraîchement corrigées).
    correct_for_journal(conn, correction_queries, target_id)
    for pub_id in absorbed_pub_ids:
        refresh_from_sources(pub_id, repo=pub_repo, audit_repo=audit_repo)

    emit_event(audit_repo, "journal.merged", "journal", target_id, {"source_id": source_id})


# ── Requalification des publications d'un journal après changement d'un input éditable ──


def requalify_publications_for_journal(
    journal_id: int,
    *,
    conn: Connection,
    correction_queries: MetadataCorrectionQueries,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> int:
    """Requalifie le `doc_type` des publications d'un journal après changement de son `journal_type`.

    Précondition : le `journal.journal_type` a déjà été mis à jour par le caller (dans la
    même transaction qu'un `update_journal`). Deux temps :

    1. `correct_for_journal` recompute **en place** les corrections des `source_publications`
       du journal — indispensable car `refresh_from_sources` repart de la colonne SP corrigée
       (pas du brut), donc sans ce recompute il figerait la publication sur l'ancienne
       correction journal-dépendante.
    2. `refresh_from_sources` sur chaque publication du journal ré-agrège les colonnes SP
       fraîchement corrigées (garde-fous habituels : conflits DOI, audit `doi_changed`, orphelins).

    Retourne le nombre de publications dont le `doc_type` a effectivement changé ; émet
    l'audit `journal.type_requalified` si > 0.

    Le **preview** (combien changeraient sans appliquer) s'obtient en enveloppant cet appel
    dans un `SAVEPOINT` rollbacké côté caller — preview et apply partagent ainsi exactement
    la même logique.
    """
    pub_ids = pub_repo.find_ids_by_journal_id(journal_id)
    if not pub_ids:
        return 0

    correct_for_journal(conn, correction_queries, journal_id)

    changed = 0
    for pub_id in pub_ids:
        pub = pub_repo.find_by_id(pub_id)
        if pub is None:
            continue
        original_doc_type = pub.doc_type
        refresh_from_sources(pub_id, repo=pub_repo, audit_repo=audit_repo)
        pub_after = pub_repo.find_by_id(pub_id)
        if pub_after is not None and pub_after.doc_type != original_doc_type:
            changed += 1

    if changed > 0:
        emit_event(
            audit_repo,
            "journal.type_requalified",
            "journal",
            journal_id,
            {"count": changed},
        )
    return changed
