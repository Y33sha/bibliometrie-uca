"""
Normalisation des données HAL : staging → tables structurées.

Usage:
    python normalize_hal.py              # traiter tous les works non traités
    python normalize_hal.py --limit 100  # traiter N works (pour test)
    python normalize_hal.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    source_publications                        (lien staging ↔ publication, source='hal')
    source_persons                          (auteurs unifiés, source='hal')
    source_authorships                      (lien document × auteur, source='hal', avec source_struct_ids)

La résolution UCA (source_authorships.structure_ids, in_perimeter) se fait en post-traitement
via populate_affiliations.py, pas ici. Ce script ne fait que stocker les source_struct_ids
(source_structures.id) extraits de authIdHasPrimaryStructure_fs.

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import logging
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection, Row

from application.journals import find_or_create_journal
from application.pipeline.normalize.base import SourceNormalizer
from application.ports.address_linker import AddressLinker
from application.ports.normalize_hal import HalNormalizeQueries
from application.ports.staging import StagingQueries
from application.ports.zenodo_resolver import ZenodoResolver
from application.publications import find_or_create as find_or_create_publication
from application.publications import refresh_from_sources, try_merge_by_doi
from application.publishers import find_or_create_publisher
from domain.authorship_roles import map_role
from domain.normalize import normalize_text
from domain.persons.identifiers import compact_identifiers, normalize_orcid
from domain.ports.journal_repository import JournalRepository
from domain.ports.publication_repository import PublicationRepository
from domain.ports.publisher_repository import PublisherRepository
from domain.publication import clean_doi, normalize_nnt
from domain.publications.dedup import has_minimal_publication_metadata
from domain.sources.hal import derive_hal_doc_type, derive_hal_oa_status
from domain.zenodo import ZenodoResolutionError, is_zenodo_doi

# =============================================================
# MAPPINGS
# =============================================================


# =============================================================
# UTILITAIRES
# =============================================================


def as_str(value: Any) -> str | None:
    """Extrait une chaîne depuis un champ HAL qui peut être str, list ou None."""
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return str(value)


def get_title(doc: dict) -> str:
    """Extrait le titre depuis les données HAL."""
    titles = doc.get("title_s")
    if isinstance(titles, list) and titles:
        return titles[0]
    if isinstance(titles, str):
        return titles
    label = doc.get("label_s", "")
    return label


# =============================================================
# PUBLISHERS & JOURNALS (via services/journals.py)
# =============================================================


def upsert_publisher(publisher_name: str, *, publisher_repo: PublisherRepository) -> int | None:
    """Trouve ou crée un éditeur. Délègue au service journals."""
    return find_or_create_publisher(publisher_name, repo=publisher_repo)


def upsert_journal(
    doc: dict, publisher_id: int | None, *, journal_repo: JournalRepository
) -> int | None:
    """Extrait et trouve/crée la revue depuis les champs HAL."""
    title = as_str(doc.get("journalTitle_s"))
    if not title:
        return None
    return find_or_create_journal(
        title,
        issn=as_str(doc.get("journalIssn_s")),
        eissn=as_str(doc.get("journalEissn_s")),
        publisher_id=publisher_id,
        repo=journal_repo,
    )


# =============================================================
# PUBLICATIONS (via services/publications.py)
# =============================================================


def extract_pub_metadata(doc: dict, journal_id: int | None) -> dict:
    """Extrait les metadonnees de publication d'un document HAL.

    Retourne un dict utilisable par find_or_create_publication.
    """
    doi = clean_doi(as_str(doc.get("doiId_s")))
    title = get_title(doc)
    pub_year = doc.get("producedDateY_i")

    doc_type = derive_hal_doc_type(doc.get("docType_s"), doc.get("docSubType_s"))

    language_list = doc.get("language_s")
    language = language_list[0] if isinstance(language_list, list) and language_list else None

    oa_status = derive_hal_oa_status(
        doc.get("openAccess_bool"),
        doc.get("fileMain_s"),
        doc.get("linkExtId_s"),
    )

    container_title = None
    if not journal_id:
        container_title = as_str(doc.get("bookTitle_s")) or as_str(doc.get("conferenceTitle_s"))

    nnt = normalize_nnt(as_str(doc.get("nntId_s")))

    return dict(
        title=title,
        title_normalized=normalize_text(title),
        pub_year=pub_year,
        doc_type=doc_type,
        doi=doi,
        nnt=nnt,
        oa_status=oa_status,
        journal_id=journal_id,
        container_title=container_title,
        language=language,
    )


def find_publication(
    doc: dict,
    journal_id: int | None,
    *,
    pub_repo: PublicationRepository,
) -> int | None:
    """Cherche une publication existante sans en créer. Retourne l'id ou None."""
    meta = extract_pub_metadata(doc, journal_id)
    if not meta["pub_year"] or not meta["title"]:
        return None
    pub_id, _ = find_or_create_publication(**meta, allow_create=False, repo=pub_repo)
    return pub_id


# =============================================================
# SOURCE DOCUMENTS (HAL)
# =============================================================


def insert_hal_document(
    conn: Connection,
    queries: HalNormalizeQueries,
    doc: dict,
    staging_id: int,
    hal_id: str,
    hal_collections_staging: list | None,
    publication_id: int | None,
    pub_meta: dict | None = None,
) -> int:
    """
    Crée/retrouve l'entrée source_publications pour HAL.
    Le champ hal_collections agrège toutes les collections vues.
    Retourne source_publications.id.
    """
    doi = clean_doi(as_str(doc.get("doiId_s")))
    title = get_title(doc)
    pub_year = doc.get("producedDateY_i")

    # Type + sous-type concaténés (ex: "ART_review-article")
    raw_type = doc.get("docType_s") or ""
    raw_sub = doc.get("docSubType_s") or ""
    doc_type = f"{raw_type}_{raw_sub}" if raw_sub else raw_type

    # Collections : depuis le staging (text[]) + collCode_s du raw_data
    collections = set()
    if hal_collections_staging:
        collections.update(hal_collections_staging)
    coll_codes = doc.get("collCode_s") or []
    if isinstance(coll_codes, list):
        collections.update(coll_codes)

    collections_array = sorted(collections) if collections else None

    # NNT dans external_ids (thèses HAL)
    nnt = normalize_nnt(as_str(doc.get("nntId_s")))
    external_ids = {"nnt": nnt} if nnt else None

    # Métadonnées de publication (pour création différée)
    journal_id = pub_meta.get("journal_id") if pub_meta else None
    oa_status = pub_meta.get("oa_status") if pub_meta else None
    language = pub_meta.get("language") if pub_meta else None
    container_title = pub_meta.get("container_title") if pub_meta else None

    # Abstract
    abstract = as_str(doc.get("abstract_s"))

    # Keywords
    kw_raw = doc.get("keyword_s")
    keywords = list(dict.fromkeys(kw_raw)) if isinstance(kw_raw, list) and kw_raw else None

    # Topics (domaines HAL)
    domain_raw = doc.get("domain_s")
    topics = {"hal_domains": domain_raw} if isinstance(domain_raw, list) and domain_raw else None

    # Biblio
    biblio = {}
    vol = as_str(doc.get("volume_s"))
    if vol:
        biblio["volume"] = vol
    issue = as_str(doc.get("issue_s"))
    if issue:
        biblio["issue"] = issue
    page = as_str(doc.get("page_s"))
    if page:
        biblio["pages"] = page
    biblio_json = biblio if biblio else None

    # URLs
    uri = as_str(doc.get("uri_s"))
    urls = [uri] if uri else None

    return queries.upsert_hal_source_publication(
        conn,
        hal_id=hal_id,
        doi=doi,
        title=title,
        pub_year=pub_year,
        doc_type=doc_type,
        hal_collections=collections_array,
        publication_id=publication_id,
        staging_id=staging_id,
        external_ids=external_ids,
        journal_id=journal_id,
        oa_status=oa_status,
        language=language,
        container_title=container_title,
        abstract=abstract,
        keywords=keywords,
        topics=topics,
        biblio=biblio_json,
        urls=urls,
    )


# =============================================================
# HAL AUTHORS (source_persons, source='hal')
# =============================================================


_TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def parse_tei_author_identifiers(label_xml: str | None) -> list[dict[str, str]]:
    """Extrait les identifiants par position d'auteur depuis le TEI HAL.

    L'API search HAL ne fournit pas de champ Solr aligné positionnellement
    pour ORCID/IdRef (les listes ``authORCIDIdExt_s``/``authIdRefIdExt_s``
    sont compactées). Seul le TEI (``label_xml``) attache proprement chaque
    identifiant à son auteur.

    Retourne une liste indexée sur la position d'auteur ; chaque entrée est
    un dict pouvant contenir ``orcid``, ``idref``, ``idhal`` (formes
    normalisées : préfixes d'URL strippés). Renvoie ``[]`` si ``label_xml``
    est absent ou mal formé.
    """
    if not label_xml:
        return []
    try:
        root = ET.fromstring(label_xml)
    except ET.ParseError:
        return []
    title_stmt = root.find(".//tei:biblFull/tei:titleStmt", _TEI_NS)
    if title_stmt is None:
        return []
    out: list[dict[str, str]] = []
    for author in title_stmt.findall("tei:author", _TEI_NS):
        ids: dict[str, str] = {}
        for idno in author.findall("tei:idno", _TEI_NS):
            typ = (idno.get("type") or "").upper()
            notation = (idno.get("notation") or "").lower()
            val = (idno.text or "").strip()
            if not val:
                continue
            if typ == "ORCID":
                orcid = normalize_orcid(val)
                if orcid:
                    ids["orcid"] = orcid
            elif typ == "IDREF":
                ids["idref"] = val.rsplit("/", 1)[-1].strip()
            elif typ == "IDHAL":
                # HAL emet souvent deux <idno type="idhal"> par auteur,
                # distingués par notation="string" (slug `prenom-nom`, le vrai
                # idhal) et notation="numeric" (le hal_person_id ré-étiqueté
                # idhal). Seul le slug nous intéresse ici — le hal_person_id
                # est capturé via le composite Solr.
                if notation != "string":
                    continue
                ids["idhal"] = val
        out.append(ids)
    return out


# =============================================================
# HAL AUTHORSHIPS
# =============================================================


def parse_author_structures(
    doc: dict,
    struct_name_by_hal_id: dict[str, str] | None = None,
) -> dict[int, set[str]]:
    """
    Parse les structures d'affiliation pour extraire le mapping
    `form_id → {halId_s natifs (text)}`.

    Format : "formId-personId_FacetSep_Nom_JoinSep_structId_FacetSep_StructNom"

    Préfère `authIdHasPrimaryStructure_fs` (uniquement la/les structure(s)
    primaire(s), càd labos feuilles), avec fallback sur `authIdHasStructure_fs`
    qui aplatit aussi l'arbre des tutelles. Évite de polluer la table `addresses`
    avec une entrée par tutelle parente alors que la résolution
    structure→tutelle se fait déjà via `structures_parents`.

    Si `struct_name_by_hal_id` est fourni, est rempli avec le mapping
    `halId_s → nom_structure` parsé depuis le document (utile pour
    construire les adresses).
    """
    entries = doc.get("authIdHasPrimaryStructure_fs") or doc.get("authIdHasStructure_fs") or []
    form_structs: dict[int, set[str]] = {}

    for entry in entries:
        parts = entry.split("_JoinSep_")
        if len(parts) != 2:
            continue

        # Gauche : "formId-personId_FacetSep_Nom"
        left_parts = parts[0].split("_FacetSep_")
        if not left_parts:
            continue
        form_person = left_parts[0]  # "49236-749496"
        dash_parts = form_person.rsplit("-", 1)
        if len(dash_parts) != 2:
            continue
        try:
            form_id = int(dash_parts[0])
        except ValueError:
            continue

        # Droite : "structId_FacetSep_StructNom"
        right_parts = parts[1].split("_FacetSep_")
        if not right_parts:
            continue
        struct_id_str = right_parts[0].strip()
        if not struct_id_str:
            continue
        struct_name = right_parts[1].strip() if len(right_parts) > 1 else ""

        form_structs.setdefault(form_id, set()).add(struct_id_str)
        if struct_name_by_hal_id is not None and struct_name:
            struct_name_by_hal_id.setdefault(struct_id_str, struct_name)

    return form_structs


def process_authors(
    conn: Connection,
    queries: HalNormalizeQueries,
    doc: dict,
    source_publication_id: int,
    *,
    address_linker: AddressLinker,
) -> None:
    """
    Traite les auteurs d'un document HAL :
    - Parse les champs alignés pour extraire hal_person_id, idhal et form_id
    - Parse authIdHasPrimaryStructure_fs pour les affiliations (clé = form_id)
    - Crée les source_authorships (source='hal', source_person_id=NULL) avec
      `source_structures` (TEXT[] des halId_s natifs) et `person_identifiers`
      (JSONB des orcid/idref/idhal/hal_person_id quand présents).

    Le pipeline n'écrit plus dans `source_persons` ni `source_structures`
    (tables en voie de suppression, cf. chantier
    `DATA_simplify-source-tables`).
    """
    # Pré-nettoyage : un re-traitement peut changer les auteurs/positions,
    # on repart d'une table blanche pour cette publi.
    queries.clear_source_authorships_for_publication(conn, source_publication_id)

    names = doc.get("authFullName_s") or []
    qualities = doc.get("authQuality_s") or []
    # ORCID et IdRef par auteur : parsés depuis le TEI (label_xml), seul
    # champ HAL qui les attache proprement à chaque position d'auteur.
    tei_ids = parse_tei_author_identifiers(doc.get("label_xml"))

    # authFullNameFormIDPersonIDIDHal_fs :
    #   "Nom_FacetSep_formId-personId_FacetSep_idhal" — aligné par position
    # C'est le champ le plus complet : on en extrait form_id, person_id et idhal
    composite = doc.get("authFullNameFormIDPersonIDIDHal_fs") or []
    form_id_by_pos: dict[int, int | None] = {}
    hal_person_id_by_pos: dict[int, int | None] = {}
    idhal_by_pos = {}

    for pos, entry in enumerate(composite):
        parts = entry.split("_FacetSep_")
        if len(parts) >= 2:
            # parts[1] = "formId-personId"
            dash_parts = parts[1].rsplit("-", 1)
            if len(dash_parts) == 2:
                try:
                    form_id_by_pos[pos] = int(dash_parts[0])
                except ValueError:
                    pass
                try:
                    pid = int(dash_parts[1])
                    if pid > 0:  # 0 = personne non identifiée par HAL
                        hal_person_id_by_pos[pos] = pid
                except ValueError:
                    pass
        if len(parts) >= 3 and parts[2].strip():
            idhal_by_pos[pos] = parts[2].strip()

    # Fallback : si authFullNameFormIDPersonIDIDHal_fs est absent,
    # on utilise les champs séparés (anciens documents)
    if not composite:
        name_idhal = doc.get("authFullNameIdHal_fs") or []
        for pos, entry in enumerate(name_idhal):
            parts = entry.split("_FacetSep_")
            if len(parts) == 2 and parts[1].strip():
                idhal_by_pos[pos] = parts[1].strip()

        name_id = doc.get("authFullNameId_fs") or []
        for pos, entry in enumerate(name_id):
            parts = entry.split("_FacetSep_")
            if len(parts) == 2 and parts[1].strip():
                try:
                    pid = int(parts[1].strip())
                    if pid > 0:
                        hal_person_id_by_pos[pos] = pid
                except ValueError:
                    pass

    # authIdHasPrimaryStructure_fs → {form_id: set of halId_s natifs (text)}
    # + mapping {halId_s: nom} local au document (pour construire les
    # adresses sans toucher à `source_structures`, table en voie de
    # suppression).
    struct_name_by_hal_id: dict[str, str] = {}
    form_struct_map = parse_author_structures(doc, struct_name_by_hal_id=struct_name_by_hal_id)

    for position, name in enumerate(names):
        idhal = idhal_by_pos.get(position)
        hal_person_id = hal_person_id_by_pos.get(position)
        form_id = form_id_by_pos.get(position)

        author_ids = tei_ids[position] if position < len(tei_ids) else {}
        orcid = author_ids.get("orcid")
        idref = author_ids.get("idref")
        # Si le TEI ne fournit pas idhal mais le composite Solr oui,
        # on garde celui-ci (composite Solr = fallback hors TEI).
        idhal = author_ids.get("idhal") or idhal

        # authQuality_s : rôle de l'auteur (aut, crp, dir, edt, …)
        quality = qualities[position] if position < len(qualities) else None
        roles, is_corresponding_from_role = map_role("hal", quality)
        is_corresponding = is_corresponding_from_role

        if not name:
            continue

        # Identifiants normalisés cross-source pour cette authorship.
        ids = compact_identifiers(
            orcid=orcid,
            idref=idref,
            idhal=idhal,
            hal_person_id=hal_person_id,
        )
        identifiers = ids if ids else None

        # Structures affiliées à cet auteur sur ce document (par form_id).
        # On stocke directement les halId_s natifs (TEXT[]) sur la sa, plus
        # de résolution vers `source_structures.id`.
        source_structures = None
        addr_parts: list[str] = []
        if form_id and form_id in form_struct_map:
            source_structures = sorted(form_struct_map[form_id])
            addr_parts = [
                struct_name_by_hal_id[hid]
                for hid in source_structures
                if hid in struct_name_by_hal_id and struct_name_by_hal_id[hid].strip()
            ]

        sa_id = queries.upsert_hal_source_authorship(
            conn,
            source_publication_id=source_publication_id,
            author_position=position,
            source_structures=source_structures,
            raw_author_name=name,
            is_corresponding=is_corresponding,
            roles=roles or None,
            person_identifiers=identifiers,
        )

        if addr_parts:
            address_linker.link(conn, sa_id, addr_parts)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: HalNormalizeQueries,
    logger: logging.Logger,
    staging_row: Row[Any],
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    pub_repo: PublicationRepository,
    zenodo_resolver: ZenodoResolver,
    staging_queries: StagingQueries,
    address_linker: AddressLinker,
) -> bool | None:
    """Traite un work du staging HAL."""
    from application.pipeline.timings import StepTimer

    staging_id, hal_id, doi, raw_data, hal_collections_staging = staging_row
    doc = raw_data

    try:
        t = StepTimer()
        title = get_title(doc)
        pub_year = doc.get("producedDateY_i")
        if not has_minimal_publication_metadata(title, pub_year):
            logger.warning(f"Impossible d'insérer {hal_id} — titre ou année manquant")
            return False

        raw_doi = clean_doi(as_str(doc.get("doiId_s")))
        if raw_doi and is_zenodo_doi(raw_doi):
            try:
                version_doi = zenodo_resolver.resolve(raw_doi)
            except ZenodoResolutionError as e:
                logger.warning(f"  {hal_id} Zenodo {raw_doi} : {e} — retenté au prochain run")
                return False
            if version_doi:
                if queries.staging_has_hal_doi(conn, version_doi):
                    logger.info(
                        f"  {hal_id} concept DOI Zenodo {raw_doi} -> "
                        f"version {version_doi} deja en staging, skip"
                    )
                    staging_queries.mark_done(conn, staging_id)
                    return None

        publisher_name = as_str(doc.get("journalPublisher_s")) or as_str(doc.get("publisher_s"))
        publisher_id = (
            upsert_publisher(publisher_name, publisher_repo=publisher_repo)
            if publisher_name
            else None
        )
        journal_id = upsert_journal(doc, publisher_id, journal_repo=journal_repo)
        t.mark("publisher+journal")

        pub_meta = extract_pub_metadata(doc, journal_id)

        publication_id = None
        old_pub_id = queries.get_hal_publication_id(conn, hal_id)
        if old_pub_id:
            publication_id = find_publication(doc, journal_id, pub_repo=pub_repo)
            if publication_id and publication_id != old_pub_id:
                from application.publications import merge_publications

                logger.info(f"  {hal_id} : fusion pub {old_pub_id} → {publication_id} (DOI/NNT)")
                merge_publications(publication_id, old_pub_id, repo=pub_repo)
            elif not publication_id:
                publication_id = old_pub_id
        else:
            publication_id = find_publication(doc, journal_id, pub_repo=pub_repo)
        t.mark("publication")

        if publication_id:
            publication_id = try_merge_by_doi(
                publication_id, clean_doi(as_str(doc.get("doiId_s"))), repo=pub_repo
            )

        source_publication_id = insert_hal_document(
            conn,
            queries,
            doc,
            staging_id,
            hal_id,
            hal_collections_staging,
            publication_id,
            pub_meta,
        )
        t.mark("hal_doc")

        process_authors(
            conn,
            queries,
            doc,
            source_publication_id,
            address_linker=address_linker,
        )
        t.mark("authors")

        if publication_id:
            refresh_from_sources(publication_id, repo=pub_repo)
        t.mark("refresh")

        staging_queries.mark_done(conn, staging_id)
        t.log_if_slow(hal_id, logger)

        return True

    except Exception as e:
        logger.error(f"Erreur sur {hal_id}: {e}")
        raise


class HalNormalizer(SourceNormalizer):
    SOURCE = "hal"
    DEFAULT_BATCH_SIZE = 500
    USE_DICT_CURSOR = False
    USE_SAVEPOINT = True
    FETCH_COLUMNS = "id, source_id, doi, raw_data, hal_collections"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: HalNormalizeQueries,
        journal_repo_factory: Callable[[Any], JournalRepository],
        publisher_repo_factory: Callable[[Any], PublisherRepository],
        pub_repo_factory: Callable[[Any], PublicationRepository],
        zenodo_resolver: ZenodoResolver,
        address_linker: AddressLinker,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._journal_repo_factory = journal_repo_factory
        self._journal_repo: JournalRepository | None = None
        self._publisher_repo_factory = publisher_repo_factory
        self._publisher_repo: PublisherRepository | None = None
        self._pub_repo_factory = pub_repo_factory
        self._pub_repo: PublicationRepository | None = None
        self._zenodo_resolver = zenodo_resolver
        self._address_linker = address_linker

    def preload_caches(self, conn: Connection) -> None:
        self._journal_repo = self._journal_repo_factory(conn)
        self._publisher_repo = self._publisher_repo_factory(conn)
        self._pub_repo = self._pub_repo_factory(conn)

    def process_work(self, conn: Connection, row: Row[Any]) -> bool | None:
        assert self._journal_repo is not None, "preload_caches doit être appelé avant"
        assert self._publisher_repo is not None, "preload_caches doit être appelé avant"
        assert self._pub_repo is not None, "preload_caches doit être appelé avant"
        return process_work(
            conn,
            self._queries,
            self.logger,
            row,
            journal_repo=self._journal_repo,
            publisher_repo=self._publisher_repo,
            pub_repo=self._pub_repo,
            zenodo_resolver=self._zenodo_resolver,
            staging_queries=self._staging,
            address_linker=self._address_linker,
        )

    def post_process(self, conn: Connection) -> None:
        self._queries.delete_hal_duplicate_authorship_addresses(conn)
        deleted_dups = self._queries.delete_hal_duplicate_authorships(conn)
        if deleted_dups:
            self.logger.info(f"Doublons de position supprimés : {deleted_dups}")

    def cleanup(self) -> None:
        self._address_linker.clear_cache()

    def on_error(self) -> None:
        # Le cache adresse peut contenir des IDs insérés dans la
        # transaction qui vient d'être rollbackée — l'invalider évite
        # les FK violations sur les works suivants.
        self._address_linker.clear_cache()
