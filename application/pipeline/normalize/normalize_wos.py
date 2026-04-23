"""
Normalisation des données WoS : staging → tables normalisées.

Usage:
    python normalize_wos.py              # traiter tous les works non traités
    python normalize_wos.py --limit 100  # traiter N works (pour test)
    python normalize_wos.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    source_publications                        (lien staging ↔ publication, source='wos')
    source_persons                          (auteurs unifiés, source='wos')
    source_authorships                      (lien document × auteur, source='wos')

Gère deux formats de raw_data :
    - TSV (fichiers téléchargés) : clés 2 lettres (TI, AU, AF, SO, PU, etc.)
    - API (WoS Expanded API) : structure imbriquée (static_data, dynamic_data)

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

from collections.abc import Callable
from typing import Any

from psycopg.types.json import Jsonb as Json

from application.journals import find_or_create_journal
from application.pipeline.normalize.base import SourceNormalizer
from application.ports.normalize_wos import WosNormalizeQueries
from application.ports.staging import StagingQueries
from application.publications import find_or_create as find_or_create_publication
from application.publications import refresh_from_sources, try_merge_by_doi
from application.publishers import find_or_create_publisher
from domain.authorship_roles import map_role
from domain.normalize import normalize_text
from domain.ports.journal_repository import JournalRepository
from domain.ports.publication_repository import PublicationRepository
from domain.ports.publisher_repository import PublisherRepository
from domain.publication import clean_doi

# =============================================================
# MAPPINGS
# =============================================================

# WoS document type → notre enum doc_type


# =============================================================
# UTILITAIRES
# =============================================================


def map_doc_type(raw_type: str | None) -> str:
    """Mappe un type de document WoS vers notre enum.

    Délègue à utils.doc_types.map_doc_type qui gère les types
    composites (séparés par ';') et le mapping WoS.
    """
    from domain.doc_types import map_doc_type as _map

    return _map(raw_type, "wos")


def map_oa_status(raw_oa: str | None) -> str:
    """Extrait le statut OA depuis le champ WoS (potentiellement multi-valeurs)."""
    if not raw_oa:
        return "unknown"
    raw_lower = raw_oa.lower()
    # Priorité : diamond > gold > hybrid > bronze > green
    if "diamond" in raw_lower:
        return "diamond"
    if "gold" in raw_lower:
        return "gold"
    if "hybrid" in raw_lower:
        return "hybrid"
    if "bronze" in raw_lower:
        return "bronze"
    if "green" in raw_lower:
        return "green"
    return "unknown"


def _safe_list(obj: Any) -> list:
    """WoS API retourne parfois un dict au lieu d'une liste."""
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    return [obj]


def _get_api_title(static: dict, title_type: str) -> str | None:
    """Extrait un titre depuis la structure API."""
    titles = static.get("summary", {}).get("titles", {})
    title_list = _safe_list(titles.get("title"))
    for t in title_list:
        if isinstance(t, dict) and t.get("type") == title_type:
            return t.get("content")
    return None


def _parse_api_authors(static: dict, dynamic: dict) -> list[dict]:
    """Extrait les auteurs depuis le format API."""
    names_data = static.get("summary", {}).get("names", {})
    name_list = _safe_list(names_data.get("name"))

    # Adresses pour le matching
    addresses_data = static.get("fullrecord_metadata", {}).get("addresses", {})
    addr_list = _safe_list(addresses_data.get("address_name"))
    addr_map = {}  # addr_no -> full_address
    addr_orgs_map = {}  # addr_no -> [{name, ror_id, country}]
    for addr_entry in addr_list:
        spec = addr_entry.get("address_spec", {})
        addr_no = spec.get("addr_no")
        if addr_no is not None:
            addr_map[str(addr_no)] = spec.get("full_address", "")
            # Organizations structurées
            orgs_data = spec.get("organizations", {})
            org_list = _safe_list(orgs_data.get("organization"))
            orgs = []
            for o in org_list:
                if isinstance(o, dict) and o.get("content"):
                    orgs.append(
                        {
                            "name": o["content"],
                            "ror_id": o.get("ror_id"),
                            "pref": o.get("pref"),
                        }
                    )
            if orgs:
                addr_orgs_map[str(addr_no)] = orgs

    authors = []
    for name_obj in name_list:
        if not isinstance(name_obj, dict):
            continue
        wos_role = name_obj.get("role")
        if not wos_role:
            continue

        full_name = name_obj.get("display_name") or name_obj.get("full_name") or ""
        last_name = name_obj.get("last_name")
        first_name = name_obj.get("first_name")
        seq_no = name_obj.get("seq_no")
        position = int(seq_no) - 1 if seq_no else 0

        daisng_id = name_obj.get("daisng_id")
        if daisng_id:
            daisng_id = str(daisng_id)
        researcher_id = name_obj.get("r_id")

        # ORCID depuis data-item-ids
        orcid = None
        di_ids = name_obj.get("data-item-ids", {})
        di_list = _safe_list(di_ids.get("data-item-id"))
        for di in di_list:
            if isinstance(di, dict) and di.get("id-type") == "PreferredORCID":
                orcid = di.get("content")
                break

        is_corresponding = name_obj.get("reprint") == "Y"

        # Affiliations via addr_no
        addr_nos = name_obj.get("addr_no")
        raw_affiliation = None
        individual_addresses = []
        author_orgs = []
        if addr_nos:
            addr_no_list = str(addr_nos).split()
            affils = [addr_map[a] for a in addr_no_list if a in addr_map]
            individual_addresses = [a.strip() for a in affils if a.strip()]
            if affils:
                raw_affiliation = " | ".join(affils)
            # Collecter les organizations de cet auteur
            seen_org_names = set()
            for a_no in addr_no_list:
                for org in addr_orgs_map.get(a_no, []):
                    if org["name"] not in seen_org_names:
                        author_orgs.append(org)
                        seen_org_names.add(org["name"])

        roles, is_corresponding_from_role = map_role("wos", wos_role)
        is_corresponding = is_corresponding or is_corresponding_from_role

        authors.append(
            {
                "position": position,
                "full_name": full_name.strip(),
                "last_name": last_name,
                "first_name": first_name,
                "orcid": orcid,
                "researcher_id": researcher_id,
                "daisng_id": daisng_id,
                "is_corresponding": is_corresponding,
                "raw_affiliation": raw_affiliation,
                "addresses": individual_addresses,
                "organizations": author_orgs,
                "roles": roles,
            }
        )

    return authors


def _get_api_doi(dynamic: dict) -> str | None:
    """Extrait le DOI depuis la structure API."""
    try:
        identifiers = (
            dynamic.get("cluster_related", {}).get("identifiers", {}).get("identifier", [])
        )
        for ident in _safe_list(identifiers):
            if isinstance(ident, dict) and ident.get("type") == "doi":
                return clean_doi(str(ident.get("value", "")))
    except (KeyError, TypeError):
        pass
    return None


def _get_api_issn(dynamic: dict, issn_type: str = "issn") -> str | None:
    """Extrait l'ISSN ou eISSN depuis la structure API."""
    try:
        identifiers = (
            dynamic.get("cluster_related", {}).get("identifiers", {}).get("identifier", [])
        )
        for ident in _safe_list(identifiers):
            if isinstance(ident, dict) and ident.get("type") == issn_type:
                return str(ident.get("value", "")).strip() or None
    except (KeyError, TypeError):
        pass
    return None


def extract_from_api(raw: dict, staging_doi: str | None) -> dict:
    """Extrait un record structuré depuis le format API."""
    static = raw.get("static_data", {})
    dynamic = raw.get("dynamic_data", {})
    summary = static.get("summary", {})
    pub_info = summary.get("pub_info", {})

    doi = _get_api_doi(dynamic) or clean_doi(staging_doi)
    title = _get_api_title(static, "item") or "(sans titre)"

    pub_year = None
    py = pub_info.get("pubyear")
    if py:
        try:
            pub_year = int(py)
        except ValueError:
            pass

    # Doc type
    doctypes = summary.get("doctypes", {})
    doctype_list = _safe_list(doctypes.get("doctype") if isinstance(doctypes, dict) else doctypes)
    raw_doc_type = None
    if doctype_list:
        if isinstance(doctype_list[0], dict):
            raw_doc_type = doctype_list[0].get("content", "")
        else:
            raw_doc_type = str(doctype_list[0])

    # Publisher
    publishers = summary.get("publishers", {})
    pub_data = publishers.get("publisher", {})
    pub_names = pub_data.get("names", {})
    pub_name_obj = pub_names.get("name", {})
    if isinstance(pub_name_obj, list):
        pub_name_obj = pub_name_obj[0] if pub_name_obj else {}
    publisher_name = pub_name_obj.get("unified_name") or pub_name_obj.get("full_name")

    # Journal
    journal_title = _get_api_title(static, "source")

    # OA — API format n'a pas toujours un champ OA simple
    oa_gold = pub_info.get("journal_oas_gold")
    oa_status = "unknown"
    if oa_gold == "Y":
        oa_status = "gold"

    # Language
    lang_data = static.get("fullrecord_metadata", {}).get("languages", {})
    lang_list = _safe_list(lang_data.get("language"))
    language = None
    if lang_list and isinstance(lang_list[0], dict):
        language = lang_list[0].get("content")
    elif lang_list:
        language = str(lang_list[0])

    # Biblio
    page = pub_info.get("page", {})
    if isinstance(page, str):
        page = {}
    biblio = {}
    vol = pub_info.get("vol")
    if vol:
        biblio["volume"] = str(vol)
    issue_val = pub_info.get("issue")
    if issue_val:
        biblio["issue"] = str(issue_val)
    if isinstance(page, dict):
        if page.get("begin"):
            biblio["first_page"] = str(page["begin"])
        if page.get("end"):
            biblio["last_page"] = str(page["end"])

    # Abstract
    frm = static.get("fullrecord_metadata", {})
    abstract = None
    abstracts = frm.get("abstracts", {})
    if abstracts:
        ab = abstracts.get("abstract", {})
        p = ab.get("abstract_text", {}).get("p", "")
        if isinstance(p, list):
            p = " ".join(str(x) for x in p)
        if p:
            abstract = str(p)

    # Keywords
    kw_data = frm.get("keywords", {})
    kw_list = kw_data.get("keyword", []) if isinstance(kw_data, dict) else []
    if isinstance(kw_list, str):
        kw_list = [kw_list]
    keywords = [str(k) for k in kw_list if k] or None

    # Topics : categories
    cat = frm.get("category_info", {})
    topics = {}
    subjects = cat.get("subjects", {}).get("subject", [])
    if isinstance(subjects, dict):
        subjects = [subjects]
    subj_names = [
        s.get("content") or s for s in subjects if isinstance(s, dict) and s.get("content")
    ]
    if subj_names:
        topics["subjects"] = subj_names
    headings = cat.get("headings", {}).get("heading", [])
    if isinstance(headings, str):
        headings = [headings]
    if headings:
        topics["headings"] = headings

    # Citations
    tc_list = dynamic.get("citation_related", {}).get("tc_list", {}).get("silo_tc", [])
    if isinstance(tc_list, dict):
        tc_list = [tc_list]
    cited_by_count = None
    for tc in tc_list:
        if isinstance(tc, dict) and tc.get("coll_id") == "WOK":
            try:
                cited_by_count = int(tc.get("local_count", 0))
            except (ValueError, TypeError):
                pass

    return {
        "ut": raw.get("UID", ""),
        "doi": doi,
        "title": title,
        "pub_year": pub_year,
        "doc_type": raw_doc_type or "other",
        "language": language,
        "oa_status": oa_status,
        "journal_title": journal_title,
        "issn": _get_api_issn(dynamic, "issn"),
        "eissn": _get_api_issn(dynamic, "eissn"),
        "publisher_name": publisher_name,
        "authors": _parse_api_authors(static, dynamic),
        "abstract": abstract,
        "cited_by_count": cited_by_count,
        "biblio": biblio or None,
        "keywords": keywords,
        "topics": topics or None,
        "urls": None,
        "external_ids": None,
    }


# =============================================================
# PUBLISHERS & JOURNALS (via services/journals.py)
# =============================================================


def upsert_publisher(
    cur: Any, publisher_name: str | None, *, publisher_repo: PublisherRepository
) -> int | None:
    """Trouve ou crée un éditeur. Délègue au service journals."""
    return find_or_create_publisher(cur, publisher_name, repo=publisher_repo)


def upsert_journal(
    cur: Any, rec: dict, publisher_id: int | None, *, journal_repo: JournalRepository
) -> int | None:
    """Trouve ou crée une revue depuis les données WoS."""
    title = rec.get("journal_title")
    if not title:
        return None
    return find_or_create_journal(
        cur,
        title,
        issn=rec.get("issn"),
        eissn=rec.get("eissn"),
        publisher_id=publisher_id,
        repo=journal_repo,
    )


# =============================================================
# PUBLICATIONS (via services/publications.py)
# =============================================================


def extract_pub_metadata(rec: dict, journal_id: int | None) -> dict:
    """Extrait les métadonnées de publication d'un record WoS.

    Retourne un dict utilisable par find_or_create_publication.
    """
    title = rec["title"]
    container_title = rec.get("journal_title") if not journal_id else None

    return dict(
        title=title,
        title_normalized=normalize_text(title),
        pub_year=rec["pub_year"],
        doc_type=rec["doc_type"],
        doi=rec["doi"],
        oa_status=rec["oa_status"],
        journal_id=journal_id,
        container_title=container_title,
        language=rec.get("language"),
    )


def find_publication(
    cur: Any,
    rec: dict,
    journal_id: int | None,
    *,
    pub_repo: PublicationRepository,
) -> int | None:
    """Cherche une publication existante sans en créer. Retourne l'id ou None."""
    meta = extract_pub_metadata(rec, journal_id)
    if not meta["pub_year"] or not meta["title"] or meta["title"] == "(sans titre)":
        return None
    # Mapper le doc_type pour find_or_create (resolve_doi_conflict a besoin du type canonique)
    meta["doc_type"] = map_doc_type(meta["doc_type"])
    pub_id, _ = find_or_create_publication(cur, **meta, allow_create=False, repo=pub_repo)
    return pub_id


# =============================================================
# SOURCE DOCUMENTS (WOS)
# =============================================================


def insert_wos_document(
    cur: Any,
    queries: WosNormalizeQueries,
    rec: dict,
    staging_id: int,
    publication_id: int | None,
    pub_meta: dict | None = None,
) -> int:
    """Crée/retrouve l'entrée source_publications pour WoS. Retourne source_publications.id."""
    journal_id = pub_meta.get("journal_id") if pub_meta else None
    oa_status = pub_meta.get("oa_status") if pub_meta else None
    language = pub_meta.get("language") if pub_meta else None
    container_title = pub_meta.get("container_title") if pub_meta else None

    abstract = rec.get("abstract")
    cited_by_count = rec.get("cited_by_count")
    biblio = Json(rec["biblio"]) if rec.get("biblio") else None
    keywords = rec.get("keywords")
    topics = Json(rec["topics"]) if rec.get("topics") else None
    urls = rec.get("urls")
    external_ids = Json(rec["external_ids"]) if rec.get("external_ids") else None

    return queries.upsert_wos_source_publication(
        cur,
        ut=rec["ut"],
        doi=rec["doi"],
        title=rec["title"],
        pub_year=rec["pub_year"],
        doc_type=rec["doc_type"],
        publication_id=publication_id,
        staging_id=staging_id,
        journal_id=journal_id,
        oa_status=oa_status,
        language=language,
        container_title=container_title,
        abstract=abstract,
        cited_by_count=cited_by_count,
        biblio=biblio,
        keywords=keywords,
        topics=topics,
        urls=urls,
        external_ids=external_ids,
    )


# =============================================================
# WOS AUTHORS (source_persons, source='wos')
# =============================================================

_wos_author_cache: dict[str, int] = {}


def upsert_wos_author(
    cur: Any, queries: WosNormalizeQueries, logger: Any, author: dict
) -> int | None:
    """Insère/retrouve un auteur WoS dans source_persons (source='wos').

    Utilise le daisng_id comme clé unique (format API).
    Cache en mémoire pour éviter les requêtes répétées.
    Retourne source_persons.id.
    """
    full_name = author.get("full_name")
    if not full_name:
        return None

    daisng_id = author.get("daisng_id")
    if not daisng_id:
        logger.warning(f"Auteur WoS sans daisng_id : {full_name}")
        return None

    if daisng_id in _wos_author_cache:
        return _wos_author_cache[daisng_id]

    last_name = author.get("last_name")
    first_name = author.get("first_name")
    orcid = author.get("orcid")
    researcher_id = author.get("researcher_id")

    source_ids = {}
    if researcher_id:
        source_ids["researcher_id"] = researcher_id
    source_ids_json = Json(source_ids) if source_ids else None

    result = queries.upsert_wos_source_person(
        cur,
        daisng_id=daisng_id,
        full_name=full_name,
        last_name=last_name,
        first_name=first_name,
        orcid=orcid,
        source_ids_json=source_ids_json,
    )
    _wos_author_cache[daisng_id] = result
    return result


# =============================================================
# WOS AUTHORSHIPS
# =============================================================


def _resolve_addresses_batch(
    cur: Any, queries: WosNormalizeQueries, raw_texts: set
) -> dict[str, int]:
    """Résout un ensemble d'adresses en batch. Retourne {raw_text: id}."""
    if not raw_texts:
        return {}
    values = [(t, normalize_text(t)) for t in raw_texts]
    queries.upsert_addresses_batch(cur, values)
    return queries.fetch_address_ids_by_raw_text(cur, list(raw_texts))


_wos_institution_cache: dict[str, int] = {}


def upsert_wos_institution(cur: Any, queries: WosNormalizeQueries, org: dict) -> int | None:
    """Insère/retrouve une organisation WoS dans source_structures."""
    name = org.get("name")
    if not name:
        return None

    if name in _wos_institution_cache:
        return _wos_institution_cache[name]

    ror_id = org.get("ror_id")
    result = queries.upsert_wos_source_structure(cur, name=name, ror_id=ror_id)
    _wos_institution_cache[name] = result
    return result


def process_authorships(
    cur: Any, queries: WosNormalizeQueries, rec: dict, source_publication_id: int
) -> None:
    """Traite les authorships d'un record WoS + crée les liens adresses et institutions."""
    # Résoudre toutes les organisations du document en un seul pass
    all_orgs = set()
    for author in rec.get("authors", []):
        for org in author.get("organizations", []):
            name = org.get("name")
            if name:
                all_orgs.add(name)
    for org_name in all_orgs:
        if org_name not in _wos_institution_cache:
            upsert_wos_institution(cur, queries, {"name": org_name})

    # Phase 1 : résoudre tous les auteurs (batch upsert source_persons)
    authors_resolved = []  # [(author_dict, source_person_id)]
    authors_to_insert = []  # [(author_dict, daisng_id, ...)]
    for author in rec.get("authors", []):
        daisng_id = author.get("daisng_id")
        if not daisng_id or not author.get("full_name"):
            continue
        if daisng_id in _wos_author_cache:
            authors_resolved.append((author, _wos_author_cache[daisng_id]))
        else:
            authors_to_insert.append(author)

    # Batch INSERT les auteurs nouveaux
    if authors_to_insert:
        # Dédupliquer par daisng_id dans le batch
        seen = set()
        deduped = []
        for a in authors_to_insert:
            if a["daisng_id"] not in seen:
                seen.add(a["daisng_id"])
                source_ids = {}
                if a.get("researcher_id"):
                    source_ids["researcher_id"] = a["researcher_id"]
                deduped.append(
                    (
                        "wos",
                        a["daisng_id"],
                        a["full_name"],
                        a.get("last_name"),
                        a.get("first_name"),
                        a.get("orcid"),
                        Json(source_ids) if source_ids else None,
                    )
                )

        for pid, src_id in queries.upsert_wos_source_persons_batch(cur, deduped):
            _wos_author_cache[src_id] = pid

        # Résoudre les auteurs insérés
        for a in authors_to_insert:
            aid = _wos_author_cache.get(a["daisng_id"])
            if aid:
                authors_resolved.append((a, aid))

    author_ids = authors_resolved
    if not author_ids:
        return

    # Phase 2 : batch INSERT source_authorships
    from domain.normalize import normalize_name_form

    values = {}  # clé = (source_publication_id, source_person_id), dédupliqué
    for author, source_person_id in author_ids:
        key = (source_publication_id, source_person_id)
        if key in values:
            continue  # même auteur déjà traité pour ce document

        institution_ids = []
        for org in author.get("organizations", []):
            name = org.get("name")
            if name and name in _wos_institution_cache:
                institution_ids.append(_wos_institution_cache[name])

        name_norm = normalize_name_form(author["full_name"])

        values[key] = (
            "wos",
            source_publication_id,
            source_person_id,
            author["position"],
            author["is_corresponding"],
            name_norm,
            institution_ids or None,
            author.get("roles"),
            author["full_name"],
        )

    queries.upsert_wos_source_authorships_batch(cur, list(values.values()))

    # Phase 3 : batch adresses (source_authorship_addresses)
    authors_with_addrs = [(a, said) for a, said in author_ids if a.get("addresses")]
    if authors_with_addrs:
        # Collecter toutes les adresses uniques du document
        all_addr_texts = set()
        for author, _ in authors_with_addrs:
            all_addr_texts.update(author["addresses"])

        # Résoudre en batch (INSERT + SELECT)
        addr_id_map = _resolve_addresses_batch(cur, queries, all_addr_texts)

        # Récupérer les sa_id
        sa_ids_needed = [said for _, said in authors_with_addrs]
        sa_id_map = queries.fetch_source_authorship_ids(
            cur, source_publication_id=source_publication_id, source_person_ids=sa_ids_needed
        )

        # Construire les liens
        addr_values = []
        for author, source_person_id in authors_with_addrs:
            sa_id = sa_id_map.get(source_person_id)
            if not sa_id:
                continue
            for addr_text in author["addresses"]:
                addr_id = addr_id_map.get(addr_text)
                if addr_id:
                    addr_values.append((sa_id, addr_id))

        queries.insert_source_authorship_addresses_batch(cur, addr_values)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_record(
    cur: Any,
    queries: WosNormalizeQueries,
    logger: Any,
    staging_row: tuple,
    *,
    journal_repo: JournalRepository,
    publisher_repo: PublisherRepository,
    pub_repo: PublicationRepository,
    staging_queries: StagingQueries,
) -> bool:
    """Traite un record du staging WoS. Retourne True si succès."""
    from application.pipeline.timings import StepTimer

    staging_id, ut, staging_doi, raw_data = staging_row

    try:
        t = StepTimer()
        rec = extract_from_api(raw_data, staging_doi)

        if not rec["ut"]:
            rec["ut"] = ut

        publisher_id = upsert_publisher(
            cur, rec.get("publisher_name"), publisher_repo=publisher_repo
        )
        journal_id = upsert_journal(cur, rec, publisher_id, journal_repo=journal_repo)
        t.mark("publisher+journal")

        pub_meta = extract_pub_metadata(rec, journal_id)

        publication_id = queries.get_wos_publication_id(cur, rec["ut"])

        if not publication_id:
            publication_id = find_publication(cur, rec, journal_id, pub_repo=pub_repo)
        t.mark("publication")

        if publication_id:
            publication_id = try_merge_by_doi(cur, publication_id, pub_meta["doi"], repo=pub_repo)

        source_publication_id = insert_wos_document(
            cur, queries, rec, staging_id, publication_id, pub_meta
        )
        t.mark("wos_doc")

        process_authorships(cur, queries, rec, source_publication_id)
        t.mark("authors")

        if publication_id:
            refresh_from_sources(cur, publication_id, repo=pub_repo)
        t.mark("refresh")

        staging_queries.mark_done(cur, staging_id)
        t.log_if_slow(ut, logger)
        return True

    except Exception as e:
        logger.error(f"Erreur sur {ut}: {e}")
        raise


class WosNormalizer(SourceNormalizer):
    SOURCE = "wos"
    DEFAULT_BATCH_SIZE = 500
    USE_DICT_CURSOR = False
    USE_SAVEPOINT = True
    FETCH_SUB_BATCH = 50
    FETCH_COLUMNS = "id, source_id AS ut, doi, raw_data"

    def __init__(
        self,
        conn: Any,
        logger: Any,
        staging_queries: StagingQueries,
        queries: WosNormalizeQueries,
        journal_repo_factory: Callable[[Any], JournalRepository],
        publisher_repo_factory: Callable[[Any], PublisherRepository],
        pub_repo_factory: Callable[[Any], PublicationRepository],
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        self._queries = queries
        self._journal_repo_factory = journal_repo_factory
        self._journal_repo: JournalRepository | None = None
        self._publisher_repo_factory = publisher_repo_factory
        self._publisher_repo: PublisherRepository | None = None
        self._pub_repo_factory = pub_repo_factory
        self._pub_repo: PublicationRepository | None = None

    def preload_caches(self, cur: Any) -> None:
        self._journal_repo = self._journal_repo_factory(cur)
        self._publisher_repo = self._publisher_repo_factory(cur)
        self._pub_repo = self._pub_repo_factory(cur)
        for src_id, pid in self._queries.fetch_wos_source_structures(cur):
            _wos_institution_cache[src_id] = pid
        for src_id, pid in self._queries.fetch_wos_source_persons_with_daisng(cur):
            _wos_author_cache[src_id] = pid
        self.logger.info(
            f"Cache WoS : {len(_wos_institution_cache)} institutions, "
            f"{len(_wos_author_cache)} auteurs"
        )

    def process_work(self, cur: Any, row: Any) -> bool | None:
        assert (
            self._journal_repo is not None
            and self._publisher_repo is not None
            and self._pub_repo is not None
        )
        return process_record(
            cur,
            self._queries,
            self.logger,
            row,
            journal_repo=self._journal_repo,
            publisher_repo=self._publisher_repo,
            pub_repo=self._pub_repo,
            staging_queries=self._staging,
        )

    def post_process(self, cur: Any) -> None:
        deleted_dups = self._queries.delete_wos_duplicate_authorships(cur)
        if deleted_dups:
            self.logger.info("Doublons de position supprimés : %d", deleted_dups)
        orphans = self._queries.delete_wos_orphan_legacy_source_persons(cur)
        if orphans:
            self.logger.info("source_persons legacy orphelins supprimés : %d", orphans)

    def cleanup(self) -> None:
        _wos_institution_cache.clear()
        _wos_author_cache.clear()
