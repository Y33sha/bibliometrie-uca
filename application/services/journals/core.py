"""Service Journaux — écritures sur l'agrégat Journal, transaction-agnostiques.

Toute écriture éditoriale passe par ce service, pipeline compris (`find_or_create_journal` au normalize). Les colonnes dérivées que le pipeline recalcule en bloc — `pub_count`, drapeau `is_in_doaj` — s'écrivent en SQL ensembliste (`infrastructure/queries/pipeline/`), hors de ce service qui traite une revue à la fois.

Les opérations sur l'agrégat Publisher vivent dans `application/services/publishers/core.py` ; les deux agrégats restent liés par `journals.publisher_id` (FK), chacun manipulé par son propre service et son propre port.

Un champ éditable d'une revue commande le `doc_type` de ses publications : le `journal_type` alimente des règles de correction. D'où `requalify_publications_for_journal` et le volet requalification de `merge_journals`, qui rejouent ces corrections sur le stock après une édition.
"""

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.pipeline.metadata_correction.correct_unary import compute_update
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository, JournalUpdate
from application.ports.repositories.publication_repository import PublicationRepository
from application.services.publications.core import refresh_from_sources
from domain.errors import NotFoundError, ValidationError
from domain.journals.journal import OaModel
from domain.normalize import normalize_text


def find_or_create_journal(
    title: str | None,
    *,
    issn: str | None = None,
    eissn: str | None = None,
    issnl: str | None = None,
    publisher_id: int | None = None,
    openalex_id: str | None = None,
    oa_model: OaModel | None = None,
    repo: JournalRepository,
) -> int | None:
    """Trouve ou crée un journal. Retourne son id, ou `None` si le titre est vide.

    Cascade de recherche : `openalex_id`, puis chacun des identifiants ISSN fournis (`issn`, `eissn`, `issnl`) cherché indifféremment dans les trois colonnes, puis le titre normalisé parmi les formes de nom. Sans correspondance, le journal est créé.

    Un journal trouvé voit ses métadonnées manquantes enrichies, et le titre reçu enregistré comme forme de nom — les variantes s'accumulent pour les matchs par titre suivants.
    """
    if not title:
        return None

    title_normalized = normalize_text(title)

    def _match_and_enrich(journal_id: int, *, with_openalex: bool = True) -> int:
        """Enrichit le journal trouvé et enregistre son titre en forme de nom — accumulation des variantes pour un futur match par titre. Retourne son id."""
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
        issn=issn,
        eissn=eissn,
        issnl=issnl,
        publisher_id=publisher_id,
        openalex_id=openalex_id,
        oa_model=oa_model,
    )
    repo.add_journal_name_form(journal_id, title_normalized, publisher_id)
    return journal_id


def update_journal(journal_id: int, *, update: JournalUpdate, repo: JournalRepository) -> None:
    """Met à jour une revue à partir des champs explicitement fournis.

    Lève `ValidationError` si aucun champ n'est fourni, `NotFoundError` si la revue n'existe pas — l'`UPDATE` du repository ne trouve alors aucune ligne à apparier.
    """
    if not update.model_fields_set:
        raise ValidationError("Aucun champ à mettre à jour")

    repo.update_journal_fields(journal_id, update)


def update_journal_apc(
    journal_id: int,
    *,
    apc_amount: float | None = None,
    apc_currency: str | None = None,
    repo: JournalRepository,
) -> None:
    """Met à jour les informations APC d'un journal.

    Sans vérification d'existence, à la différence d'`update_journal` : l'appelant est la phase `publishers_journals`, qui boucle sur des ids issus d'une requête.
    """
    repo.update_journal_apc(
        journal_id,
        apc_amount=apc_amount,
        apc_currency=apc_currency,
    )


def _correct_for_journal(
    conn: Connection, queries: MetadataCorrectionQueries, journal_id: int
) -> int:
    """Recalcule et persiste les corrections unaires des `source_publications` d'un journal, après un changement de son `journal_type`. Retourne le nombre de `source_publications` corrigées.

    À enchaîner avec `refresh_from_sources` des publications du journal, qui repart de la colonne `source_publication` rafraîchie ici.
    """
    rows = queries.fetch_for_unary_correction_by_journal(conn, journal_id)
    updates = [u for row in rows if (u := compute_update(row)) is not None]
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
    if target_id == source_id:
        raise ValidationError("Impossible de fusionner un journal avec lui-même")
    if repo.find_by_id(target_id) is None:
        raise NotFoundError("Revue cible introuvable")
    if repo.find_by_id(source_id) is None:
        raise NotFoundError("Revue source introuvable")

    # Capturer les publications du source avant le repoint, pour les rafraîchir.
    absorbed_pub_ids = publication_repo.find_ids_by_journal_id(source_id)

    repo.merge_journal_into(target_id, source_id)

    # Les enregistrements absorbés portent maintenant `journal_id = target` : recalcule en
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
