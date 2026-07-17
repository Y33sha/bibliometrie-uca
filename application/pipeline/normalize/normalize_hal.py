"""Normalisation des données HAL : staging → tables structurées."""

import logging
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date

from sqlalchemy import Connection

from application.pipeline.normalize._authorships_batch import (
    AddressRecord,
    AuthorRecord,
    write_source_authorships,
)
from application.pipeline.normalize.base import SourceNormalizer
from application.pipeline.timings import StepTimer
from application.ports.pipeline.normalize.authorships import AuthorshipsBatchQueries
from application.ports.pipeline.normalize.source_publications import (
    SourcePublicationQueries,
    SourcePublicationRow,
)
from application.ports.pipeline.normalize.staging import StagingQueries, StagingRow
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import PublisherRepository
from application.services.journals.core import find_or_create_journal
from application.services.publishers.core import find_or_create_publisher
from domain.persons.identifiers import (
    compact_identifiers,
    mark_shared_identifiers_dubious,
    normalize_orcid,
)
from domain.publications.authorship_roles import map_role
from domain.publications.identifiers import (
    clean_doi,
    normalize_arxiv_id,
    normalize_nnt,
    normalize_pmcid,
    normalize_pmid,
)
from domain.publications.metadata import has_minimal_publication_metadata
from domain.sources.hal import derive_hal_oa_status
from domain.types import JsonValue

# =============================================================
# UTILITAIRES
# =============================================================


def as_str(value: object) -> str | None:
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
# PUBLISHERS & JOURNALS
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
# PUBLICATIONS
# =============================================================


def extract_pub_metadata(doc: dict, journal_id: int | None) -> dict:
    """Extrait les métadonnées de publication d'un document HAL.

    Retourne un dict utilisable par `insert_hal_document`. Toutes les valeurs sont brutes — pas de transformation de cohérence. `doc_type` est le concat brut `docType_s_docSubType_s` (ex. `ART_review-article`), pas la valeur canonique : la résolution source→enum (`map_doc_type`) relève de la phase `metadata_correction`, pas du brut stocké dans `source_publications`.
    """
    title = get_title(doc)
    raw_type = doc.get("docType_s") or ""
    raw_sub = doc.get("docSubType_s") or ""
    doc_type = f"{raw_type}_{raw_sub}" if raw_sub else raw_type or None

    language_list = doc.get("language_s")
    language = language_list[0] if isinstance(language_list, list) and language_list else None

    container_title = None
    if not journal_id:
        container_title = as_str(doc.get("bookTitle_s")) or as_str(doc.get("conferenceTitle_s"))

    embargo_until = active_embargo_until(doc.get("label_xml"), date.today())

    return dict(
        title=title,
        pub_year=doc.get("producedDateY_i"),
        doc_type=doc_type,
        doi=clean_doi(as_str(doc.get("doiId_s"))),
        nnt=normalize_nnt(as_str(doc.get("nntId_s"))),
        oa_status=derive_hal_oa_status(
            doc.get("openAccess_bool"),
            doc.get("fileMain_s"),
            doc.get("linkExtId_s"),
            embargo_until,
        ),
        embargo_until=embargo_until,
        journal_id=journal_id,
        container_title=container_title,
        language=language,
    )


# =============================================================
# SOURCE DOCUMENTS (HAL)
# =============================================================


def build_hal_external_ids(doc: dict, hal_id: str, nnt: str | None) -> dict[str, JsonValue]:
    """Construit `external_ids` (clés de déduplication cross-source) pour un doc HAL.

    `hal_id` est redondant avec `source_id` côté identité, mais on le pose aussi ici pour qu'il devienne un **token de confirmation** (cf. `domain.source_publications.keys`) et que HAL soit clusterisé comme les autres sources — symétrie avec ce que theses fait déjà pour NNT. `pmid` vient du champ `pubmedid_s` ; `pmcid`/`arxiv_id` des liens externes (`linkExtUrl_s`).
    """
    external_ids: dict[str, JsonValue] = {"hal_id": [hal_id]}
    if nnt:
        external_ids["nnt"] = nnt
    if pmid := normalize_pmid(as_str(doc.get("pubmedid_s"))):
        external_ids["pmid"] = pmid
    link_urls = doc.get("linkExtUrl_s")
    if isinstance(link_urls, str):
        link_urls = [link_urls]
    for url in link_urls or []:
        if "pmcid" not in external_ids and (pmcid := normalize_pmcid(url)):
            external_ids["pmcid"] = pmcid
        if "arxiv_id" not in external_ids and (arxiv_id := normalize_arxiv_id(url)):
            external_ids["arxiv_id"] = arxiv_id
    return external_ids


def insert_hal_document(
    conn: Connection,
    queries: SourcePublicationQueries,
    doc: dict,
    staging_id: int,
    hal_id: str,
    pub_meta: dict,
) -> int:
    """Crée/retrouve l'entrée source_publications pour HAL.

    Les métadonnées canoniques (doi, title, pub_year, doc_type, nnt,
    journal_id, oa_status, language, container_title) viennent toutes de
    `pub_meta`, construit en amont par `extract_pub_metadata`. `doc`
    ne sert ici que pour les extras HAL-spécifiques (collections, abstract,
    keywords, domaines, biblio, urls).
    """
    # Collections : `collCode_s` du raw_data (liste complète des collections du record).
    coll_codes = doc.get("collCode_s") or []
    collections_array = (
        sorted(set(coll_codes)) if isinstance(coll_codes, list) and coll_codes else None
    )

    external_ids = build_hal_external_ids(doc, hal_id, pub_meta["nnt"])

    # Abstract
    abstract = as_str(doc.get("abstract_s"))

    # Keywords
    kw_raw = doc.get("keyword_s")
    keywords = list(dict.fromkeys(kw_raw)) if isinstance(kw_raw, list) and kw_raw else None

    # Topics : domaines HAL, stockés tels que la source les expose (code + chemin de libellés).
    domain_raw = doc.get("fr_domainAllCodeLabel_fs")
    topics = {"hal_domains": domain_raw} if isinstance(domain_raw, list) and domain_raw else None

    # Biblio
    biblio: dict[str, JsonValue] = {}
    vol = as_str(doc.get("volume_s"))
    if vol:
        biblio["volume"] = vol
    issue = as_str(doc.get("issue_s"))
    if issue:
        biblio["issue"] = issue
    page = as_str(doc.get("page_s"))
    if page:
        biblio["pages"] = page

    # Publisher + journal bruts (traçabilité du nom tel que vu par HAL, en parallèle de publishers/journals créés via find_or_create_*).
    publisher_raw = as_str(doc.get("journalPublisher_s")) or as_str(doc.get("publisher_s"))
    if publisher_raw:
        biblio["publisher"] = publisher_raw
    journal_obj: dict[str, str] = {}
    if jt := as_str(doc.get("journalTitle_s")):
        journal_obj["title"] = jt
    if jissn := as_str(doc.get("journalIssn_s")):
        journal_obj["issn"] = jissn
    if jeissn := as_str(doc.get("journalEissn_s")):
        journal_obj["eissn"] = jeissn
    if journal_obj:
        biblio["journal"] = journal_obj

    biblio_json = biblio if biblio else None

    # URLs
    uri = as_str(doc.get("uri_s"))
    urls = [uri] if uri else None

    return queries.upsert_source_publication(
        conn,
        SourcePublicationRow(
            source="hal",
            source_id=hal_id,
            staging_id=staging_id,
            doi=pub_meta["doi"],
            external_ids=external_ids,
            title=pub_meta["title"] or "",
            pub_year=pub_meta["pub_year"],
            doc_type=pub_meta["doc_type"],
            journal_id=pub_meta["journal_id"],
            container_title=pub_meta["container_title"],
            language=pub_meta["language"],
            biblio=biblio_json,
            abstract=abstract,
            keywords=keywords,
            topics=topics,
            oa_status=pub_meta["oa_status"],
            urls=urls,
            embargo_until=pub_meta["embargo_until"],
            hal_collections=collections_array,
        ),
    )


# =============================================================
# HAL AUTHORS — parsing identifiants depuis le TEI
# =============================================================


_TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def active_embargo_until(label_xml: str | None, today: date) -> date | None:
    """Date de fin d'un embargo HAL **encore actif** (future), sinon None.

    Lit `ref[@type='file']/date/@notBefore` du TEI (`label_xml`) : la date à laquelle le fichier déposé devient accessible. Plusieurs refs `type='file'` (page + document) : on retient la plus tardive. Une date déjà échue (fichier accessible) renvoie None — pas d'embargo actif, on ne stocke pas d'historique. La levée à l'échéance d'une date future stockée est portée par une règle de correction `oa_status`, sans dépendre d'un ré-import HAL.
    """
    if not label_xml:
        return None
    try:
        root = ET.fromstring(label_xml)
    except ET.ParseError:
        return None
    dates: list[date] = []
    for ref in root.iter(f"{{{_TEI_NS['tei']}}}ref"):
        if ref.get("type") != "file":
            continue
        date_el = ref.find("tei:date", _TEI_NS)
        if date_el is None:
            continue
        not_before = date_el.get("notBefore")
        if not_before:
            try:
                dates.append(date.fromisoformat(not_before))
            except ValueError:
                continue
    if not dates:
        return None
    latest = max(dates)
    return latest if latest > today else None


def parse_tei_author_identifiers(label_xml: str | None) -> list[dict[str, str]]:
    """Extrait les identifiants par position d'auteur depuis le TEI HAL.

    L'API search HAL ne fournit pas de champ Solr aligné positionnellement pour ORCID/IdRef (les listes `authORCIDIdExt_s`/`authIdRefIdExt_s` sont compactées). Seul le TEI (`label_xml`) attache proprement chaque identifiant à son auteur.

    Retourne une liste indexée sur la position d'auteur ; chaque entrée est un dict pouvant contenir `orcid`, `idref`, `idhal` (formes normalisées : préfixes d'URL strippés). Renvoie `[]` si `label_xml` est absent ou mal formé.
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
                # HAL émet souvent deux <idno type="idhal"> par auteur, distingués par notation="string" (slug `prenom-nom`, le vrai idhal) et notation="numeric" (le hal_person_id ré-étiqueté idhal).
                # Seul le slug nous intéresse ici — le hal_person_id est capturé via le composite Solr.
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
    """Parse les structures d'affiliation pour extraire le mapping `form_id → {halId_s natifs (text)}`.

    Format : "formId-personId_FacetSep_Nom_JoinSep_structId_FacetSep_StructNom"

    Préfère `authIdHasPrimaryStructure_fs` (uniquement la/les structure(s) primaire(s), c'est-à-dire les laboratoires feuilles), avec fallback sur `authIdHasStructure_fs` qui aplatit aussi l'arbre des tutelles. Évite de polluer la table `addresses` avec une entrée par tutelle parente alors que la résolution structure→tutelle se fait déjà via `structures_parents`.

    Si `struct_name_by_hal_id` est fourni, est rempli avec le mapping `halId_s → nom_structure` parsé depuis le document (utile pour construire les adresses).
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


def build_hal_author_records(doc: dict) -> list[AuthorRecord]:
    """Parse les auteurs d'un document HAL en `AuthorRecord` (sans I/O).

    - Parse les champs alignés pour extraire hal_person_id, idhal et form_id
    - Parse authIdHasPrimaryStructure_fs pour les affiliations (clé = form_id)
    - Produit pour chaque auteur les `person_identifiers` (orcid/idref/idhal/hal_person_id quand présents) et `addresses` (noms de structures).

    Un `hal_person_id` listé sur plusieurs auteurs du même dépôt (erreur de saisie HAL) rend toute l'identité de ces signatures douteuse : tous les identifiants (hal_person_id/idref/idhal/orcid, attachés au compte HAL) sont alors rangés sous une clé suffixée `_dubious` — valeur conservée mais écartée du matching personnes.
    """
    qualities = doc.get("authQuality_s") or []
    # ORCID et IdRef par auteur : parsés depuis le TEI (label_xml), seul champ HAL qui les attache proprement à chaque position d'auteur.
    tei_ids = parse_tei_author_identifiers(doc.get("label_xml"))

    # authFullNameFormIDPersonIDIDHal_fs :
    #   "Nom_FacetSep_formId-personId_FacetSep_idhal" — aligné par position.
    # Présence validée par le caller ; on en extrait nom, form_id, person_id.
    # Le 3e segment (idhal) est IGNORÉ : non fiable — quand l'auteur n'a pas de slug, HAL y recopie le person_id numérique, ce qui injecterait de faux idhal numériques (== hal_person_id).
    # L'idhal vient du seul TEI (`parse_tei_author_identifiers`, qui ne garde que notation="string").
    composite = doc.get("authFullNameFormIDPersonIDIDHal_fs") or []
    names = [entry.split("_FacetSep_", 1)[0] for entry in composite]
    form_id_by_pos: dict[int, int | None] = {}
    hal_person_id_by_pos: dict[int, int | None] = {}

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

    # authIdHasPrimaryStructure_fs → {form_id: ensemble de halId_s natifs (text)} + mapping {halId_s: nom} local au document (pour construire les adresses).
    struct_name_by_hal_id: dict[str, str] = {}
    form_struct_map = parse_author_structures(doc, struct_name_by_hal_id=struct_name_by_hal_id)

    # Identifiants normalisés par position, puis requalification des partagés : un même identifiant (compte HAL, ORCID, idref…) porté par ≥2 signatures du *même dépôt* est une corruption de saisie (un identifiant ne peut pas désigner deux signatures dans un même document) → suffixé `_dubious`, conservé mais invisible au matching personnes.
    ids_by_position = mark_shared_identifiers_dubious(
        [
            compact_identifiers(
                orcid=(tei_ids[pos].get("orcid") if pos < len(tei_ids) else None),
                idref=(tei_ids[pos].get("idref") if pos < len(tei_ids) else None),
                idhal=(tei_ids[pos].get("idhal") if pos < len(tei_ids) else None),
                hal_person_id=hal_person_id_by_pos.get(pos),
            )
            for pos in range(len(names))
        ]
    )

    records: list[AuthorRecord] = []
    for position, name in enumerate(names):
        form_id = form_id_by_pos.get(position)

        # authQuality_s : rôle de l'auteur (aut, crp, dir, edt, …)
        quality = qualities[position] if position < len(qualities) else None
        roles, is_corresponding_from_role = map_role("hal", quality)
        is_corresponding = is_corresponding_from_role

        if not name:
            continue

        identifiers = ids_by_position[position]

        # Noms des structures affiliées à cet auteur (par form_id), utilisés comme adresses brutes.
        addr_parts: list[str] = []
        if form_id and form_id in form_struct_map:
            addr_parts = [
                struct_name_by_hal_id[hid]
                for hid in sorted(form_struct_map[form_id])
                if hid in struct_name_by_hal_id and struct_name_by_hal_id[hid].strip()
            ]

        records.append(
            AuthorRecord(
                position=position,
                raw_name=name,
                is_corresponding=is_corresponding,
                roles=roles or None,
                person_identifiers=identifiers,
                addresses=[AddressRecord(text=part) for part in addr_parts],
            )
        )

    return records


def process_authorships(
    conn: Connection,
    authorship_queries: AuthorshipsBatchQueries,
    doc: dict,
    source_publication_id: int,
) -> None:
    """Parse les auteurs HAL puis écrit les authorships en batch."""
    records = build_hal_author_records(doc)
    write_source_authorships(conn, authorship_queries, "hal", source_publication_id, records)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: SourcePublicationQueries,
    logger: logging.Logger,
    staging_row: StagingRow,
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    pub_repo: PublicationRepository,
    staging_queries: StagingQueries,
    authorship_queries: AuthorshipsBatchQueries,
) -> bool | None:
    """Traite un work du staging HAL."""
    staging_id = staging_row.id
    hal_id = staging_row.source_id
    doc = staging_row.raw_data

    t = StepTimer()
    title = get_title(doc)
    pub_year = doc.get("producedDateY_i")
    if not has_minimal_publication_metadata(title, pub_year):
        logger.warning(f"Impossible d'insérer {hal_id} — titre ou année manquant")
        staging_queries.mark_done(conn, staging_id)
        return False

    if not doc.get("authFullNameFormIDPersonIDIDHal_fs"):
        logger.error(
            f"{hal_id} : champ authFullNameFormIDPersonIDIDHal_fs absent du payload "
            "— doc HAL inexploitable, marqué traité"
        )
        staging_queries.mark_done(conn, staging_id)
        return False

    publisher_name = as_str(doc.get("journalPublisher_s")) or as_str(doc.get("publisher_s"))
    publisher_id = (
        upsert_publisher(publisher_name, publisher_repo=publisher_repo) if publisher_name else None
    )
    journal_id = upsert_journal(doc, publisher_id, journal_repo=journal_repo)
    t.mark("publisher+journal")

    pub_meta = extract_pub_metadata(doc, journal_id)

    source_publication_id = insert_hal_document(
        conn,
        queries,
        doc,
        staging_id,
        hal_id,
        pub_meta,
    )
    t.mark("hal_doc")

    process_authorships(conn, authorship_queries, doc, source_publication_id)
    t.mark("authors")

    staging_queries.mark_done(conn, staging_id)
    t.log_if_slow(hal_id, logger)

    return True


class HalNormalizer(SourceNormalizer):
    SOURCE = "hal"
    DEFAULT_BATCH_SIZE = 500

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging_queries: StagingQueries,
        queries: SourcePublicationQueries,
        journal_repo_factory: Callable[[Connection], JournalRepository],
        publisher_repo_factory: Callable[[Connection], PublisherRepository],
        pub_repo_factory: Callable[[Connection], PublicationRepository],
        authorship_queries: AuthorshipsBatchQueries,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._journal_repo_factory = journal_repo_factory
        self._journal_repo: JournalRepository | None = None
        self._publisher_repo_factory = publisher_repo_factory
        self._publisher_repo: PublisherRepository | None = None
        self._pub_repo_factory = pub_repo_factory
        self._pub_repo: PublicationRepository | None = None
        self._authorship_queries = authorship_queries

    def preload_caches(self, conn: Connection) -> None:
        self._journal_repo = self._journal_repo_factory(conn)
        self._publisher_repo = self._publisher_repo_factory(conn)
        self._pub_repo = self._pub_repo_factory(conn)

    def process_work(self, conn: Connection, row: StagingRow) -> bool | None:
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
            staging_queries=self._staging,
            authorship_queries=self._authorship_queries,
        )
