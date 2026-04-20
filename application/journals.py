"""
Service Référentiel bibliographique — accès exclusif en écriture
aux tables `publishers` et `journals`.

Toute création ou recherche de journal/éditeur passe par ce module.
Compatible avec les curseurs tuples (standard) et RealDictCursor.
"""

from typing import Any

from application.audit import emit_event
from domain.errors import ConflictError, NotFoundError, ValidationError
from domain.normalize import normalize_text
from domain.ports.journal_repository import JournalRepository

# ── Publishers ──


def find_or_create_publisher(
    cur: Any,
    name: str | None,
    *,
    openalex_id: str | None = None,
    repo: JournalRepository,
) -> int | None:
    """Trouve ou crée un éditeur.

    Cascade de recherche :
    1. openalex_id (si fourni)
    2. publisher_name_forms (par nom normalisé)
    3. Création + enregistrement de la forme de nom

    Retourne publisher.id ou None si name est vide.
    """
    if not name:
        return None

    name_normalized = normalize_text(name)
    if not name_normalized:
        return None

    # 1. Par openalex_id
    if openalex_id:
        pub_id = repo.find_publisher_by_openalex_id(openalex_id)
        if pub_id:
            repo.add_publisher_name_form(pub_id, name_normalized)
            return pub_id

    # 2. Par forme de nom (rattache l'openalex_id si on en a un)
    pub_id = repo.find_publisher_by_name_form(name_normalized)
    if pub_id:
        if openalex_id:
            repo.set_publisher_openalex_id_if_missing(pub_id, openalex_id)
        return pub_id

    # 3. Créer
    pub_id = repo.create_publisher(
        name=name.strip(),
        name_normalized=name_normalized,
        openalex_id=openalex_id,
    )
    repo.add_publisher_name_form(pub_id, name_normalized)
    return pub_id


# ── Journals ──


def find_or_create_journal(
    cur: Any,
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
    cur: Any, journal_id: int, *, fields: dict, repo: JournalRepository
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


def update_publisher(
    cur: Any, publisher_id: int, *, fields: dict, repo: JournalRepository
) -> None:
    """Met à jour un éditeur. Le `name` est automatiquement normalisé en
    `name_normalized`.

    Lève NotFoundError si l'éditeur n'existe pas.
    Lève ValidationError si `fields` est vide.
    """
    if not fields:
        raise ValidationError("Aucun champ à mettre à jour")

    if not repo.publisher_exists(publisher_id):
        raise NotFoundError(f"Éditeur {publisher_id} introuvable")

    fields = dict(fields)
    if "name" in fields:
        fields["name_normalized"] = normalize_text(fields["name"])
    repo.update_publisher_fields(publisher_id, fields)


def update_journal_apc(
    cur: Any,
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


def reset_journal_apc(cur: Any, *, repo: JournalRepository) -> int:
    """Réinitialise les APC/DOAJ de toutes les revues avec openalex_id."""
    return repo.reset_journal_apc()


# ── Fusions ──


def merge_publishers(
    cur: Any, target_id: int, source_id: int, *, repo: JournalRepository
) -> None:
    """Fusionne l'éditeur source dans l'éditeur cible.

    Invariant métier : s'il y a des journaux aux titres partagés entre
    les deux éditeurs avec des ISSN/eISSN/ISSN-L différents, la fusion
    est refusée (ConflictError) — on ne veut pas fusionner deux
    journaux qui ont manifestement des identités distinctes.
    """
    if target_id == source_id:
        raise ConflictError("Impossible de fusionner un éditeur avec lui-même")

    # 1. Détecter les journaux partageant un titre entre les deux éditeurs,
    #    vérifier les conflits ISSN, puis les fusionner.
    for pair in repo.find_shared_title_journal_pairs(target_id, source_id):
        for field in ("issn", "eissn", "issnl"):
            tv = pair[f"t_{field}"]
            sv = pair[f"s_{field}"]
            if tv and sv and tv != sv:
                raise ConflictError(
                    f"Conflit {field} lors de la fusion des revues "
                    f"(cible #{pair['target_journal_id']}: {tv}, "
                    f"source #{pair['source_journal_id']}: {sv}). "
                    f"Fusionner les revues manuellement d'abord."
                )
        merge_journals(cur, pair["target_journal_id"], pair["source_journal_id"], repo=repo)

    # 2-6. Le reste de la fusion (transferts, enrichissement, delete).
    repo.merge_publisher_into(target_id, source_id)

    emit_event(cur, "publisher.merged", "publisher", target_id, {"source_id": source_id})


def merge_journals(
    cur: Any, target_id: int, source_id: int, *, repo: JournalRepository
) -> None:
    """Fusionne le journal source dans le journal cible."""
    if target_id == source_id:
        raise ConflictError("Impossible de fusionner un journal avec lui-même")

    repo.merge_journal_into(target_id, source_id)
    emit_event(cur, "journal.merged", "journal", target_id, {"source_id": source_id})
