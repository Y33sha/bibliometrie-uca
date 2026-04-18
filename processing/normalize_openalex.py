"""
Normalisation des données OpenAlex : staging → tables structurées.

Usage:
    python normalize_openalex.py              # traiter tous les works non traités
    python normalize_openalex.py --limit 100  # traiter N works (pour test)
    python normalize_openalex.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications          (tables de vérité — partagées)
    source_publications                            (lien staging ↔ publication, source='openalex')
    source_persons                              (auteurs unifiés, source='openalex')
    source_authorships                          (lien document × auteur, source='openalex', avec source_struct_ids)
    source_structures                           (structures sources, source='openalex')

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import argparse
import os
import re

from psycopg2.extras import Json, RealDictCursor

from db.connection import get_connection
from application.journals import find_or_create_journal, find_or_create_publisher
from application.publications import (
    find_by_doi,
    find_by_nnt,
    refresh_from_sources,
    resolve_doi_conflict,
    try_merge_by_doi,
)
from application.publications import find_or_create as find_or_create_publication
from infrastructure.addresses import link_addresses
from infrastructure.db_helpers import mark_staging_done
from domain.doc_types import map_doc_type
from utils.doi import clean_doi
from utils.hal import extract_hal_id_from_url
from infrastructure.log import setup_logger
from utils.nnt import extract_nnt_from_openalex, is_theses_fr_source
from domain.normalize import normalize_text
from infrastructure.zenodo import ZenodoResolutionError, is_zenodo_doi, resolve_zenodo_doi

# ----- Logging -----
logger = setup_logger("normalize_openalex", os.path.join(os.path.dirname(__file__), "logs"))


# =============================================================
# MAPPINGS
# =============================================================


# OpenAlex OA status → notre enum oa_type
OA_MAP = {
    "gold": "gold",
    "diamond": "diamond",
    "hybrid": "hybrid",
    "bronze": "bronze",
    "green": "green",
    "closed": "closed",
}


# =============================================================
# UTILITAIRES
# =============================================================


def extract_locations_data(work: dict) -> tuple[list[str], dict]:
    """Extrait les URLs et identifiants depuis les locations d'un work OpenAlex.

    Retourne (urls, external_ids) où :
      - urls : liste dédupliquée de landing_page_url et pdf_url
      - external_ids : dict d'identifiants extraits des URLs (hal, nnt, pmid, pmc)
    """
    urls = []
    seen = set()
    external_ids: dict[str, str] = {}

    for loc in work.get("locations") or []:
        for key in ("landing_page_url", "pdf_url"):
            url = loc.get(key)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

    # Extraire les identifiants des URLs
    for url in urls:
        # HAL
        if not external_ids.get("hal"):
            hal_id = extract_hal_id_from_url(url)
            if hal_id:
                external_ids["hal"] = hal_id
        # theses.fr / NNT
        if not external_ids.get("nnt"):
            m = re.search(r"theses\.fr/([A-Za-z0-9]+)", url)
            if m:
                external_ids["nnt"] = m.group(1)
        # PubMed
        if not external_ids.get("pmid"):
            m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", url)
            if m:
                external_ids["pmid"] = m.group(1)
        # PMC
        if not external_ids.get("pmc"):
            m = re.search(r"ncbi\.nlm\.nih\.gov/pmc/articles/(?:PMC)?(\d+)", url)
            if m:
                external_ids["pmc"] = f"PMC{m.group(1)}"

    return urls, external_ids


def reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Reconstruit le texte de l'abstract depuis l'inverted index OpenAlex.

    Le format est {mot: [positions]} → on reconstitue le texte en ordre.
    """
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, indices in inverted_index.items():
        for idx in indices:
            positions[idx] = word
    if not positions:
        return None
    return " ".join(positions[k] for k in sorted(positions))


def extract_topics(work: dict) -> list[dict] | None:
    """Extrait les topics OpenAlex sous forme de liste simplifiée."""
    raw = work.get("topics")
    if not raw:
        return None
    topics = []
    for t in raw:
        topic = {}
        for level in ("domain", "field", "subfield", "topic"):
            obj = t.get(level) or t if level == "topic" else t.get(level)
            if obj and obj.get("display_name"):
                topic[level] = obj["display_name"]
        if t.get("score") is not None:
            topic["score"] = t["score"]
        if topic:
            topics.append(topic)
    return topics or None


def extract_short_id(url: str, prefix: str = "https://openalex.org/") -> str:
    """Extrait l'ID court d'une URL OpenAlex."""
    if url and url.startswith(prefix):
        return url.replace(prefix, "")
    return url or ""


def is_hal_primary_location(work: dict) -> bool:
    """Vérifie si la primary_location d'un work OpenAlex pointe vers HAL."""
    location = work.get("primary_location") or {}
    url = location.get("landing_page_url") or ""
    source = location.get("source") or {}
    source_url = source.get("homepage_url") or ""
    source_type = source.get("type") or ""
    if re.search(r"/(?:hal|tel|halshs|inserm|pasteur|cea|ineris)-\d+", url):
        return True
    if source_type == "repository" and (
        "hal" in source_url.lower() or "hal" in (source.get("display_name") or "").lower()
    ):
        return True
    return False


def find_hal_publication_id(cur, work: dict) -> int | None:
    """
    Si le work OpenAlex pointe vers un document HAL existant,
    retourne le publication_id associé (pour éviter les doublons).
    """
    location = work.get("primary_location") or {}
    url = location.get("landing_page_url") or ""
    hal_id = extract_hal_id_from_url(url)
    if not hal_id:
        return None

    cur.execute(
        "SELECT publication_id FROM source_publications WHERE source = 'hal' AND source_id = %s",
        (hal_id,),
    )
    row = cur.fetchone()
    if row and row["publication_id"]:
        return row["publication_id"]
    return None


def is_repository_source(work: dict) -> bool:
    """Vérifie si la primary_location est un repository (SPIRE, Zenodo, etc.)."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    return source.get("type") == "repository"


# =============================================================
# PUBLISHERS & JOURNALS (via services/journals.py)
# =============================================================


def upsert_publisher(cur, work: dict) -> int | None:
    """Extrait et trouve/crée l'éditeur depuis le work OpenAlex."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    publisher_name = source.get("host_organization_name")
    if not publisher_name:
        return None
    openalex_id = extract_short_id(source.get("host_organization") or "")
    return find_or_create_publisher(cur, publisher_name, openalex_id=openalex_id or None)


def upsert_journal(cur, work: dict, publisher_id: int | None) -> int | None:
    """Extrait et trouve/crée la revue depuis le work OpenAlex."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    title = source.get("display_name")
    if not title:
        return None

    openalex_id = extract_short_id(source.get("id") or "")
    issn_l = source.get("issn_l")
    issns = source.get("issn") or []
    issn = None
    eissn = None
    for i in issns:
        if i != issn_l:
            if not issn:
                issn = i
            elif not eissn:
                eissn = i

    source_type = source.get("type")
    oa_model = None
    if source_type == "journal":
        oa_model = "full_oa" if source.get("is_oa", False) else "subscription"
    elif source_type == "repository":
        oa_model = "repository"

    return find_or_create_journal(
        cur,
        title,
        issn=issn,
        eissn=eissn,
        issnl=issn_l,
        publisher_id=publisher_id,
        openalex_id=openalex_id or None,
        oa_model=oa_model,
    )


# =============================================================
# PUBLICATIONS (inchangé — table de vérité)
# =============================================================


def extract_pub_metadata(work: dict, journal_id: int | None) -> dict:
    """Extrait les métadonnées de publication d'un work OpenAlex.

    Retourne un dict utilisable par find_or_create_publication.
    """
    doi = clean_doi(work.get("doi"))
    title = work.get("title") or work.get("display_name") or ""
    pub_year = work.get("publication_year")

    raw_type = work.get("type") or "other"
    doc_type = raw_type  # stocké brut dans source_publications

    nnt = None
    if is_theses_fr_source(work):
        doc_type = "thesis"
        nnt = extract_nnt_from_openalex(work)
    elif raw_type == "dissertation":
        loc_url = (work.get("primary_location") or {}).get("landing_page_url") or ""
        if "dumas." in loc_url:
            doc_type = "memoir"

    oa_info = work.get("open_access") or {}
    oa_status = OA_MAP.get(oa_info.get("oa_status") or "closed", "unknown")
    language = work.get("language")

    container_title = None
    if not journal_id:
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        container_title = source.get("display_name")

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


def find_publication(cur, work: dict, journal_id: int | None) -> int | None:
    """Cherche une publication existante sans en créer. Retourne l'id ou None."""
    meta = extract_pub_metadata(work, journal_id)
    if not meta["pub_year"] or not meta["title"]:
        return None
    # Mapper le doc_type pour find_or_create (resolve_doi_conflict a besoin du type canonique)
    meta["doc_type"] = map_doc_type(meta["doc_type"], "openalex")
    pub_id, _ = find_or_create_publication(cur, **meta, allow_create=False)
    return pub_id


# =============================================================
# SOURCE DOCUMENTS (OPENALEX)
# =============================================================


def insert_openalex_document(
    cur, work: dict, staging_id: int, publication_id: int | None, pub_meta: dict | None = None
) -> int:
    """
    Crée/retrouve l'entrée source_publications pour OpenAlex.
    Retourne source_publications.id.
    """
    openalex_id = extract_short_id(work["id"])
    doi = clean_doi(work.get("doi"))
    title = work.get("title") or work.get("display_name") or ""
    pub_year = work.get("publication_year")
    doc_type = work.get("type")

    # URLs et identifiants extraits des locations
    urls, location_ids = extract_locations_data(work)

    # NNT depuis la structure du work (prioritaire sur celui extrait des URLs)
    if is_theses_fr_source(work):
        nnt = extract_nnt_from_openalex(work)
        if nnt:
            location_ids["nnt"] = nnt

    # Conserver le DOI original si retiré lors d'un conflit chapitre/ouvrage
    if pub_meta and pub_meta.get("source_doi"):
        location_ids["source_doi"] = pub_meta["source_doi"]

    external_ids = Json(location_ids) if location_ids else None
    cited_by_count = work.get("cited_by_count")
    is_retracted = work.get("is_retracted") or False

    # Biblio (volume, issue, pages)
    raw_biblio = work.get("biblio") or {}
    biblio_clean = {
        k: raw_biblio[k]
        for k in ("volume", "issue", "first_page", "last_page")
        if raw_biblio.get(k)
    }
    biblio = Json(biblio_clean) if biblio_clean else None

    # Abstract, keywords, topics
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    keywords = work.get("keywords")
    if isinstance(keywords, list):
        keywords = [k.get("keyword") if isinstance(k, dict) else k for k in keywords]
        keywords = [k for k in keywords if k] or None
    else:
        keywords = None
    topics = extract_topics(work)
    topics_json = Json(topics) if topics else None

    # Métadonnées de publication (pour création différée)
    journal_id = pub_meta.get("journal_id") if pub_meta else None
    oa_status = pub_meta.get("oa_status") if pub_meta else None
    language = pub_meta.get("language") if pub_meta else None
    container_title = pub_meta.get("container_title") if pub_meta else None

    cur.execute(
        """
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id, external_ids, urls, cited_by_count,
             journal_id, oa_status, language, container_title,
             is_retracted, biblio, abstract, keywords, topics)
        VALUES ('openalex', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            external_ids = COALESCE(source_publications.external_ids, '{}') || COALESCE(EXCLUDED.external_ids, '{}'),
            urls = COALESCE(EXCLUDED.urls, source_publications.urls),
            cited_by_count = GREATEST(COALESCE(EXCLUDED.cited_by_count, 0), COALESCE(source_publications.cited_by_count, 0)),
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            is_retracted = COALESCE(EXCLUDED.is_retracted, source_publications.is_retracted),
            biblio = COALESCE(EXCLUDED.biblio, source_publications.biblio),
            abstract = COALESCE(EXCLUDED.abstract, source_publications.abstract),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics)
        RETURNING id
    """,
        (
            openalex_id,
            doi,
            title,
            pub_year,
            doc_type,
            publication_id,
            staging_id,
            external_ids,
            urls or None,
            cited_by_count,
            journal_id,
            oa_status,
            language,
            container_title,
            is_retracted,
            biblio,
            abstract,
            keywords,
            topics_json,
        ),
    )
    return cur.fetchone()["id"]


# =============================================================
# OPENALEX AUTHORS (source_persons, source='openalex')
# =============================================================


def upsert_openalex_author(cur, authorship: dict) -> int | None:
    """
    Insère/retrouve un auteur OpenAlex dans source_persons (source='openalex').
    Déduplique par openalex_id (clé unique via source_id).
    Retourne source_persons.id ou None.
    """
    author_data = authorship.get("author") or {}
    display_name = author_data.get("display_name")
    if not display_name:
        return None

    openalex_id = extract_short_id(author_data.get("id") or "")
    if not openalex_id:
        return None

    # source_id = COALESCE(openalex_id, 'nokey-{old_id}')
    # Ici openalex_id est toujours présent (on retourne None sinon)
    source_id = openalex_id

    orcid = author_data.get("orcid")
    if orcid:
        orcid = orcid.replace("https://orcid.org/", "").strip()
        if not orcid:
            orcid = None

    # Séparer nom/prénom (heuristique : dernier mot = nom)
    parts = display_name.strip().split()
    if len(parts) >= 2:
        first_name = " ".join(parts[:-1])
        last_name = parts[-1]
    else:
        first_name = None
        last_name = display_name

    cur.execute(
        """
        INSERT INTO source_persons
            (source, source_id, full_name, last_name, first_name, orcid)
        VALUES ('openalex', %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            orcid = COALESCE(source_persons.orcid, EXCLUDED.orcid),
            full_name = EXCLUDED.full_name
        RETURNING id
    """,
        (source_id, display_name, last_name, first_name, orcid),
    )
    return cur.fetchone()["id"]


# =============================================================
# OPENALEX INSTITUTIONS (source_structures, source='openalex')
# =============================================================


def upsert_openalex_institution(cur, institution: dict) -> int | None:
    """
    Insère/retrouve une institution OpenAlex dans source_structures.
    Retourne source_structures.id ou None.
    """
    inst_id_url = institution.get("id")
    if not inst_id_url:
        return None

    openalex_id = extract_short_id(inst_id_url)
    name = institution.get("display_name") or ""
    ror_id = institution.get("ror")
    country_code = institution.get("country_code")
    inst_type = institution.get("type")

    if not name:
        # Essayer de retrouver quand même par source_id
        cur.execute(
            """
            SELECT id FROM source_structures
            WHERE source = 'openalex' AND source_id = %s
        """,
            (openalex_id,),
        )
        row = cur.fetchone()
        return row["id"] if row else None

    source_data = Json({"type": inst_type}) if inst_type else None

    cur.execute(
        """
        INSERT INTO source_structures
            (source, source_id, name, ror_id, country, source_data)
        VALUES ('openalex', %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            name = COALESCE(NULLIF(source_structures.name, ''), EXCLUDED.name),
            ror_id = COALESCE(source_structures.ror_id, EXCLUDED.ror_id),
            source_data = COALESCE(source_structures.source_data, '{}') ||
                          COALESCE(EXCLUDED.source_data, '{}')
        RETURNING id
    """,
        (openalex_id, name, ror_id, country_code, source_data),
    )
    row = cur.fetchone()
    return row["id"] if row else None


# =============================================================
# OPENALEX AUTHORSHIPS
# =============================================================


def process_authorships(cur, work: dict, source_publication_id: int):
    """
    Traite les authorships d'un work OpenAlex :
    - Insère/retrouve chaque auteur dans source_persons (source='openalex')
    - Crée les liens source_authorships (source='openalex')
    - Extrait et insère les institutions dans source_structures (source='openalex')
    - Stocke les source_struct_ids (source_structures.id) sur chaque authorship
    """
    authorships = work.get("authorships") or []

    # Supprimer les anciennes authorships de ce document
    # (nécessaire quand un work refetché a changé d'auteurs/positions)
    cur.execute(
        "DELETE FROM source_authorships WHERE source = 'openalex' AND source_publication_id = %s",
        (source_publication_id,),
    )

    for position, authorship in enumerate(authorships):
        source_person_id = upsert_openalex_author(cur, authorship)
        if not source_person_id:
            continue

        # Nom brut de l'auteur (fiable, contrairement à author.display_name)
        raw_author_name = authorship.get("raw_author_name")

        # Corresponding author
        is_corresponding = authorship.get("is_corresponding", False)

        # Affiliations brutes
        raw_strings = authorship.get("raw_affiliation_strings") or []
        if raw_strings:
            " | ".join(raw_strings)
        else:
            institutions = authorship.get("institutions") or []
            inst_names = [i.get("display_name") for i in institutions if i.get("display_name")]
            " | ".join(inst_names) if inst_names else None

        # Institutions OpenAlex → source_structures.id
        source_struct_ids = []
        for inst in authorship.get("institutions") or []:
            ss_id = upsert_openalex_institution(cur, inst)
            if ss_id:
                source_struct_ids.append(ss_id)

        # Adresses individuelles pour link_addresses
        addr_parts = (
            raw_strings
            if raw_strings
            else (
                [
                    n
                    for n in (i.get("display_name") for i in (authorship.get("institutions") or []))
                    if n
                ]
            )
        )

        cur.execute(
            """
            INSERT INTO source_authorships
                (source, source_publication_id, source_person_id, author_position,
                 source_struct_ids,
                 author_name_normalized, is_corresponding, raw_author_name)
            VALUES ('openalex', %s, %s, %s, %s, normalize_name_form(%s), %s, %s)
            ON CONFLICT (source_publication_id, source_person_id) DO UPDATE SET
                author_name_normalized = COALESCE(
                    EXCLUDED.author_name_normalized,
                    source_authorships.author_name_normalized
                ),
                is_corresponding = EXCLUDED.is_corresponding,
                raw_author_name = EXCLUDED.raw_author_name
            RETURNING id
        """,
            (
                source_publication_id,
                source_person_id,
                position,
                source_struct_ids or None,
                raw_author_name,
                is_corresponding,
                raw_author_name,
            ),
        )
        row = cur.fetchone()
        sa_id = row[0] if isinstance(row, tuple) else row["id"]

        if addr_parts:
            link_addresses(cur, sa_id, addr_parts)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(cur, staging_row: tuple) -> bool:
    """
    Traite un work du staging OpenAlex.
    Retourne True si traité avec succès.
    """
    if isinstance(staging_row, dict):
        staging_id = staging_row["id"]
        openalex_id = staging_row["openalex_id"]
        doi = staging_row["doi"]
        work = staging_row["raw_data"]
    else:
        staging_id, openalex_id, doi, work = staging_row

    try:
        # Zenodo : si le DOI est un concept DOI, vérifier si le version DOI
        # est déjà en staging → skip pour éviter les doublons
        raw_doi = clean_doi(doi)
        if is_zenodo_doi(raw_doi):
            try:
                version_doi = resolve_zenodo_doi(raw_doi)
            except ZenodoResolutionError as e:
                logger.warning(f"  {openalex_id} Zenodo {raw_doi} : {e} — retenté au prochain run")
                return None  # ne pas marquer processed
            if version_doi:
                cur.execute(
                    "SELECT id FROM staging WHERE source = 'openalex' AND lower(doi) = lower(%s)",
                    (version_doi,),
                )
                if cur.fetchone():
                    logger.info(
                        f"  {openalex_id} concept DOI Zenodo {raw_doi} -> "
                        f"version {version_doi} deja en staging, skip"
                    )
                    mark_staging_done(cur, staging_id)
                    return None  # skip, pas une erreur

        # Détecter si la primary_location pointe vers HAL, theses.fr ou un repository
        hal_location = is_hal_primary_location(work)
        theses_fr = is_theses_fr_source(work)
        repo_location = is_repository_source(work)

        if hal_location or theses_fr:
            publisher_id = None
            journal_id = None
        elif repo_location:
            publisher_id = None
            journal_id = None
        else:
            publisher_id = upsert_publisher(cur, work)
            journal_id = upsert_journal(cur, work, publisher_id)

        # Métadonnées de publication (stockées sur source_publications)
        pub_meta = extract_pub_metadata(work, journal_id)

        # Chercher une publication existante (sans créer)
        publication_id = None

        # Via HAL ou theses.fr (cross-référence)
        if hal_location:
            publication_id = find_hal_publication_id(cur, work)
        if not publication_id and theses_fr:
            nnt = extract_nnt_from_openalex(work)
            if nnt:
                existing = find_by_nnt(cur, nnt)
                if existing:
                    publication_id = existing.id

        # Idempotence : réutiliser le publication_id existant
        if not publication_id:
            cur.execute(
                "SELECT publication_id FROM source_publications WHERE source = 'openalex' AND source_id = %s",
                (openalex_id,),
            )
            existing_doc = cur.fetchone()
            if existing_doc and existing_doc["publication_id"]:
                publication_id = existing_doc["publication_id"]

        # Recherche par DOI/NNT/titre (sans création)
        if not publication_id:
            publication_id = find_publication(cur, work, journal_id)

        # Enrichir la publication existante si trouvée
        if publication_id:
            enrich_doi = pub_meta["doi"]
            # Résoudre les conflits de DOI chapitre/ouvrage
            if enrich_doi:
                existing = find_by_doi(cur, enrich_doi)
                if existing and existing.id != publication_id:
                    original_doi = enrich_doi
                    enrich_doi, _ = resolve_doi_conflict(
                        cur,
                        enrich_doi,
                        pub_meta["doc_type"],
                        pub_meta["title_normalized"],
                        existing,
                    )
                    if enrich_doi != original_doi:
                        pub_meta["source_doi"] = original_doi
            # Extraire les champs enrichis depuis le work
            reconstruct_abstract(work.get("abstract_inverted_index"))
            kw_raw = work.get("keywords")
            enrich_keywords = None
            if isinstance(kw_raw, list):
                enrich_keywords = [k.get("keyword") if isinstance(k, dict) else k for k in kw_raw]
                enrich_keywords = [k for k in enrich_keywords if k] or None
            extract_topics(work)
            raw_biblio = work.get("biblio") or {}
            {
                k: raw_biblio[k]
                for k in ("volume", "issue", "first_page", "last_page")
                if raw_biblio.get(k)
            } or None

            publication_id = try_merge_by_doi(cur, publication_id, enrich_doi)

        # Document OpenAlex (source_publications) — publication_id peut être NULL
        source_publication_id = insert_openalex_document(
            cur, work, staging_id, publication_id, pub_meta
        )

        # Auteurs et authorships
        process_authorships(cur, work, source_publication_id)

        # Recalcul complet des métadonnées depuis toutes les sources
        if publication_id:
            refresh_from_sources(cur, publication_id)

        mark_staging_done(cur, staging_id)

        return True

    except Exception as e:
        logger.error(f"Erreur sur {openalex_id}: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Normalisation OpenAlex → tables structurées")
    parser.add_argument("--limit", type=int, help="Nombre max de works à traiter")
    parser.add_argument(
        "--reset", action="store_true", help="Remettre tous les works à processed=FALSE"
    )
    parser.add_argument(
        "--batch-size", type=int, default=500, help="Taille du commit batch (défaut: 500)"
    )
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if args.reset:
            cur.execute("UPDATE staging SET processed = FALSE WHERE source = 'openalex'")
            count = cur.rowcount
            conn.commit()
            logger.info(f"Reset : {count} works remis à processed=FALSE")
            return

        cur.execute("SELECT COUNT(*) FROM staging WHERE source = 'openalex' AND processed = FALSE")
        total = cur.fetchone()["count"]
        logger.info(f"=== Normalisation OpenAlex : {total} works à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = args.limit or total
        limit = min(limit, total)
        logger.info(f"Traitement de {limit} works (batch size: {args.batch_size})")

        # Charger les IDs puis fetch par lots pour limiter la mémoire
        cur.execute(
            """
            SELECT id FROM staging
            WHERE source = 'openalex' AND processed = FALSE
            ORDER BY id
            LIMIT %s
        """,
            (limit,),
        )
        work_ids = [r["id"] for r in cur.fetchall()]

        processed = 0
        skipped = 0
        errors = 0
        FETCH_BATCH = 50

        for batch_start in range(0, len(work_ids), FETCH_BATCH):
            batch_ids = work_ids[batch_start : batch_start + FETCH_BATCH]
            cur.execute(
                """
                SELECT id, source_id AS openalex_id, doi, raw_data
                FROM staging WHERE id = ANY(%s)
                ORDER BY id
            """,
                (batch_ids,),
            )
            batch_rows = cur.fetchall()

            for row in batch_rows:
                try:
                    result = process_work(cur, row)
                    if result is True:
                        processed += 1
                    elif result is None:
                        skipped += 1
                    else:
                        errors += 1
                except Exception:
                    conn.rollback()
                    errors += 1
                    continue

                done = processed + skipped
                if done % args.batch_size == 0:
                    conn.commit()
                    parts = [f"{done}/{limit} traites"]
                    if skipped:
                        parts.append(f"{skipped} ignores")
                    if errors:
                        parts.append(f"{errors} erreurs")
                    logger.info(f"  {', '.join(parts)}")

        conn.commit()

        logger.info("\n=== Terminé ===")
        logger.info(f"Traités avec succès : {processed}")
        if skipped:
            logger.info(f"Ignorés (Zenodo, etc.) : {skipped}")
        logger.info(f"Erreurs : {errors}")
        cur.execute("SELECT COUNT(*) FROM source_structures WHERE source = 'openalex'")
        count = cur.fetchone()["count"]
        logger.info(f"  source_structures (openalex) : {count} enregistrements")
        cur.execute("SELECT COUNT(*) FROM source_persons WHERE source = 'openalex'")
        count = cur.fetchone()["count"]
        logger.info(f"  source_persons (openalex) : {count} enregistrements")
        cur.execute("SELECT COUNT(*) FROM source_publications WHERE source = 'openalex'")
        count = cur.fetchone()["count"]
        logger.info(f"  source_publications (openalex) : {count} enregistrements")

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
