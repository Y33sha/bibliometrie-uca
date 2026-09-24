"""Service Éditeurs — écritures sur l'agrégat Publisher, transaction-agnostiques.

Toute écriture éditoriale passe par ce service. Le compteur dérivé `pub_count`, que le pipeline recalcule en bloc, s'écrit en SQL ensembliste (`infrastructure/pipeline/authorships/pub_counts.py`), hors de ce service qui traite un éditeur à la fois.

Agrégat distinct de Journal, servi par son propre port (`PublisherRepository`). Un appelant qui ne touche qu'aux éditeurs (ex. `update_publisher` d'un router admin) charge cette seule surface.

La fusion d'éditeurs (`merge_publishers`) vit ici : c'est une opération de l'agrégat Publisher. Elle prend aussi le port `JournalRepository` pour détecter les journaux en conflit entre les deux éditeurs avant de déléguer les transferts SQL.
"""

from collections import Counter

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.pipeline.publishers import PublisherFindOrCreateQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdate,
)
from application.services._merge import load_merge_pair
from application.services.journals.core import merge_journals
from domain.errors import (
    BlockingJournal,
    ConflictError,
    NotFoundError,
    PublisherMergeBlockedError,
    ValidationError,
)
from domain.journals.issns import issn_conflict
from domain.normalize import normalize_text, to_plain_text
from domain.publishers.members import crossref_member_conflict
from domain.publishers.names import publisher_name_key


def find_or_create_publisher(
    name: str | None,
    *,
    openalex_id: str | None = None,
    repo: PublisherFindOrCreateQueries,
) -> int | None:
    """Trouve ou crée un éditeur.

    Cascade de recherche :
    1. openalex_id (si fourni)
    2. publisher_name_forms, par la clé de nom (`publisher_name_key`)
    3. Création + enregistrement de la forme de nom

    Retourne publisher.id ou None si name est vide.
    """
    if not name:
        return None

    # 1. Par openalex_id
    if openalex_id:
        pub_id = repo.find_publisher_by_openalex_id(openalex_id)
        if pub_id:
            name_key = publisher_name_key(to_plain_text(name))
            if name_key:
                repo.add_publisher_name_form(pub_id, name_key)
            return pub_id

    # 2-3. Match ou création par forme de nom, puis rattachement de l'openalex_id
    # (sur l'éditeur trouvé comme sur celui créé).
    matched = match_or_create_publisher(name, repo=repo)
    if matched is None:
        return None
    pub_id, _ = matched
    if openalex_id:
        repo.set_publisher_openalex_id_if_missing(pub_id, openalex_id)
    return pub_id


def match_or_create_publisher(
    name: str, *, repo: PublisherFindOrCreateQueries
) -> tuple[int, bool] | None:
    """`(id, created)` de l'éditeur que désigne `name`, retrouvé par sa clé de nom ou créé. `None` si le nom ne garde rien à la normalisation.

    Le nom est mis à plat d'abord : le nom affiché, le nom normalisé et la clé en dérivent tous (cf. `find_or_create_journal`).
    """
    name = to_plain_text(name)
    name_normalized = normalize_text(name)
    name_key = publisher_name_key(name)
    if not name_normalized or not name_key:
        return None
    return repo.match_or_create_by_name_form(name, name_normalized, name_key)


def update_publisher(
    publisher_id: int,
    *,
    update: PublisherUpdate,
    repo: PublisherRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Charge l'éditeur, applique les champs explicitement fournis, persiste.

    L'événement d'audit ne porte que les champs soumis : y joindre les autres laisserait croire qu'ils ont été fournis.

    Lève `ValidationError` si aucun champ n'est fourni, `NotFoundError` si l'éditeur n'existe pas.
    """
    if not update.model_fields_set:
        raise ValidationError("Aucun champ à mettre à jour")

    publisher = repo.find_by_id(publisher_id)
    if publisher is None:
        raise NotFoundError(f"Éditeur {publisher_id} introuvable")

    # Les champs de `PublisherUpdate` portent les noms des attributs de l'agrégat.
    champs = update.model_dump(exclude_unset=True, mode="json")
    for field_name, value in update.model_dump(exclude_unset=True).items():
        setattr(publisher, field_name, value)
    repo.save(publisher)
    emit_event(audit_repo, "publisher.updated", "publisher", publisher_id, champs)


def merge_publishers(
    target_id: int,
    source_id: int,
    *,
    conn: Connection,
    correction_queries: MetadataCorrectionQueries,
    publisher_repo: PublisherRepository,
    journal_repo: JournalRepository,
    publication_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne l'éditeur source dans l'éditeur cible.

    Deux invariants métier refusent la fusion (`ConflictError`), chacun sur une identité déclarée : des membres Crossref distincts de part et d'autre, ou deux journaux au titre partagé dont les ISSN diffèrent.

    La détection est côté `journal_repo` (requête sur `journals`), la fusion finale côté `publisher_repo` (transferts + delete).

    Lève `ValidationError` sur deux identifiants égaux, `NotFoundError` sur un éditeur introuvable.
    """
    load_merge_pair(target_id, source_id, publisher_repo.find_by_id, label="Éditeur")

    # 1. Deux identités Crossref distinctes désignent deux éditeurs : la fusion s'arrête là.
    if conflict := crossref_member_conflict(
        publisher_repo.crossref_member_ids(target_id),
        publisher_repo.crossref_member_ids(source_id),
    ):
        raise ConflictError(f"Fusion refusée, {conflict} (cible / source)")

    # 2. Détecter les journaux partageant un titre entre les deux éditeurs.
    #    Collecter toutes les paires bloquantes en une passe pour lever
    #    PublisherMergeBlockedError avec l'ensemble — l'UI les affiche
    #    d'un coup.
    pairs = journal_repo.find_shared_title_journal_pairs(target_id, source_id)
    # Si un journal apparaît dans plusieurs paires, l'éditeur correspondant
    # contient un doublon interne (2 journaux au même title_normalized). La
    # fusion N→1 casserait (la source supprimée puis rechargée). On signale
    # toutes les paires concernées comme bloquantes.
    target_seen = Counter(p["target_journal_id"] for p in pairs)
    source_seen = Counter(p["source_journal_id"] for p in pairs)
    blockers: list[BlockingJournal] = []
    mergeable_pairs = []
    for pair in pairs:
        reasons: list[str] = []
        if target_seen[pair["target_journal_id"]] > 1:
            reasons.append("doublon interne dans l'éditeur cible (titre dédupliqué)")
        if source_seen[pair["source_journal_id"]] > 1:
            reasons.append("doublon interne dans l'éditeur source (titre dédupliqué)")
        if conflict := issn_conflict(pair["t_issns"], pair["s_issns"]):
            reasons.append(f"{conflict} (cible / source)")
        if reasons:
            blockers.append(
                BlockingJournal(
                    target_journal_id=pair["target_journal_id"],
                    target_title=pair["t_title"],
                    source_journal_id=pair["source_journal_id"],
                    source_title=pair["s_title"],
                    reason=" ; ".join(reasons),
                )
            )
        else:
            mergeable_pairs.append(pair)
    if blockers:
        raise PublisherMergeBlockedError(blockers)

    for pair in mergeable_pairs:
        merge_journals(
            pair["target_journal_id"],
            pair["source_journal_id"],
            conn=conn,
            correction_queries=correction_queries,
            repo=journal_repo,
            publication_repo=publication_repo,
            audit_repo=audit_repo,
        )

    # 2-6. Le reste de la fusion (transferts, enrichissement, delete).
    publisher_repo.merge_publisher_into(target_id, source_id)

    emit_event(audit_repo, "publisher.merged", "publisher", target_id, {"source_id": source_id})
