"""
Service Éditeurs — accès exclusif en écriture à la table `publishers`.

Séparé de `application/journals.py` (principe SRP) : publishers et
journals sont deux agrégats distincts, servis par deux ports distincts
(`PublisherRepository`, `JournalRepository`). Un caller qui ne touche
qu'aux éditeurs (ex. `update_publisher` d'un router admin) n'a pas à
charger la surface journaux.

La fusion d'éditeurs (`merge_publishers`) reste ici parce que
sémantiquement c'est une opération sur l'agrégat Publisher ; elle a
besoin du port `JournalRepository` en complément pour détecter les
journaux à conflit entre les deux éditeurs à fusionner avant de
déléguer les transferts SQL.
"""

from application.audit import emit_event
from application.journals import merge_journals
from domain.errors import ConflictError, NotFoundError, ValidationError
from domain.json_types import JsonValue
from domain.normalize import normalize_text
from domain.ports.audit_repository import AuditRepository
from domain.ports.journal_repository import JournalRepository
from domain.ports.publisher_repository import PublisherRepository


def find_or_create_publisher(
    name: str | None,
    *,
    openalex_id: str | None = None,
    repo: PublisherRepository,
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


def update_publisher(
    publisher_id: int, *, fields: dict[str, JsonValue], repo: PublisherRepository
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
        name = fields["name"]
        assert isinstance(name, str), "fields['name'] doit être un str (validé par Pydantic)"
        fields["name_normalized"] = normalize_text(name)
    repo.update_publisher_fields(publisher_id, fields)


def merge_publishers(
    target_id: int,
    source_id: int,
    *,
    publisher_repo: PublisherRepository,
    journal_repo: JournalRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne l'éditeur source dans l'éditeur cible.

    Invariant métier : s'il y a des journaux aux titres partagés entre
    les deux éditeurs avec des ISSN/eISSN/ISSN-L différents, la fusion
    est refusée (ConflictError) — on ne veut pas fusionner deux
    journaux qui ont manifestement des identités distinctes.

    La détection est côté `journal_repo` (query sur `journals`), la
    fusion finale est côté `publisher_repo` (transferts + delete).
    """
    if target_id == source_id:
        raise ConflictError("Impossible de fusionner un éditeur avec lui-même")

    # 1. Détecter les journaux partageant un titre entre les deux éditeurs,
    #    vérifier les conflits ISSN, puis les fusionner.
    for pair in journal_repo.find_shared_title_journal_pairs(target_id, source_id):
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
        merge_journals(
            pair["target_journal_id"],
            pair["source_journal_id"],
            repo=journal_repo,
            audit_repo=audit_repo,
        )

    # 2-6. Le reste de la fusion (transferts, enrichissement, delete).
    publisher_repo.merge_publisher_into(target_id, source_id)

    emit_event(audit_repo, "publisher.merged", "publisher", target_id, {"source_id": source_id})
