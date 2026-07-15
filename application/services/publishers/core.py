"""Service Éditeurs — écritures sur l'agrégat Publisher, transaction-agnostiques.

Toute écriture éditoriale passe par ce service. Le compteur dérivé `pub_count`, que le pipeline recalcule en bloc, s'écrit en SQL ensembliste (`infrastructure/queries/pipeline/pub_counts.py`), hors de ce service qui traite un éditeur à la fois.

Agrégat distinct de Journal, servi par son propre port (`PublisherRepository`). Un appelant qui ne touche qu'aux éditeurs (ex. `update_publisher` d'un router admin) charge cette seule surface.

La fusion d'éditeurs (`merge_publishers`) vit ici : c'est une opération de l'agrégat Publisher. Elle prend aussi le port `JournalRepository` pour détecter les journaux en conflit entre les deux éditeurs avant de déléguer les transferts SQL.
"""

from collections import Counter

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdate,
)
from application.services.journals.core import merge_journals
from domain.errors import (
    BlockingJournal,
    ConflictError,
    NotFoundError,
    PublisherMergeBlockedError,
    ValidationError,
)
from domain.normalize import normalize_text


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

    # 2-3. Match ou création par forme de nom, puis rattachement de l'openalex_id
    # (sur l'éditeur trouvé comme sur celui créé).
    pub_id, _ = repo.match_or_create_by_name_form(name.strip(), name_normalized)
    if openalex_id:
        repo.set_publisher_openalex_id_if_missing(pub_id, openalex_id)
    return pub_id


def update_publisher(
    publisher_id: int, *, update: PublisherUpdate, repo: PublisherRepository
) -> None:
    """Met à jour un éditeur à partir des champs explicitement fournis.

    Lève NotFoundError si l'éditeur n'existe pas, ValidationError si aucun champ n'est fourni.
    """
    if not update.model_fields_set:
        raise ValidationError("Aucun champ à mettre à jour")

    if not repo.publisher_exists(publisher_id):
        raise NotFoundError(f"Éditeur {publisher_id} introuvable")

    repo.update_publisher_fields(publisher_id, update)


def merge_publishers(
    target_id: int,
    source_id: int,
    *,
    conn: Connection,
    correction_queries: MetadataCorrectionQueries,
    publisher_repo: PublisherRepository,
    journal_repo: JournalRepository,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne l'éditeur source dans l'éditeur cible.

    Invariant métier : si deux journaux aux titres partagés entre les deux éditeurs portent des ISSN/eISSN/ISSN-L différents, la fusion est refusée (`ConflictError`) — leurs identités sont distinctes.

    La détection est côté `journal_repo` (requête sur `journals`), la fusion finale côté `publisher_repo` (transferts + delete).
    """
    if target_id == source_id:
        raise ConflictError("Impossible de fusionner un éditeur avec lui-même")

    # 1. Détecter les journaux partageant un titre entre les deux éditeurs.
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
        for field in ("issn", "eissn", "issnl"):
            tv = pair[f"t_{field}"]
            sv = pair[f"s_{field}"]
            if tv and sv and tv != sv:
                reasons.append(f"{field.upper()} différents : {tv} (cible) vs {sv} (source)")
                break
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
            pub_repo=pub_repo,
            audit_repo=audit_repo,
        )

    # 2-6. Le reste de la fusion (transferts, enrichissement, delete).
    publisher_repo.merge_publisher_into(target_id, source_id)

    emit_event(audit_repo, "publisher.merged", "publisher", target_id, {"source_id": source_id})
