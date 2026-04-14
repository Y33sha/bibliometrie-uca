"""
Normalisation des données WoS : staging → tables normalisées.

Usage:
    python normalize_wos.py              # traiter tous les works non traités
    python normalize_wos.py --limit 100  # traiter N works (pour test)
    python normalize_wos.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    source_documents                        (lien staging ↔ publication, source='wos')
    source_authors                          (auteurs unifiés, source='wos')
    source_authorships                      (lien document × auteur, source='wos')

Gère deux formats de raw_data :
    - TSV (fichiers téléchargés) : clés 2 lettres (TI, AU, AF, SO, PU, etc.)
    - API (WoS Expanded API) : structure imbriquée (static_data, dynamic_data)

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import argparse
import os
import sys

import psycopg2
from psycopg2.extras import Json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.doi import clean_doi
from utils.log import setup_logger
from utils.normalize import normalize_text
from utils.authorship_roles import map_role
from services.publications import find_or_create as find_or_create_publication, try_merge_by_doi, refresh_from_sources
from utils.db_helpers import mark_staging_done
from services.journals import find_or_create_publisher, find_or_create_journal

# ----- Logging -----
logger = setup_logger("normalize_wos", os.path.join(os.path.dirname(__file__), "logs"))


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
    from utils.doc_types import map_doc_type as _map
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


def _safe_list(obj) -> list:
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
                    orgs.append({
                        "name": o["content"],
                        "ror_id": o.get("ror_id"),
                        "pref": o.get("pref"),
                    })
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

        authors.append({
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
        })

    return authors


def _get_api_doi(dynamic: dict) -> str | None:
    """Extrait le DOI depuis la structure API."""
    try:
        identifiers = (
            dynamic.get("cluster_related", {})
            .get("identifiers", {})
            .get("identifier", [])
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
            dynamic.get("cluster_related", {})
            .get("identifiers", {})
            .get("identifier", [])
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
    keywords = [k for k in kw_list if k] or None

    # Topics : categories
    cat = frm.get("category_info", {})
    topics = {}
    subjects = cat.get("subjects", {}).get("subject", [])
    if isinstance(subjects, dict):
        subjects = [subjects]
    subj_names = [s.get("content") or s for s in subjects if isinstance(s, dict) and s.get("content")]
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

def upsert_publisher(cur, publisher_name: str | None) -> int | None:
    """Trouve ou crée un éditeur. Délègue au service journals."""
    return find_or_create_publisher(cur, publisher_name)


def upsert_journal(cur, rec: dict, publisher_id: int | None) -> int | None:
    """Trouve ou crée une revue depuis les données WoS."""
    title = rec.get("journal_title")
    if not title:
        return None
    return find_or_create_journal(
        cur, title,
        issn=rec.get("issn"), eissn=rec.get("eissn"),
        publisher_id=publisher_id)


# =============================================================
# PUBLICATIONS (via services/publications.py)
# =============================================================

def extract_pub_metadata(rec: dict, journal_id: int | None) -> dict:
    """Extrait les métadonnées de publication d'un record WoS.

    Retourne un dict utilisable par find_or_create_publication.
    """
    title = rec["title"]
    container_title = rec.get("journal_title") if not journal_id else None

    return dict(title=title, title_normalized=normalize_text(title),
                pub_year=rec["pub_year"], doc_type=rec["doc_type"],
                doi=rec["doi"], oa_status=rec["oa_status"],
                journal_id=journal_id, container_title=container_title,
                language=rec.get("language"))


def find_publication(cur, rec: dict, journal_id: int | None) -> int | None:
    """Cherche une publication existante sans en créer. Retourne l'id ou None."""
    meta = extract_pub_metadata(rec, journal_id)
    if not meta["pub_year"] or not meta["title"] or meta["title"] == "(sans titre)":
        return None
    # Mapper le doc_type pour find_or_create (resolve_doi_conflict a besoin du type canonique)
    meta["doc_type"] = map_doc_type(meta["doc_type"])
    pub_id, _ = find_or_create_publication(cur, **meta, allow_create=False)
    return pub_id


# =============================================================
# SOURCE DOCUMENTS (WOS)
# =============================================================

def insert_wos_document(cur, rec: dict, staging_id: int,
                        publication_id: int | None,
                        pub_meta: dict | None = None) -> int:
    """Crée/retrouve l'entrée source_documents pour WoS. Retourne source_documents.id."""
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

    cur.execute("""
        INSERT INTO source_documents
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id,
             journal_id, oa_status, language, container_title,
             abstract, cited_by_count, biblio, keywords, topics,
             urls, external_ids)
        VALUES ('wos', %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_documents.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, source_documents.doc_type),
            journal_id = COALESCE(EXCLUDED.journal_id, source_documents.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_documents.oa_status),
            language = COALESCE(EXCLUDED.language, source_documents.language),
            container_title = COALESCE(EXCLUDED.container_title, source_documents.container_title),
            abstract = COALESCE(EXCLUDED.abstract, source_documents.abstract),
            cited_by_count = GREATEST(COALESCE(EXCLUDED.cited_by_count, 0), COALESCE(source_documents.cited_by_count, 0)),
            biblio = COALESCE(EXCLUDED.biblio, source_documents.biblio),
            keywords = COALESCE(EXCLUDED.keywords, source_documents.keywords),
            topics = COALESCE(EXCLUDED.topics, source_documents.topics),
            urls = COALESCE(EXCLUDED.urls, source_documents.urls),
            external_ids = COALESCE(source_documents.external_ids, '{}') || COALESCE(EXCLUDED.external_ids, '{}')
        RETURNING id
    """, (rec["ut"], rec["doi"], rec["title"], rec["pub_year"],
          rec["doc_type"], publication_id, staging_id,
          journal_id, oa_status, language, container_title,
          abstract, cited_by_count, biblio, keywords, topics,
          urls, external_ids))
    return cur.fetchone()[0]


# =============================================================
# WOS AUTHORS (source_authors, source='wos')
# =============================================================

_wos_author_cache: dict[str, int] = {}


def upsert_wos_author(cur, author: dict) -> int | None:
    """Insère/retrouve un auteur WoS dans source_authors (source='wos').

    Utilise le daisng_id comme clé unique (format API).
    Cache en mémoire pour éviter les requêtes répétées.
    Retourne source_authors.id.
    """
    full_name = author.get("full_name")
    if not full_name:
        return None

    daisng_id = author.get("daisng_id")
    if not daisng_id:
        # Sans daisng_id, on ne peut pas dédupliquer proprement
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

    cur.execute("""
        INSERT INTO source_authors
            (source, source_id, full_name, last_name, first_name, orcid, source_ids)
        VALUES ('wos', %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            orcid = COALESCE(source_authors.orcid, EXCLUDED.orcid),
            full_name = EXCLUDED.full_name,
            source_ids = COALESCE(source_authors.source_ids, '{}') ||
                         COALESCE(EXCLUDED.source_ids, '{}')
        RETURNING id
    """, (daisng_id, full_name, last_name, first_name, orcid, source_ids_json))
    result = cur.fetchone()[0]
    _wos_author_cache[daisng_id] = result
    return result


# =============================================================
# WOS AUTHORSHIPS
# =============================================================

def _resolve_addresses_batch(cur, raw_texts: set) -> dict[str, int]:
    """Résout un ensemble d'adresses en batch. Retourne {raw_text: id}.

    Insère les adresses inconnues en un seul batch, puis récupère tous les IDs.
    """
    if not raw_texts:
        return {}
    from psycopg2.extras import execute_values as _ev

    # Batch INSERT (ON CONFLICT sur md5(raw_text) pour les existantes)
    values = [(t, normalize_text(t)) for t in raw_texts]
    _ev(cur, """
        INSERT INTO addresses (raw_text, normalized_text)
        VALUES %s
        ON CONFLICT (md5(raw_text)) DO NOTHING
    """, values)

    # Récupérer tous les IDs en un seul SELECT
    cur.execute("SELECT raw_text, id FROM addresses WHERE raw_text = ANY(%s)",
                (list(raw_texts),))
    return {r[0]: r[1] for r in cur.fetchall()}


_wos_institution_cache: dict[str, int] = {}


def upsert_wos_institution(cur, org: dict) -> int | None:
    """Insère/retrouve une organisation WoS dans source_structures. Retourne source_structures.id."""
    name = org.get("name")
    if not name:
        return None

    if name in _wos_institution_cache:
        return _wos_institution_cache[name]

    ror_id = org.get("ror_id")
    cur.execute("""
        INSERT INTO source_structures (source, source_id, name, ror_id)
        VALUES ('wos', %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            ror_id = COALESCE(source_structures.ror_id, EXCLUDED.ror_id)
        RETURNING id
    """, (name, name, ror_id))
    result = cur.fetchone()[0]
    _wos_institution_cache[name] = result
    return result


def process_authorships(cur, rec: dict, source_document_id: int):
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
            upsert_wos_institution(cur, {"name": org_name})

    # Phase 1 : résoudre tous les auteurs (batch upsert source_authors)
    from psycopg2.extras import execute_values as _ev

    # Séparer les auteurs déjà en cache de ceux à insérer
    authors_resolved = []  # [(author_dict, source_author_id)]
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
                deduped.append((
                    'wos', a["daisng_id"], a["full_name"],
                    a.get("last_name"), a.get("first_name"),
                    a.get("orcid"),
                    Json(source_ids) if source_ids else None,
                ))

        _ev(cur, """
            INSERT INTO source_authors
                (source, source_id, full_name, last_name, first_name, orcid, source_ids)
            VALUES %s
            ON CONFLICT (source, source_id) DO UPDATE SET
                orcid = COALESCE(source_authors.orcid, EXCLUDED.orcid),
                full_name = EXCLUDED.full_name,
                source_ids = COALESCE(source_authors.source_ids, '{}'::jsonb) ||
                             COALESCE(EXCLUDED.source_ids, '{}'::jsonb)
            RETURNING id, source_id
        """, deduped)
        for row in cur.fetchall():
            _wos_author_cache[row[1]] = row[0]

        # Résoudre les auteurs insérés
        for a in authors_to_insert:
            aid = _wos_author_cache.get(a["daisng_id"])
            if aid:
                authors_resolved.append((a, aid))

    author_ids = authors_resolved
    if not author_ids:
        return

    # Phase 2 : batch INSERT source_authorships
    from utils.normalize import normalize_name_form

    values = {}  # clé = (source_document_id, source_author_id), dédupliqué
    for author, source_author_id in author_ids:
        key = (source_document_id, source_author_id)
        if key in values:
            continue  # même auteur déjà traité pour ce document

        institution_ids = []
        for org in author.get("organizations", []):
            name = org.get("name")
            if name and name in _wos_institution_cache:
                institution_ids.append(_wos_institution_cache[name])

        raw_affil_text = author.get("raw_affiliation")
        raw_affiliations = Json([raw_affil_text]) if raw_affil_text else None
        name_norm = normalize_name_form(author["full_name"])

        values[key] = (
            'wos', source_document_id, source_author_id, author["position"],
            author["is_corresponding"], raw_affiliations, name_norm,
            institution_ids or None, author.get("roles"),
        )

    _ev(cur, """
        INSERT INTO source_authorships
            (source, source_document_id, source_author_id, author_position,
             is_corresponding, raw_affiliations, author_name_normalized,
             source_struct_ids, roles)
        VALUES %s
        ON CONFLICT (source_document_id, source_author_id) DO UPDATE SET
            raw_affiliations = COALESCE(
                EXCLUDED.raw_affiliations,
                source_authorships.raw_affiliations
            ),
            is_corresponding = EXCLUDED.is_corresponding OR source_authorships.is_corresponding,
            author_name_normalized = COALESCE(
                EXCLUDED.author_name_normalized,
                source_authorships.author_name_normalized
            ),
            source_struct_ids = COALESCE(
                EXCLUDED.source_struct_ids,
                source_authorships.source_struct_ids
            ),
            roles = EXCLUDED.roles,
            addresses_extracted = FALSE
    """, list(values.values()))

    # Phase 3 : batch adresses (source_authorship_addresses)
    authors_with_addrs = [(a, said) for a, said in author_ids if a.get("addresses")]
    if authors_with_addrs:
        # Collecter toutes les adresses uniques du document
        all_addr_texts = set()
        for author, _ in authors_with_addrs:
            all_addr_texts.update(author["addresses"])

        # Résoudre en batch (INSERT + SELECT)
        addr_id_map = _resolve_addresses_batch(cur, all_addr_texts)

        # Récupérer les sa_id
        sa_ids_needed = [said for _, said in authors_with_addrs]
        cur.execute("""
            SELECT source_author_id, id FROM source_authorships
            WHERE source_document_id = %s AND source_author_id = ANY(%s)
        """, (source_document_id, sa_ids_needed))
        sa_id_map = {r[0]: r[1] for r in cur.fetchall()}

        # Construire les liens
        addr_values = []
        for author, source_author_id in authors_with_addrs:
            sa_id = sa_id_map.get(source_author_id)
            if not sa_id:
                continue
            for addr_text in author["addresses"]:
                addr_id = addr_id_map.get(addr_text)
                if addr_id:
                    addr_values.append((sa_id, addr_id))

        if addr_values:
            _ev(cur, """
                INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
                VALUES %s
                ON CONFLICT (source_authorship_id, address_id) DO NOTHING
            """, addr_values)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================

def process_record(cur, staging_row: tuple) -> bool:
    """Traite un record du staging WoS. Retourne True si succès."""
    from utils.timings import StepTimer
    staging_id, ut, staging_doi, raw_data = staging_row

    try:
        t = StepTimer()
        rec = extract_from_api(raw_data, staging_doi)

        # Forcer le UT depuis le staging si absent du raw_data
        if not rec["ut"]:
            rec["ut"] = ut

        # Publisher & Journal
        publisher_id = upsert_publisher(cur, rec.get("publisher_name"))
        journal_id = upsert_journal(cur, rec, publisher_id)
        t.mark("publisher+journal")

        # Métadonnées de publication (stockées sur source_documents)
        pub_meta = extract_pub_metadata(rec, journal_id)

        # Chercher une publication existante (sans créer)
        publication_id = None

        # Idempotence : réutiliser le publication_id existant
        cur.execute(
            "SELECT publication_id FROM source_documents WHERE source = 'wos' AND source_id = %s",
            (rec["ut"],))
        existing_doc = cur.fetchone()
        if existing_doc and existing_doc[0]:
            publication_id = existing_doc[0]

        # Recherche par DOI/titre (sans création)
        if not publication_id:
            publication_id = find_publication(cur, rec, journal_id)
        t.mark("publication")

        # Enrichir la publication existante si trouvée
        if publication_id:
            publication_id = try_merge_by_doi(cur, publication_id, pub_meta["doi"])

        # Document WoS (source_documents)
        source_document_id = insert_wos_document(
            cur, rec, staging_id, publication_id, pub_meta
        )
        t.mark("wos_doc")

        # Auteurs et authorships
        process_authorships(cur, rec, source_document_id)
        t.mark("authors")

        # Recalcul complet des métadonnées depuis toutes les sources
        if publication_id:
            refresh_from_sources(cur, publication_id)
        t.mark("refresh")

        mark_staging_done(cur, staging_id)
        t.log_if_slow(ut, logger)
        return True

    except Exception as e:
        logger.error(f"Erreur sur {ut}: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Normalisation WoS → tables normalisées")
    parser.add_argument("--limit", type=int, help="Nombre max de works à traiter")
    parser.add_argument("--reset", action="store_true",
                        help="Remettre tous les works à processed=FALSE")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="Taille du commit batch (défaut: 500)")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor()

        if args.reset:
            cur.execute("UPDATE staging SET processed = FALSE WHERE source = 'wos'")
            count = cur.rowcount
            conn.commit()
            logger.info(f"Reset : {count} works remis à processed=FALSE")
            return

        cur.execute("SELECT COUNT(*) FROM staging WHERE source = 'wos' AND processed = FALSE")
        total = cur.fetchone()[0]
        logger.info(f"=== Normalisation WoS : {total} works à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = args.limit or total
        limit = min(limit, total)
        logger.info(f"Traitement de {limit} works (batch size: {args.batch_size})")

        # Charger les IDs puis fetch par lots pour limiter la memoire
        cur.execute("""
            SELECT id FROM staging
            WHERE source = 'wos' AND processed = FALSE
            ORDER BY id
            LIMIT %s
        """, (limit,))
        work_ids = [r[0] for r in cur.fetchall()]

        # Pré-charger les caches WoS
        cur.execute("SELECT source_id, id FROM source_structures WHERE source = 'wos'")
        for r in cur.fetchall():
            _wos_institution_cache[r[0]] = r[1]
        cur.execute("SELECT source_id, id FROM source_authors WHERE source = 'wos' AND source_id NOT LIKE 'wos-%%'")
        for r in cur.fetchall():
            _wos_author_cache[r[0]] = r[1]
        logger.info(f"Cache WoS : {len(_wos_institution_cache)} institutions, {len(_wos_author_cache)} auteurs")

        processed = 0
        errors = 0
        FETCH_BATCH = 50

        for batch_start in range(0, len(work_ids), FETCH_BATCH):
            batch_ids = work_ids[batch_start:batch_start + FETCH_BATCH]
            cur.execute("""
                SELECT id, source_id AS ut, doi, raw_data
                FROM staging WHERE id = ANY(%s)
                ORDER BY id
            """, (batch_ids,))
            batch_rows = cur.fetchall()

            for row in batch_rows:
                try:
                    cur.execute("SAVEPOINT normalize_wos_work")
                    success = process_record(cur, row)
                    cur.execute("RELEASE SAVEPOINT normalize_wos_work")
                    if success:
                        processed += 1
                    else:
                        errors += 1
                except Exception as e:
                    try:
                        cur.execute("ROLLBACK TO SAVEPOINT normalize_wos_work")
                    except Exception:
                        conn.rollback()
                    errors += 1
                    continue

                if processed % args.batch_size == 0 and processed > 0:
                    conn.commit()
                    logger.info(f"  {processed}/{limit} traités ({errors} erreurs)")

        conn.commit()
        _wos_institution_cache.clear()
        _wos_author_cache.clear()

        logger.info(f"\n=== Terminé ===")
        logger.info(f"Traités avec succès : {processed}")
        logger.info(f"Erreurs : {errors}")

    except KeyboardInterrupt:
        conn.commit()
        logger.warning("Interruption — données déjà traitées conservées.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
