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

import argparse
import os
import re
import sys
import time

import psycopg2
from psycopg2.extras import Json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.doi import clean_doi
from utils.log import setup_logger
from utils.normalize import normalize_text
from utils.zenodo import is_zenodo_doi, resolve_zenodo_doi, ZenodoResolutionError
from utils.authorship_roles import map_role
from utils.doc_types import map_doc_type
from services.publications import find_or_create as find_or_create_publication, try_merge_by_doi, refresh_from_sources
from utils.nnt import normalize_nnt
from utils.db_helpers import mark_staging_done
from services.journals import find_or_create_publisher, find_or_create_journal

# ----- Logging -----
logger = setup_logger("normalize_hal", os.path.join(os.path.dirname(__file__), "logs"))


# =============================================================
# MAPPINGS
# =============================================================



# =============================================================
# UTILITAIRES
# =============================================================


def as_str(value) -> str | None:
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

def upsert_publisher(cur, publisher_name: str) -> int | None:
    """Trouve ou crée un éditeur. Délègue au service journals."""
    return find_or_create_publisher(cur, publisher_name)


def upsert_journal(cur, doc: dict, publisher_id: int | None) -> int | None:
    """Extrait et trouve/crée la revue depuis les champs HAL."""
    title = as_str(doc.get("journalTitle_s"))
    if not title:
        return None
    return find_or_create_journal(
        cur, title,
        issn=as_str(doc.get("journalIssn_s")),
        eissn=as_str(doc.get("journalEissn_s")),
        publisher_id=publisher_id)


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

    return dict(title=title, title_normalized=normalize_text(title),
                pub_year=pub_year, doc_type=doc_type, doi=doi, nnt=nnt,
                oa_status=oa_status, journal_id=journal_id,
                container_title=container_title, language=language)


def find_publication(cur, doc: dict, journal_id: int | None) -> int | None:
    """Cherche une publication existante sans en créer. Retourne l'id ou None."""
    meta = extract_pub_metadata(doc, journal_id)
    if not meta["pub_year"] or not meta["title"]:
        return None
    pub_id, _ = find_or_create_publication(cur, **meta, allow_create=False)
    return pub_id


# =============================================================
# SOURCE DOCUMENTS (HAL)
# =============================================================

def insert_hal_document(cur, doc: dict, staging_id: int, hal_id: str,
                        hal_collections_staging: list | None,
                        publication_id: int | None,
                        pub_meta: dict | None = None) -> int:
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
    topics = Json({"hal_domains": domain_raw}) if isinstance(domain_raw, list) and domain_raw else None

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

    cur.execute("""
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             hal_collections, publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             abstract, keywords, topics, biblio, urls)
        VALUES ('hal', %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doi = COALESCE(source_publications.doi, EXCLUDED.doi),
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            hal_collections = (
                SELECT array_agg(DISTINCT c ORDER BY c)
                FROM unnest(
                    COALESCE(source_publications.hal_collections, '{}') ||
                    COALESCE(EXCLUDED.hal_collections, '{}')
                ) AS c
            ),
            external_ids = COALESCE(source_publications.external_ids, '{}') || COALESCE(EXCLUDED.external_ids, '{}'),
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            abstract = COALESCE(EXCLUDED.abstract, source_publications.abstract),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics),
            biblio = COALESCE(EXCLUDED.biblio, source_publications.biblio),
            urls = COALESCE(EXCLUDED.urls, source_publications.urls)
        RETURNING id
    """, (hal_id, doi, title, pub_year, doc_type,
          collections_array, publication_id, staging_id, external_ids,
          journal_id, oa_status, language, container_title,
          abstract, keywords, topics, biblio_json, urls))
    return cur.fetchone()[0]


# =============================================================
# HAL AUTHORS (source_persons, source='hal')
# =============================================================

def _hal_source_id(hal_person_id: int | None, hal_form_id: int | None,
                   old_id: int | None = None) -> str:
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


def upsert_hal_author(cur, full_name: str, hal_person_id: int | None,
                      idhal: str | None, hal_form_id: int | None = None,
                      orcid: str | None = None) -> int | None:
    """
    Insère/retrouve un auteur HAL dans source_persons (source='hal').
    Déduplique par :
      1. hal_person_id (clé unique via source_id, auteurs avec compte HAL)
      2. hal_form_id (clé unique via source_id, auteurs sans compte HAL)
      3. nom exact (dernier recours)
    Retourne source_persons.id ou None.
    Utilise un cache mémoire pour éviter les SELECTs redondants.
    """
    if not full_name:
        return None

    # Séparer nom/prénom (heuristique HAL : souvent "Prénom Nom")
    parts = full_name.strip().split()
    if len(parts) >= 2:
        first_name = " ".join(parts[:-1])
        last_name = parts[-1]
    else:
        first_name = None
        last_name = full_name

    # Construire le JSONB source_ids pour les IDs spécifiques HAL
    source_ids = {}
    if hal_person_id and hal_person_id > 0:
        source_ids["hal_person_id"] = hal_person_id
    if idhal:
        source_ids["idhal"] = idhal
    if hal_form_id:
        source_ids["hal_form_id"] = hal_form_id
    source_ids_json = Json(source_ids) if source_ids else None

    # 1. Par hal_person_id (clé fiable) — 0 signifie non identifié
    if hal_person_id and hal_person_id > 0:
        src_id = _hal_source_id(hal_person_id, hal_form_id)
        if src_id in _hal_author_cache:
            return _hal_author_cache[src_id]
        cur.execute("""
            INSERT INTO source_persons
                (source, source_id, full_name, last_name, first_name, orcid,
                 source_ids)
            VALUES ('hal', %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, source_id) DO UPDATE SET
                orcid = COALESCE(source_persons.orcid, EXCLUDED.orcid),
                full_name = EXCLUDED.full_name,
                source_ids = COALESCE(source_persons.source_ids, '{}') ||
                             COALESCE(EXCLUDED.source_ids, '{}')
            RETURNING id
        """, (src_id, full_name, last_name, first_name, orcid,
              source_ids_json))
        result = cur.fetchone()[0]
        _hal_author_cache[src_id] = result
        return result

    # 2. Par hal_form_id (auteurs sans compte HAL mais avec form_id)
    if hal_form_id:
        src_id = _hal_source_id(None, hal_form_id)
        if src_id in _hal_author_cache:
            return _hal_author_cache[src_id]
        cur.execute("""
            INSERT INTO source_persons
                (source, source_id, full_name, last_name, first_name, orcid,
                 source_ids)
            VALUES ('hal', %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, source_id) DO UPDATE SET
                orcid = COALESCE(source_persons.orcid, EXCLUDED.orcid),
                full_name = EXCLUDED.full_name,
                source_ids = COALESCE(source_persons.source_ids, '{}') ||
                             COALESCE(EXCLUDED.source_ids, '{}')
            RETURNING id
        """, (src_id, full_name, last_name, first_name, orcid,
              source_ids_json))
        result = cur.fetchone()[0]
        _hal_author_cache[src_id] = result
        return result

    # 3. Pas de hal_person_id ni form_id → chercher par nom exact
    cache_key = f"nokey:{full_name}:{first_name}"
    if cache_key in _hal_author_cache:
        return _hal_author_cache[cache_key]

    cur.execute("""
        SELECT id FROM source_persons
        WHERE source = 'hal'
          AND source_id LIKE 'nokey-%%'
          AND full_name = %s
          AND first_name IS NOT DISTINCT FROM %s
        LIMIT 1
    """, (full_name, first_name))
    row = cur.fetchone()
    if row:
        if orcid or source_ids_json:
            cur.execute("""
                UPDATE source_persons SET
                    orcid = COALESCE(source_persons.orcid, %s),
                    source_ids = COALESCE(source_persons.source_ids, '{}') ||
                                 COALESCE(%s::jsonb, '{}')
                WHERE id = %s
            """, (orcid, source_ids_json, row[0]))
        _hal_author_cache[cache_key] = row[0]
        return row[0]

    # 4. Nouveau sans identifiant — on génère un source_id séquentiel
    cur.execute("SELECT nextval('source_persons_id_seq')")
    next_id = cur.fetchone()[0]
    src_id = f"nokey-{next_id}"
    cur.execute("""
        INSERT INTO source_persons
            (id, source, source_id, full_name, last_name, first_name, orcid,
             source_ids)
        VALUES (%s, 'hal', %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (next_id, src_id, full_name, last_name, first_name, orcid,
          source_ids_json))
    result = cur.fetchone()[0]
    _hal_author_cache[cache_key] = result
    return result


# =============================================================
# HAL AUTHORSHIPS
# =============================================================

def parse_author_structures(doc: dict) -> dict[int, set[int]]:
    """
    Parse authIdHasStructure_fs pour extraire le mapping
    form_id → {hal_struct_id bruts (entiers HAL, résolus en source_struct_ids ensuite)}.

    Format : "formId-personId_FacetSep_Nom_JoinSep_structId_FacetSep_StructNom"

    On utilise le form_id (et non le person_id) comme clé, car le form_id
    est toujours présent, y compris pour les auteurs sans compte HAL
    (personId = 0).

    Note : retourne les hal_struct_id bruts (entiers HAL). La résolution
    vers source_structures.id se fait dans process_authors via lookup SQL.
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

        form_structs.setdefault(form_id, set()).add(struct_id)

    return form_structs


def process_authors(cur, doc: dict, source_publication_id: int,
                    struct_cache: dict | None = None,
                    struct_name_cache: dict | None = None):
    """
    Traite les auteurs d'un document HAL :
    - Parse les champs alignés pour extraire hal_person_id, idhal et form_id
    - Parse authIdHasStructure_fs pour les affiliations (clé = form_id)
    - Crée/retrouve chaque auteur dans source_persons (source='hal')
    - Crée les source_authorships (source='hal') avec source_struct_ids (source_structures.id)
    """
    names = doc.get("authFullName_s") or []
    orcids = doc.get("authOrcid_s") or []
    qualities = doc.get("authQuality_s") or []

    # authFullNameFormIDPersonIDIDHal_fs :
    #   "Nom_FacetSep_formId-personId_FacetSep_idhal" — aligné par position
    # C'est le champ le plus complet : on en extrait form_id, person_id et idhal
    composite = doc.get("authFullNameFormIDPersonIDIDHal_fs") or []
    form_id_by_pos = {}
    hal_person_id_by_pos = {}
    idhal_by_pos = {}

    for pos, entry in enumerate(composite):
        parts = entry.split("_FacetSep_")
        if len(parts) >= 2:
            # parts[1] = "formId-personId"
            dash_parts = parts[1].rsplit("-", 1)
            if len(dash_parts) == 2:
                try:
                    form_id = int(dash_parts[0])
                    form_id_by_pos[pos] = form_id
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
    form_struct_map = parse_author_structures(doc)

    for position, name in enumerate(names):
        idhal = idhal_by_pos.get(position)
        hal_person_id = hal_person_id_by_pos.get(position)
        form_id = form_id_by_pos.get(position)
        orcid = orcids[position] if position < len(orcids) else None
        # authOrcid_s peut contenir des chaînes vides
        if orcid and not orcid.strip():
            orcid = None

        # authQuality_s : rôle de l'auteur (aut, crp, dir, edt, …)
        quality = qualities[position] if position < len(qualities) else None
        roles, is_corresponding_from_role = map_role("hal", quality)
        is_corresponding = is_corresponding_from_role

        source_person_id = upsert_hal_author(
            cur, name, hal_person_id, idhal, form_id, orcid=orcid
        )
        if not source_person_id:
            continue

        # Structures affiliées à cet auteur sur ce document (par form_id)
        # Résoudre les hal_struct_id bruts → source_structures.id
        source_struct_ids = None
        if form_id and form_id in form_struct_map:
            raw_hal_ids = sorted(form_struct_map[form_id])
            if struct_cache is not None:
                resolved = [struct_cache[str(hid)] for hid in raw_hal_ids if str(hid) in struct_cache]
            else:
                cur.execute("""
                    SELECT id FROM source_structures
                    WHERE source = 'hal' AND source_id = ANY(%s)
                """, ([str(hid) for hid in raw_hal_ids],))
                resolved = [r[0] for r in cur.fetchall()]
            if resolved:
                source_struct_ids = sorted(resolved)

        # raw_affiliations : noms des structures liées (pour populate_addresses)
        raw_affiliations = None
        if source_struct_ids and struct_name_cache:
            struct_names = [struct_name_cache[sid] for sid in source_struct_ids
                           if sid in struct_name_cache and struct_name_cache[sid].strip()]
            if struct_names:
                raw_affiliations = Json(struct_names)

        cur.execute("""
            INSERT INTO source_authorships
                (source, source_publication_id, source_person_id, author_position, source_struct_ids,
                 author_name_normalized, is_corresponding, roles, raw_author_name, raw_affiliations)
            VALUES ('hal', %s, %s, %s, %s, normalize_name_form(%s), %s, %s, %s, %s)
            ON CONFLICT (source_publication_id, source_person_id) DO UPDATE SET
                source_struct_ids = COALESCE(
                    EXCLUDED.source_struct_ids,
                    source_authorships.source_struct_ids
                ),
                author_name_normalized = EXCLUDED.author_name_normalized,
                is_corresponding = EXCLUDED.is_corresponding,
                roles = EXCLUDED.roles,
                raw_author_name = EXCLUDED.raw_author_name,
                raw_affiliations = EXCLUDED.raw_affiliations,
                addresses_extracted = FALSE
        """, (source_publication_id, source_person_id, position,
              source_struct_ids, name, is_corresponding, roles or None, name,
              raw_affiliations))


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================

def process_work(cur, staging_row: tuple, struct_cache: dict | None = None,
                 struct_name_cache: dict | None = None) -> bool:
    """Traite un work du staging HAL."""
    from utils.timings import StepTimer
    staging_id, hal_id, doi, raw_data, hal_collections_staging = staging_row
    doc = raw_data

    try:
        t = StepTimer()
        title = get_title(doc)
        pub_year = doc.get("producedDateY_i")
        if not title or not pub_year:
            logger.warning(f"Impossible d'insérer {hal_id} — titre ou année manquant")
            return False

        # Zenodo : si le DOI est un concept DOI, vérifier si le version DOI
        # est déjà en staging → skip pour éviter les doublons
        raw_doi = clean_doi(as_str(doc.get("doiId_s")))
        if is_zenodo_doi(raw_doi):
            try:
                version_doi = resolve_zenodo_doi(raw_doi)
            except ZenodoResolutionError as e:
                logger.warning(f"  {hal_id} Zenodo {raw_doi} : {e} — retenté au prochain run")
                return False  # ne pas marquer processed
            if version_doi:
                cur.execute(
                    "SELECT id FROM staging WHERE source = 'hal' AND lower(doi) = lower(%s)",
                    (version_doi,))
                if cur.fetchone():
                    logger.info(f"  {hal_id} concept DOI Zenodo {raw_doi} -> "
                                f"version {version_doi} deja en staging, skip")
                    mark_staging_done(cur, staging_id)
                    return False

        publisher_name = as_str(doc.get("journalPublisher_s")) or as_str(doc.get("publisher_s"))
        publisher_id = upsert_publisher(cur, publisher_name)
        journal_id = upsert_journal(cur, doc, publisher_id)
        t.mark("publisher+journal")

        # Métadonnées de publication (stockées sur source_publications)
        pub_meta = extract_pub_metadata(doc, journal_id)

        # Chercher une publication existante (sans créer)
        publication_id = None

        # Idempotence : si source_publications a déjà ce source_id avec un publication_id,
        # le réutiliser au lieu de risquer un doublon
        cur.execute(
            "SELECT publication_id FROM source_publications WHERE source = 'hal' AND source_id = %s",
            (hal_id,))
        existing_doc = cur.fetchone()
        if existing_doc and existing_doc[0]:
            old_pub_id = existing_doc[0]
            # Re-traitement : relancer find pour détecter les fusions par DOI/NNT
            publication_id = find_publication(cur, doc, journal_id)
            if publication_id and publication_id != old_pub_id:
                # DOI/NNT pointe vers une autre publication → fusionner
                from services.publications import merge_publications
                logger.info(f"  {hal_id} : fusion pub {old_pub_id} → {publication_id} (DOI/NNT)")
                merge_publications(cur, publication_id, old_pub_id)
            elif not publication_id:
                publication_id = old_pub_id
        else:
            # Recherche par DOI/NNT/titre (sans création)
            publication_id = find_publication(cur, doc, journal_id)
        t.mark("publication")

        # Enrichir la publication existante si trouvée
        # (try_merge_by_doi gère les fusions DOI, refresh_from_sources recalcule après)
        if publication_id:
            publication_id = try_merge_by_doi(cur, publication_id, clean_doi(as_str(doc.get("doiId_s"))))

        # Document HAL (source_publications) — publication_id peut être NULL
        source_publication_id = insert_hal_document(
            cur, doc, staging_id, hal_id, hal_collections_staging, publication_id, pub_meta
        )
        t.mark("hal_doc")

        # Auteurs et authorships (avec source_struct_ids)
        process_authors(cur, doc, source_publication_id,
                        struct_cache=struct_cache, struct_name_cache=struct_name_cache)
        t.mark("authors")

        # Recalcul complet des métadonnées depuis toutes les sources
        if publication_id:
            refresh_from_sources(cur, publication_id)
        t.mark("refresh")

        mark_staging_done(cur, staging_id)
        t.log_if_slow(hal_id, logger)

        return True

    except Exception as e:
        logger.error(f"Erreur sur {hal_id}: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Normalisation HAL → tables structurées")
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
            cur.execute("UPDATE staging SET processed = FALSE WHERE source = 'hal'")
            count = cur.rowcount
            conn.commit()
            logger.info(f"Reset : {count} works remis à processed=FALSE")
            return

        cur.execute("SELECT COUNT(*) FROM staging WHERE source = 'hal' AND processed = FALSE")
        total = cur.fetchone()[0]
        logger.info(f"=== Normalisation HAL : {total} works à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = args.limit or total
        limit = min(limit, total)
        logger.info(f"Traitement de {limit} works (batch size: {args.batch_size})")

        cur.execute("""
            SELECT id, source_id, doi, raw_data, hal_collections
            FROM staging
            WHERE source = 'hal' AND processed = FALSE
            ORDER BY id
            LIMIT %s
        """, (limit,))

        rows = cur.fetchall()
        processed = 0
        errors = 0
        skipped_hors_perimetre = 0

        # Cache source_structures HAL (source_id → id + nom) pour éviter une requête par auteur
        cur.execute("""
            SELECT source_id, id,
                   COALESCE(name, '') || CASE WHEN acronym IS NOT NULL THEN ' ' || acronym ELSE '' END
            FROM source_structures WHERE source = 'hal'
        """)
        _struct_rows = cur.fetchall()
        struct_cache = {r[0]: r[1] for r in _struct_rows}
        struct_name_cache = {r[1]: r[2] for r in _struct_rows}
        logger.info(f"Cache source_structures : {len(struct_cache)} entrées")

        for row in rows:
            try:
                cur.execute("SAVEPOINT normalize_work")
                success = process_work(cur, row, struct_cache=struct_cache,
                                       struct_name_cache=struct_name_cache)
                cur.execute("RELEASE SAVEPOINT normalize_work")
                if success:
                    processed += 1
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT normalize_work")
                errors += 1
                continue

            if processed % args.batch_size == 0:
                conn.commit()
                logger.info(
                    f"  {processed}/{limit} traités "
                    f"({errors} erreurs, {skipped_hors_perimetre} hors périmètre)"
                )

        conn.commit()

        # Nettoyage : supprimer les doublons de position (garder le plus recent)
        cur.execute("""
            DELETE FROM source_authorship_addresses
            WHERE source_authorship_id IN (
                SELECT sa1.id FROM source_authorships sa1
                JOIN source_authorships sa2
                  ON sa2.source_publication_id = sa1.source_publication_id
                 AND sa2.author_position = sa1.author_position
                 AND sa2.id > sa1.id
                WHERE sa1.source = 'hal' AND sa1.author_position IS NOT NULL
            )
        """)
        cur.execute("""
            DELETE FROM source_authorships
            WHERE source = 'hal' AND id IN (
                SELECT sa1.id FROM source_authorships sa1
                JOIN source_authorships sa2
                  ON sa2.source_publication_id = sa1.source_publication_id
                 AND sa2.author_position = sa1.author_position
                 AND sa2.id > sa1.id
                WHERE sa1.source = 'hal' AND sa1.author_position IS NOT NULL
            )
        """)
        dup_deleted = cur.rowcount
        if dup_deleted:
            logger.info(f"Doublons de position supprimés : {dup_deleted}")

        # Nettoyage : supprimer les source_persons HAL orphelins
        cur.execute("""
            DELETE FROM source_persons
            WHERE source = 'hal'
              AND NOT EXISTS (
                  SELECT 1 FROM source_authorships sa
                  WHERE sa.source_person_id = source_persons.id
              )
        """)
        orphans_deleted = cur.rowcount
        if orphans_deleted:
            logger.info(f"Source_authors orphelins supprimés : {orphans_deleted}")

        conn.commit()
        struct_cache.clear()
        _hal_author_cache.clear()

        logger.info(f"\n=== Terminé ===")
        logger.info(f"Traités avec succès : {processed}")
        logger.info(f"Hors périmètre (enrichissement seul) : {skipped_hors_perimetre}")
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
