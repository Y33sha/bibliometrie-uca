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
(source_structures.id) extraits de authIdHasStructure_fs.

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from psycopg.types.json import Jsonb as Json

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
from domain.doc_types import map_doc_type
from domain.normalize import normalize_text
from domain.ports.journal_repository import JournalRepository
from domain.ports.publication_repository import PublicationRepository
from domain.ports.publisher_repository import PublisherRepository
from domain.publication import clean_doi, normalize_nnt
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


def upsert_publisher(
    cur: Any, publisher_name: str, *, publisher_repo: PublisherRepository
) -> int | None:
    """Trouve ou crée un éditeur. Délègue au service journals."""
    return find_or_create_publisher(cur, publisher_name, repo=publisher_repo)


def upsert_journal(
    cur: Any, doc: dict, publisher_id: int | None, *, journal_repo: JournalRepository
) -> int | None:
    """Extrait et trouve/crée la revue depuis les champs HAL."""
    title = as_str(doc.get("journalTitle_s"))
    if not title:
        return None
    return find_or_create_journal(
        cur,
        title,
        issn=as_str(doc.get("journalIssn_s")),
        eissn=as_str(doc.get("journalEissn_s")),
        publisher_id=publisher_id,
        repo=journal_repo,
    )


# =============================================================
# PUBLICATIONS (via services/publications.py)
# =============================================================


def _map_hal_doc_type(doc: dict) -> str:
    """Mappe le type HAL vers le type canonique.
    Teste d'abord la combinaison TYPE_SOUS-TYPE, puis le type seul.
    """
    raw_type = doc.get("docType_s", "OTHER")
    raw_sub = doc.get("docSubType_s") or ""
    combo = f"{raw_type}_{raw_sub}" if raw_sub else ""
    if combo:
        result = map_doc_type(combo, "hal")
        if result != "other":
            return result
    return map_doc_type(raw_type, "hal")


def extract_pub_metadata(doc: dict, journal_id: int | None) -> dict:
    """Extrait les metadonnees de publication d'un document HAL.

    Retourne un dict utilisable par find_or_create_publication.
    """
    doi = clean_doi(as_str(doc.get("doiId_s")))
    title = get_title(doc)
    pub_year = doc.get("producedDateY_i")

    doc_type = _map_hal_doc_type(doc)

    language_list = doc.get("language_s")
    language = language_list[0] if isinstance(language_list, list) and language_list else None

    oa_status = "green" if doc.get("openAccess_bool") else "closed"

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
    cur: Any,
    doc: dict,
    journal_id: int | None,
    *,
    pub_repo: PublicationRepository,
) -> int | None:
    """Cherche une publication existante sans en créer. Retourne l'id ou None."""
    meta = extract_pub_metadata(doc, journal_id)
    if not meta["pub_year"] or not meta["title"]:
        return None
    pub_id, _ = find_or_create_publication(cur, **meta, allow_create=False, repo=pub_repo)
    return pub_id


# =============================================================
# SOURCE DOCUMENTS (HAL)
# =============================================================


def insert_hal_document(
    cur: Any,
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
    external_ids = Json({"nnt": nnt}) if nnt else None

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
    topics = (
        Json({"hal_domains": domain_raw}) if isinstance(domain_raw, list) and domain_raw else None
    )

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
    biblio_json = Json(biblio) if biblio else None

    # URLs
    uri = as_str(doc.get("uri_s"))
    urls = [uri] if uri else None

    return queries.upsert_hal_source_publication(
        cur,
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
            val = (idno.text or "").strip()
            if not val:
                continue
            if typ == "ORCID":
                ids["orcid"] = (
                    val.replace("https://orcid.org/", "")
                    .replace("http://orcid.org/", "")
                    .strip("/ ")
                )
            elif typ == "IDREF":
                ids["idref"] = val.rsplit("/", 1)[-1].strip()
            elif typ == "IDHAL":
                ids["idhal"] = val
        out.append(ids)
    return out


def _hal_source_id(
    hal_person_id: int | None, hal_form_id: int | None, old_id: int | None = None
) -> str:
    """
    Calcule le source_id HAL :
    - hal_person_id seul si non null (un seul source_author par personne HAL)
    - 0_hal_form_id si hal_person_id est null (auteur sans compte HAL)
    - nokey-{old_id} si les deux sont null
    """
    if hal_person_id and hal_person_id > 0:
        return str(hal_person_id)
    if hal_form_id:
        return f"0_{hal_form_id}"
    return f"nokey-{old_id}" if old_id else "_"


_hal_author_cache: dict[str, int] = {}


def upsert_hal_author(
    cur: Any,
    queries: HalNormalizeQueries,
    full_name: str,
    hal_person_id: int | None,
    idhal: str | None,
    hal_form_id: int | None = None,
    orcid: str | None = None,
    idref: str | None = None,
) -> int | None:
    """Crée un `source_persons` HAL uniquement quand un `hal_person_id` est
    fourni (= compte HAL identifié, cas légitime conservé par le chantier
    source_persons). Sans `hal_person_id`, retourne None : la
    `source_authorships` sera insérée avec `source_person_id=NULL`,
    et les éventuels orcid/idref/idhal vivront sur `identifiers`.

    Cache mémoire par `hal_person_id` pour éviter les SELECTs redondants.
    """
    if not full_name:
        return None
    if not (hal_person_id and hal_person_id > 0):
        return None

    src_id = _hal_source_id(hal_person_id, hal_form_id)
    if src_id in _hal_author_cache:
        return _hal_author_cache[src_id]

    parts = full_name.strip().split()
    if len(parts) >= 2:
        first_name = " ".join(parts[:-1])
        last_name = parts[-1]
    else:
        first_name = None
        last_name = full_name

    source_ids: dict[str, Any] = {"hal_person_id": hal_person_id}
    if idhal:
        source_ids["idhal"] = idhal
    if hal_form_id:
        source_ids["hal_form_id"] = hal_form_id

    result = queries.upsert_hal_source_person(
        cur,
        source_id=src_id,
        full_name=full_name,
        last_name=last_name,
        first_name=first_name,
        orcid=orcid,
        idref=idref,
        source_ids_json=Json(source_ids),
    )
    _hal_author_cache[src_id] = result
    return result


# =============================================================
# HAL AUTHORSHIPS
# =============================================================


def parse_author_structures(
    doc: dict,
    cur: Any = None,
    queries: HalNormalizeQueries | None = None,
    struct_cache: dict | None = None,
    struct_name_cache: dict | None = None,
) -> dict[int, set[int]]:
    """
    Parse authIdHasStructure_fs pour extraire le mapping
    form_id → {hal_struct_id bruts (entiers HAL, résolus en source_struct_ids ensuite)}.

    Format : "formId-personId_FacetSep_Nom_JoinSep_structId_FacetSep_StructNom"

    Crée les source_structures HAL à la volée si elles n'existent pas encore.
    """
    entries = doc.get("authIdHasStructure_fs") or []
    form_structs: dict[int, set[int]] = {}

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
        try:
            struct_id = int(right_parts[0])
        except ValueError:
            continue
        struct_name = right_parts[1].strip() if len(right_parts) > 1 else ""

        form_structs.setdefault(form_id, set()).add(struct_id)

        # Créer la source_structure si pas encore en cache
        if (
            cur
            and queries is not None
            and struct_cache is not None
            and str(struct_id) not in struct_cache
        ):
            ss_id = queries.upsert_hal_source_structure(
                cur,
                source_id=str(struct_id),
                name=(struct_name[:500] if struct_name else str(struct_id)),
            )
            struct_cache[str(struct_id)] = ss_id
            if struct_name_cache is not None:
                struct_name_cache[ss_id] = struct_name

    return form_structs


def process_authors(
    cur: Any,
    queries: HalNormalizeQueries,
    doc: dict,
    source_publication_id: int,
    *,
    address_linker: AddressLinker,
    struct_cache: dict | None = None,
    struct_name_cache: dict | None = None,
) -> None:
    """
    Traite les auteurs d'un document HAL :
    - Parse les champs alignés pour extraire hal_person_id, idhal et form_id
    - Parse authIdHasStructure_fs pour les affiliations (clé = form_id)
    - Crée/retrouve chaque auteur dans source_persons (source='hal')
    - Crée les source_authorships (source='hal') avec source_struct_ids (source_structures.id)
    """
    # Pré-nettoyage : un re-traitement peut changer les auteurs/positions,
    # on repart d'une table blanche pour cette publi.
    queries.clear_source_authorships_for_publication(cur, source_publication_id)

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

    # authIdHasStructure_fs → {form_id: set of hal_struct_id bruts}
    form_struct_map = parse_author_structures(
        doc,
        cur=cur,
        queries=queries,
        struct_cache=struct_cache,
        struct_name_cache=struct_name_cache,
    )

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

        # Avec hal_person_id : crée le source_persons (cas légitime conservé)
        # Sans hal_person_id : source_person_id reste NULL, identifiants
        # (orcid/idref/idhal) sur la source_authorships via identifiers.
        source_person_id = upsert_hal_author(
            cur, queries, name, hal_person_id, idhal, form_id, orcid=orcid, idref=idref
        )

        if not name:
            continue

        # Identifiants normalisés cross-source pour cette authorship
        ids: dict[str, Any] = {}
        if orcid:
            ids["orcid"] = orcid
        if idref:
            ids["idref"] = idref
        if idhal:
            ids["idhal"] = idhal
        if hal_person_id and hal_person_id > 0:
            ids["hal_person_id"] = hal_person_id
        identifiers = Json(ids) if ids else None

        # Structures affiliées à cet auteur sur ce document (par form_id)
        # Résoudre les hal_struct_id bruts → source_structures.id
        source_struct_ids = None
        if form_id and form_id in form_struct_map:
            raw_hal_ids = sorted(form_struct_map[form_id])
            if struct_cache is not None:
                resolved = [
                    struct_cache[str(hid)] for hid in raw_hal_ids if str(hid) in struct_cache
                ]
            else:
                resolved = queries.fetch_hal_source_structure_ids(
                    cur, [str(hid) for hid in raw_hal_ids]
                )
            if resolved:
                source_struct_ids = sorted(resolved)

        # Noms des structures pour les adresses
        addr_parts = []
        if source_struct_ids and struct_name_cache:
            addr_parts = [
                struct_name_cache[sid]
                for sid in source_struct_ids
                if sid in struct_name_cache and struct_name_cache[sid].strip()
            ]

        sa_id = queries.upsert_hal_source_authorship(
            cur,
            source_publication_id=source_publication_id,
            source_person_id=source_person_id,
            author_position=position,
            source_struct_ids=source_struct_ids,
            raw_author_name=name,
            is_corresponding=is_corresponding,
            roles=roles or None,
            identifiers=identifiers,
        )

        if addr_parts:
            address_linker.link(cur, sa_id, addr_parts)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    cur: Any,
    queries: HalNormalizeQueries,
    logger: Any,
    staging_row: tuple,
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    pub_repo: PublicationRepository,
    zenodo_resolver: ZenodoResolver,
    staging_queries: StagingQueries,
    address_linker: AddressLinker,
    struct_cache: dict | None = None,
    struct_name_cache: dict | None = None,
) -> bool:
    """Traite un work du staging HAL."""
    from application.pipeline.timings import StepTimer

    staging_id, hal_id, doi, raw_data, hal_collections_staging = staging_row
    doc = raw_data

    try:
        t = StepTimer()
        title = get_title(doc)
        pub_year = doc.get("producedDateY_i")
        if not title or not pub_year:
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
                if queries.staging_has_hal_doi(cur, version_doi):
                    logger.info(
                        f"  {hal_id} concept DOI Zenodo {raw_doi} -> "
                        f"version {version_doi} deja en staging, skip"
                    )
                    staging_queries.mark_done(cur, staging_id)
                    return False

        publisher_name = as_str(doc.get("journalPublisher_s")) or as_str(doc.get("publisher_s"))
        publisher_id = (
            upsert_publisher(cur, publisher_name, publisher_repo=publisher_repo)
            if publisher_name
            else None
        )
        journal_id = upsert_journal(cur, doc, publisher_id, journal_repo=journal_repo)
        t.mark("publisher+journal")

        pub_meta = extract_pub_metadata(doc, journal_id)

        publication_id = None
        old_pub_id = queries.get_hal_publication_id(cur, hal_id)
        if old_pub_id:
            publication_id = find_publication(cur, doc, journal_id, pub_repo=pub_repo)
            if publication_id and publication_id != old_pub_id:
                from application.publications import merge_publications

                logger.info(f"  {hal_id} : fusion pub {old_pub_id} → {publication_id} (DOI/NNT)")
                merge_publications(cur, publication_id, old_pub_id, repo=pub_repo)
            elif not publication_id:
                publication_id = old_pub_id
        else:
            publication_id = find_publication(cur, doc, journal_id, pub_repo=pub_repo)
        t.mark("publication")

        if publication_id:
            publication_id = try_merge_by_doi(
                cur, publication_id, clean_doi(as_str(doc.get("doiId_s"))), repo=pub_repo
            )

        source_publication_id = insert_hal_document(
            cur,
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
            cur,
            queries,
            doc,
            source_publication_id,
            address_linker=address_linker,
            struct_cache=struct_cache,
            struct_name_cache=struct_name_cache,
        )
        t.mark("authors")

        if publication_id:
            refresh_from_sources(cur, publication_id, repo=pub_repo)
        t.mark("refresh")

        staging_queries.mark_done(cur, staging_id)
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
        conn: Any,
        logger: Any,
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
        self._struct_cache: dict[str, int] = {}
        self._struct_name_cache: dict[int, str] = {}

    def preload_caches(self, cur: Any) -> None:
        self._journal_repo = self._journal_repo_factory(cur)
        self._publisher_repo = self._publisher_repo_factory(cur)
        self._pub_repo = self._pub_repo_factory(cur)
        rows = self._queries.fetch_hal_source_structures_for_cache(cur)
        self._struct_cache = {src: pid for src, pid, _ in rows}
        self._struct_name_cache = {pid: name for _, pid, name in rows}
        self.logger.info(f"Cache source_structures : {len(self._struct_cache)} entrées")

    def process_work(self, cur: Any, row: Any) -> bool | None:
        assert self._journal_repo is not None, "preload_caches doit être appelé avant"
        assert self._publisher_repo is not None, "preload_caches doit être appelé avant"
        assert self._pub_repo is not None, "preload_caches doit être appelé avant"
        return process_work(
            cur,
            self._queries,
            self.logger,
            row,
            journal_repo=self._journal_repo,
            publisher_repo=self._publisher_repo,
            pub_repo=self._pub_repo,
            zenodo_resolver=self._zenodo_resolver,
            staging_queries=self._staging,
            address_linker=self._address_linker,
            struct_cache=self._struct_cache,
            struct_name_cache=self._struct_name_cache,
        )

    def post_process(self, cur: Any) -> None:
        self._queries.delete_hal_duplicate_authorship_addresses(cur)
        deleted_dups = self._queries.delete_hal_duplicate_authorships(cur)
        if deleted_dups:
            self.logger.info(f"Doublons de position supprimés : {deleted_dups}")

        orphans = self._queries.delete_hal_orphan_source_persons(cur)
        if orphans:
            self.logger.info(f"Source_authors orphelins supprimés : {orphans}")

    def cleanup(self) -> None:
        self._struct_cache.clear()
        self._struct_name_cache.clear()
        self._address_linker.clear_cache()

    def on_error(self) -> None:
        # Les caches peuvent contenir des IDs (adresses, structures)
        # insérés dans la transaction qui vient d'être rollbackée — les
        # invalider évite les FK violations sur les works suivants.
        self._struct_cache.clear()
        self._struct_name_cache.clear()
        self._address_linker.clear_cache()
        _hal_author_cache.clear()
