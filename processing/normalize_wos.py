"""
Normalisation des données WoS : staging_wos → tables normalisées.

Usage:
    python normalize_wos.py              # traiter tous les works non traités
    python normalize_wos.py --limit 100  # traiter N works (pour test)
    python normalize_wos.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    wos_documents                           (lien staging ↔ publication)
    wos_authors                             (auteurs WoS dédupliqués)
    wos_authorships                         (lien document × auteur)

Gère deux formats de raw_data :
    - TSV (fichiers téléchargés) : clés 2 lettres (TI, AU, AF, SO, PU, etc.)
    - API (WoS Expanded API) : structure imbriquée (static_data, dynamic_data)

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import argparse
import logging
import os
import re
import sys

import psycopg2
from psycopg2.extras import Json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.normalize import normalize_text

# ----- Logging -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "normalize_wos.log")
        ),
    ],
)
logger = logging.getLogger(__name__)


# =============================================================
# MAPPINGS
# =============================================================

# WoS document type → notre enum doc_type
DOCTYPE_MAP = {
    "article": "article",
    "review": "review",
    "book": "book",
    "book chapter": "book_chapter",
    "proceedings paper": "conference_paper",
    "editorial material": "editorial",
    "letter": "article",
    "meeting abstract": "conference_paper",
    "book review": "review",
    "correction": "other",
    "retraction": "other",
    "news item": "other",
    "reprint": "other",
    "note": "article",
    "data paper": "other",
    "early access": "article",
    "software review": "other",
    "discussion": "other",
    "biographical-item": "other",
    "bibliography": "other",
    "art exhibit review": "other",
    "dance performance review": "other",
    "film review": "other",
    "music performance review": "other",
    "music score review": "other",
    "poetry": "other",
    "record review": "other",
    "theater review": "other",
    "tv review, radio review": "other",
    "hardware review": "other",
    "database review": "other",
    "chronology": "other",
    "excerpt": "other",
    "fiction, creative prose": "other",
    "script": "other",
    "item about an individual": "other",
}


# =============================================================
# UTILITAIRES
# =============================================================


def clean_doi(doi: str | None) -> str | None:
    """Nettoie un DOI."""
    if not doi:
        return None
    doi = doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").strip()
    return doi if doi else None


def detect_format(raw_data: dict) -> str:
    """Détecte le format : 'tsv' ou 'api'."""
    if "static_data" in raw_data:
        return "api"
    return "tsv"


def map_doc_type(raw_type: str | None) -> str:
    """Mappe un type de document WoS vers notre enum."""
    if not raw_type:
        return "other"
    # WoS peut avoir des types composites : "Article; Proceedings Paper"
    # On prend le premier type significatif
    parts = [p.strip().lower() for p in raw_type.split(";")]
    for part in parts:
        mapped = DOCTYPE_MAP.get(part)
        if mapped and mapped != "other":
            return mapped
    # Fallback sur le premier
    return DOCTYPE_MAP.get(parts[0], "other")


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


# =============================================================
# EXTRACTION DEPUIS FORMAT TSV
# =============================================================

def _parse_tsv_authors(raw: dict) -> list[dict]:
    """Extrait les auteurs depuis le format TSV."""
    # AF = full names ("LastName, FirstName; ..."), AU = abbreviated
    af_str = raw.get("AF", "")
    au_str = raw.get("AU", "")

    if af_str:
        af_names = [n.strip() for n in af_str.split(";") if n.strip()]
    elif au_str:
        af_names = [n.strip() for n in au_str.split(";") if n.strip()]
    else:
        return []

    # OI = ORCID ("Name/0000-0001-...; Name2/0000-...")
    orcid_map = {}
    oi_str = raw.get("OI", "")
    if oi_str:
        for entry in oi_str.split(";"):
            entry = entry.strip()
            if "/" in entry:
                name_part, orcid = entry.rsplit("/", 1)
                orcid = orcid.strip()
                if re.match(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$", orcid):
                    orcid_map[name_part.strip().lower()] = orcid

    # RI = ResearcherID ("Name/RID; ...")
    rid_map = {}
    ri_str = raw.get("RI", "")
    if ri_str:
        for entry in ri_str.split(";"):
            entry = entry.strip()
            if "/" in entry:
                name_part, rid = entry.rsplit("/", 1)
                rid_map[name_part.strip().lower()] = rid.strip()

    # RP = reprint/corresponding author address
    rp_str = raw.get("RP", "")
    corresponding_name = None
    if rp_str:
        match = re.match(r"^([^(]+)\(corresponding", rp_str)
        if match:
            corresponding_name = match.group(1).strip().lower()

    # C1 = affiliations : "[Author1; Author2] Address; [Author3] Address2"
    c1_str = raw.get("C1", "")
    author_affiliations = _parse_c1_field(c1_str, af_names)

    authors = []
    for i, full_name in enumerate(af_names):
        # Séparer nom/prénom ("LastName, FirstName")
        if "," in full_name:
            parts = full_name.split(",", 1)
            last_name = parts[0].strip()
            first_name = parts[1].strip()
        else:
            last_name = full_name.strip()
            first_name = None

        name_lower = full_name.strip().lower()
        orcid = orcid_map.get(name_lower)
        rid = rid_map.get(name_lower)

        # Matching souple pour ORCID/RID (nom de famille seul)
        if not orcid and last_name:
            for key, val in orcid_map.items():
                if last_name.lower() in key:
                    orcid = val
                    break
        if not rid and last_name:
            for key, val in rid_map.items():
                if last_name.lower() in key:
                    rid = val
                    break

        is_corresponding = False
        if corresponding_name and last_name:
            is_corresponding = last_name.lower() in corresponding_name

        raw_affiliation = author_affiliations.get(i)

        authors.append({
            "position": i,
            "full_name": full_name.strip(),
            "last_name": last_name,
            "first_name": first_name,
            "orcid": orcid,
            "researcher_id": rid,
            "daisng_id": None,
            "is_corresponding": is_corresponding,
            "raw_affiliation": raw_affiliation,
        })

    return authors


def _parse_c1_field(c1_str: str, author_names: list[str]) -> dict[int, str]:
    """Parse le champ C1 WoS et retourne un dict {position_auteur: affiliation}.

    Format C1 :
        [Author1; Author2] Address1; [Author3] Address2
    """
    if not c1_str:
        return {}

    # Normaliser les noms d'auteurs pour le matching
    name_to_idx = {}
    for i, name in enumerate(author_names):
        # Le C1 utilise souvent le format AF (full names)
        name_to_idx[name.strip().lower()] = i
        # Aussi avec juste le nom de famille
        if "," in name:
            last = name.split(",", 1)[0].strip().lower()
            # Ne pas écraser si plusieurs auteurs ont le même nom de famille
            if last not in name_to_idx:
                name_to_idx[last] = i

    result: dict[int, str] = {}

    # Séparer les blocs [auteurs] adresse
    # Pattern: [Name1; Name2] Address text
    blocks = re.findall(r'\[([^\]]+)\]\s*([^[]*)', c1_str)

    for author_block, address in blocks:
        address = address.strip().rstrip(";").strip()
        if not address:
            continue

        names_in_block = [n.strip() for n in author_block.split(";")]
        for name in names_in_block:
            name_lower = name.strip().lower()
            idx = name_to_idx.get(name_lower)
            if idx is None:
                # Essayer matching par nom de famille
                if "," in name:
                    last = name.split(",", 1)[0].strip().lower()
                    idx = name_to_idx.get(last)
            if idx is not None:
                if idx in result:
                    result[idx] += " | " + address
                else:
                    result[idx] = address

    return result


def extract_from_tsv(raw: dict, staging_doi: str | None) -> dict:
    """Extrait un record structuré depuis le format TSV."""
    doi = clean_doi(raw.get("DI")) or clean_doi(staging_doi)
    title = raw.get("TI", "").strip() or "(sans titre)"

    pub_year = None
    py_str = raw.get("PY", "")
    if py_str:
        try:
            pub_year = int(py_str)
        except ValueError:
            pass

    return {
        "ut": raw.get("UT", ""),
        "doi": doi,
        "title": title,
        "pub_year": pub_year,
        "doc_type": map_doc_type(raw.get("DT")),
        "language": raw.get("LA"),
        "oa_status": map_oa_status(raw.get("OA")),
        "journal_title": raw.get("SO"),
        "issn": raw.get("SN"),
        "eissn": raw.get("EI"),
        "publisher_name": raw.get("PU"),
        "authors": _parse_tsv_authors(raw),
    }


# =============================================================
# EXTRACTION DEPUIS FORMAT API
# =============================================================

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
    for addr_entry in addr_list:
        spec = addr_entry.get("address_spec", {})
        addr_no = spec.get("addr_no")
        if addr_no is not None:
            addr_map[str(addr_no)] = spec.get("full_address", "")

    authors = []
    for name_obj in name_list:
        if not isinstance(name_obj, dict):
            continue
        if name_obj.get("role") != "author":
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
        if addr_nos:
            addr_no_list = str(addr_nos).split()
            affils = [addr_map[a] for a in addr_no_list if a in addr_map]
            if affils:
                raw_affiliation = " | ".join(affils)

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

    return {
        "ut": raw.get("UID", ""),
        "doi": doi,
        "title": title,
        "pub_year": pub_year,
        "doc_type": map_doc_type(raw_doc_type),
        "language": language,
        "oa_status": oa_status,
        "journal_title": journal_title,
        "issn": _get_api_issn(dynamic, "issn"),
        "eissn": _get_api_issn(dynamic, "eissn"),
        "publisher_name": publisher_name,
        "authors": _parse_api_authors(static, dynamic),
    }


# =============================================================
# PUBLISHERS & JOURNALS (tables de vérité partagées)
# =============================================================

def upsert_publisher(cur, publisher_name: str | None) -> int | None:
    """Insère/retrouve un éditeur par nom normalisé. Retourne publisher.id."""
    if not publisher_name:
        return None

    name_normalized = normalize_text(publisher_name)
    if not name_normalized:
        return None

    cur.execute(
        "SELECT id FROM publishers WHERE name_normalized = %s LIMIT 1",
        (name_normalized,)
    )
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute("""
        INSERT INTO publishers (name, name_normalized)
        VALUES (%s, %s)
        RETURNING id
    """, (publisher_name.strip(), name_normalized))
    return cur.fetchone()[0]


def upsert_journal(cur, rec: dict, publisher_id: int | None) -> int | None:
    """Insère/retrouve une revue. Retourne journal.id."""
    title = rec.get("journal_title")
    if not title:
        return None

    issn = rec.get("issn")
    eissn = rec.get("eissn")
    title_normalized = normalize_text(title)

    # Chercher par ISSN d'abord
    if issn:
        cur.execute("SELECT id FROM journals WHERE issn = %s LIMIT 1", (issn,))
        row = cur.fetchone()
        if row:
            # Enrichir eissn et publisher_id si manquants
            cur.execute("""
                UPDATE journals SET
                    eissn = COALESCE(journals.eissn, %s),
                    publisher_id = COALESCE(journals.publisher_id, %s)
                WHERE id = %s
            """, (eissn, publisher_id, row[0]))
            return row[0]

    # Chercher par eISSN
    if eissn:
        cur.execute("SELECT id FROM journals WHERE eissn = %s LIMIT 1", (eissn,))
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE journals SET
                    issn = COALESCE(journals.issn, %s),
                    publisher_id = COALESCE(journals.publisher_id, %s)
                WHERE id = %s
            """, (issn, publisher_id, row[0]))
            return row[0]

    # Chercher par ISSN-L (WoS n'a pas d'ISSN-L mais l'ISSN peut matcher)
    if issn:
        cur.execute("SELECT id FROM journals WHERE issnl = %s LIMIT 1", (issn,))
        row = cur.fetchone()
        if row:
            return row[0]

    # Chercher par titre normalisé
    cur.execute(
        "SELECT id FROM journals WHERE title_normalized = %s LIMIT 1",
        (title_normalized,)
    )
    row = cur.fetchone()
    if row:
        cur.execute("""
            UPDATE journals SET
                issn = COALESCE(journals.issn, %s),
                eissn = COALESCE(journals.eissn, %s),
                publisher_id = COALESCE(journals.publisher_id, %s)
            WHERE id = %s
        """, (issn, eissn, publisher_id, row[0]))
        return row[0]

    # Créer
    cur.execute("""
        INSERT INTO journals (title, title_normalized, issn, eissn, publisher_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (title.strip(), title_normalized, issn, eissn, publisher_id))
    return cur.fetchone()[0]


# =============================================================
# PUBLICATIONS (table de vérité)
# =============================================================

def upsert_publication(cur, rec: dict, journal_id: int | None) -> int | None:
    """Insère/retrouve la publication canonique. Retourne publication.id."""
    doi = rec["doi"]
    title = rec["title"]
    title_normalized = normalize_text(title)
    pub_year = rec["pub_year"]
    doc_type = rec["doc_type"]
    oa_status = rec["oa_status"]
    language = rec.get("language")

    if not pub_year or not title or title == "(sans titre)":
        return None

    container_title = rec.get("journal_title") if not journal_id else None

    if doi:
        cur.execute("""
            INSERT INTO publications
                (title, title_normalized, doc_type, pub_year, doi,
                 oa_status, journal_id, container_title, language)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (doi) DO UPDATE SET
                journal_id = COALESCE(publications.journal_id, EXCLUDED.journal_id),
                doc_type = CASE
                    WHEN publications.doc_type = 'other'
                         AND EXCLUDED.doc_type <> 'other'
                        THEN EXCLUDED.doc_type
                    ELSE COALESCE(publications.doc_type, EXCLUDED.doc_type)
                END,
                oa_status = CASE
                    WHEN publications.oa_status = 'unknown' THEN EXCLUDED.oa_status
                    WHEN EXCLUDED.oa_status = 'diamond' THEN 'diamond'::oa_type
                    ELSE publications.oa_status
                END,
                container_title = COALESCE(publications.container_title, EXCLUDED.container_title),
                updated_at = now()
            RETURNING id
        """, (title, title_normalized, doc_type, pub_year, doi,
              oa_status, journal_id, container_title, language))
        return cur.fetchone()[0]
    else:
        # Sans DOI : chercher par titre+année+journal (articles uniquement)
        if doc_type == "article" and journal_id:
            cur.execute("""
                SELECT id FROM publications
                WHERE title_normalized = %s AND pub_year = %s AND journal_id = %s
                LIMIT 1
            """, (title_normalized, pub_year, journal_id))
            row = cur.fetchone()
            if row:
                return row[0]

        cur.execute("""
            INSERT INTO publications
                (title, title_normalized, doc_type, pub_year,
                 oa_status, journal_id, container_title, language)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (title, title_normalized, doc_type, pub_year,
              oa_status, journal_id, container_title, language))
        return cur.fetchone()[0]


# =============================================================
# WOS DOCUMENTS
# =============================================================

def insert_wos_document(cur, rec: dict, staging_id: int,
                        publication_id: int) -> int:
    """Crée/retrouve l'entrée wos_documents. Retourne wos_document.id."""
    cur.execute("""
        INSERT INTO wos_documents
            (ut, doi, title, pub_year, doc_type, publication_id, staging_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ut) DO UPDATE SET
            publication_id = COALESCE(
                wos_documents.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, wos_documents.doc_type)
        RETURNING id
    """, (rec["ut"], rec["doi"], rec["title"], rec["pub_year"],
          rec["doc_type"], publication_id, staging_id))
    return cur.fetchone()[0]


# =============================================================
# WOS AUTHORS
# =============================================================

def upsert_wos_author(cur, author: dict) -> int | None:
    """Insère/retrouve un auteur WoS. Retourne wos_authors.id."""
    full_name = author["full_name"]
    if not full_name:
        return None

    last_name = author.get("last_name")
    first_name = author.get("first_name")
    daisng_id = author.get("daisng_id")
    orcid = author.get("orcid")
    researcher_id = author.get("researcher_id")

    # 1. Par daisng_id (clé unique, format API uniquement)
    if daisng_id:
        cur.execute("""
            INSERT INTO wos_authors
                (full_name, last_name, first_name, daisng_id, orcid, researcher_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (daisng_id) DO UPDATE SET
                orcid = COALESCE(wos_authors.orcid, EXCLUDED.orcid),
                researcher_id = COALESCE(wos_authors.researcher_id, EXCLUDED.researcher_id),
                full_name = EXCLUDED.full_name,
                updated_at = now()
            RETURNING id
        """, (full_name, last_name, first_name, daisng_id, orcid, researcher_id))
        return cur.fetchone()[0]

    # 2. Par ORCID (si disponible et déjà connu)
    if orcid:
        cur.execute(
            "SELECT id FROM wos_authors WHERE orcid = %s LIMIT 1",
            (orcid,)
        )
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE wos_authors SET
                    researcher_id = COALESCE(wos_authors.researcher_id, %s),
                    updated_at = now()
                WHERE id = %s
            """, (researcher_id, row[0]))
            return row[0]

    # 3. Par nom exact (last_name + first_name)
    if last_name and first_name:
        cur.execute("""
            SELECT id FROM wos_authors
            WHERE last_name = %s AND first_name = %s AND daisng_id IS NULL
            LIMIT 1
        """, (last_name, first_name))
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE wos_authors SET
                    orcid = COALESCE(wos_authors.orcid, %s),
                    researcher_id = COALESCE(wos_authors.researcher_id, %s),
                    updated_at = now()
                WHERE id = %s
            """, (orcid, researcher_id, row[0]))
            return row[0]

    # 4. Créer
    cur.execute("""
        INSERT INTO wos_authors
            (full_name, last_name, first_name, orcid, researcher_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (full_name, last_name, first_name, orcid, researcher_id))
    return cur.fetchone()[0]


# =============================================================
# WOS AUTHORSHIPS
# =============================================================

def process_authorships(cur, rec: dict, wos_document_id: int):
    """Traite les authorships d'un record WoS."""
    for author in rec.get("authors", []):
        wos_author_id = upsert_wos_author(cur, author)
        if not wos_author_id:
            continue

        cur.execute("""
            INSERT INTO wos_authorships
                (wos_document_id, wos_author_id, author_position,
                 is_corresponding, raw_affiliation)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (wos_document_id, wos_author_id) DO UPDATE SET
                raw_affiliation = COALESCE(
                    EXCLUDED.raw_affiliation,
                    wos_authorships.raw_affiliation
                ),
                is_corresponding = EXCLUDED.is_corresponding OR wos_authorships.is_corresponding
        """, (wos_document_id, wos_author_id, author["position"],
              author["is_corresponding"], author.get("raw_affiliation")))


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================

def process_record(cur, staging_row: tuple) -> bool:
    """Traite un record du staging WoS. Retourne True si succès."""
    staging_id, ut, staging_doi, raw_data = staging_row

    try:
        fmt = detect_format(raw_data)
        if fmt == "tsv":
            rec = extract_from_tsv(raw_data, staging_doi)
        else:
            rec = extract_from_api(raw_data, staging_doi)

        # Forcer le UT depuis le staging si absent du raw_data
        if not rec["ut"]:
            rec["ut"] = ut

        # Publisher & Journal
        publisher_id = upsert_publisher(cur, rec.get("publisher_name"))
        journal_id = upsert_journal(cur, rec, publisher_id)

        # Publication canonique
        publication_id = upsert_publication(cur, rec, journal_id)
        if not publication_id:
            logger.warning(f"Impossible d'insérer {ut} — titre ou année manquant")
            # Marquer processed quand même pour ne pas reboucler
            cur.execute(
                "UPDATE staging_wos SET processed = TRUE WHERE id = %s",
                (staging_id,)
            )
            return False

        # Document WoS
        wos_document_id = insert_wos_document(cur, rec, staging_id, publication_id)

        # Auteurs et authorships
        process_authorships(cur, rec, wos_document_id)

        # Marquer comme traité
        cur.execute(
            "UPDATE staging_wos SET processed = TRUE WHERE id = %s",
            (staging_id,)
        )
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
            cur.execute("UPDATE staging_wos SET processed = FALSE")
            count = cur.rowcount
            conn.commit()
            logger.info(f"Reset : {count} works remis à processed=FALSE")
            return

        cur.execute("SELECT COUNT(*) FROM staging_wos WHERE processed = FALSE")
        total = cur.fetchone()[0]
        logger.info(f"=== Normalisation WoS : {total} works à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = args.limit or total
        limit = min(limit, total)
        logger.info(f"Traitement de {limit} works (batch size: {args.batch_size})")

        cur.execute("""
            SELECT id, ut, doi, raw_data
            FROM staging_wos
            WHERE processed = FALSE
            ORDER BY id
            LIMIT %s
        """, (limit,))

        rows = cur.fetchall()
        processed = 0
        errors = 0

        for row in rows:
            try:
                success = process_record(cur, row)
                if success:
                    processed += 1
                else:
                    errors += 1
            except Exception:
                conn.rollback()
                errors += 1
                continue

            if processed % args.batch_size == 0 and processed > 0:
                conn.commit()
                logger.info(f"  {processed}/{limit} traités ({errors} erreurs)")

        conn.commit()

        # Stats finales
        logger.info(f"\n=== Terminé ===")
        logger.info(f"Traités avec succès : {processed}")
        logger.info(f"Erreurs : {errors}")

        for table in ["publications", "journals", "publishers",
                       "wos_documents", "wos_authors", "wos_authorships"]:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            logger.info(f"  {table} : {count} enregistrements")

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
