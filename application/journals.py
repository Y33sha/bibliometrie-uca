"""
Service Journaux — accès exclusif en écriture à la table `journals`.

Les opérations sur l'agrégat Publisher vivent dans `application/publishers.py`
(principe SRP). Les deux agrégats restent liés par `journals.publisher_id`
(FK) mais sont manipulés par des services distincts, chacun sur son
propre port.

Les routers FastAPI utilisent les mêmes repos que le pipeline
(routes `def` exécutées dans le threadpool Starlette).
"""

from sqlalchemy import Connection

from application.audit import emit_event
from domain.errors import ConflictError, NotFoundError, ValidationError
from domain.normalize import normalize_text
from domain.ports.audit_repository import AuditRepository
from domain.ports.journal_repository import JournalRepository


def find_or_create_journal(
    cur: Connection,
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
    1. openalex_id (upsert si fourni)
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
    conn: Connection, journal_id: int, *, fields: dict, repo: JournalRepository
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

    fields = dict(fields)
    if "title" in fields:
        fields["title_normalized"] = normalize_text(fields["title"])
    repo.update_journal_fields(journal_id, fields)


def update_journal_apc(
    cur: Connection,
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


def reset_journal_apc(cur: Connection, *, repo: JournalRepository) -> int:
    """Réinitialise les APC/DOAJ de toutes les revues avec openalex_id."""
    return repo.reset_journal_apc()


def merge_journals(
    conn: Connection,
    target_id: int,
    source_id: int,
    *,
    repo: JournalRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne le journal source dans le journal cible."""
    if target_id == source_id:
        raise ConflictError("Impossible de fusionner un journal avec lui-même")

    repo.merge_journal_into(target_id, source_id)
    emit_event(audit_repo, "journal.merged", "journal", target_id, {"source_id": source_id})
