"""
Normalisation des données theses.fr : staging → tables structurées.

Usage:
    python normalize_theses.py              # traiter tous les works non traités
    python normalize_theses.py --limit 100  # traiter N works (pour test)
    python normalize_theses.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publications                (table de vérité)
    source_publications            (source='theses')
    source_persons              (source='theses')
    source_authorships          (source='theses', avec roles)

Particularités theses.fr :
- Pas de journal (les thèses ne sont pas publiées dans des revues)
- Les rôles sont structurels : auteurs, directeurs, rapporteurs, examinateurs, president
- Le PPN IdRef sert de clé de dédup pour les auteurs
- Le NNT sert de DOI-équivalent pour les thèses soutenues
- Les thèses en cours n'ont ni NNT ni DOI

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import argparse
import os

from psycopg2.extras import Json, RealDictCursor

from db.connection import get_connection
from application.publications import (
    find_or_create,
    find_thesis_by_title,
    refresh_from_sources,
    try_merge_by_doi,
)
from infrastructure.addresses import link_addresses
from domain.authorship_roles import THESES_FIELD_ROLES, merge_roles
from infrastructure.db_helpers import mark_staging_done
from infrastructure.log import setup_logger
from domain.names import names_compatible
from utils.nnt import normalize_nnt
from domain.normalize import normalize_name, normalize_text

logger = setup_logger("normalize_theses", os.path.join(os.path.dirname(__file__), "logs"))


# =============================================================
# PUBLICATIONS
# =============================================================


def _extract_thesis_author(these: dict) -> tuple[str, str] | None:
    """Extrait (last_name, first_name) normalisés de l'auteur de la thèse."""
    auteurs = these.get("auteurs") or []
    if not auteurs:
        return None
    auteur = auteurs[0]
    ln = normalize_name(auteur.get("nom") or "")
    fn = normalize_name(auteur.get("prenom") or "")
    return (ln, fn) if ln else None


def _thesis_author_compatible(cur, pub_id: int, author: tuple[str, str]) -> bool:
    """Vérifie si l'auteur d'une thèse existante est compatible avec author."""
    cur.execute(
        """
        SELECT sa.last_name, sa.first_name
        FROM source_authorships sas
        JOIN source_publications sd ON sd.id = sas.source_publication_id
        JOIN source_persons sa ON sa.id = sas.source_person_id
        WHERE sd.publication_id = %s
          AND 'author' = ANY(sas.roles)
        ORDER BY sd.id, sas.author_position
        LIMIT 1
    """,
        (pub_id,),
    )
    row = cur.fetchone()
    if not row:
        # Pas d'auteur connu → on accepte le match (titre+année suffisent)
        return True
    ln = normalize_name(row["last_name"] or "")
    fn = normalize_name(row["first_name"] or "")
    if not ln:
        return True
    if names_compatible(author[0], author[1], ln, fn):
        return True
    # Fallback : tokens identiques (gère les particules type Ben, Le, Da)
    tokens_a = set(f"{author[0]} {author[1]}".split())
    tokens_b = set(f"{ln} {fn}".split())
    return tokens_a == tokens_b and len(tokens_a) >= 2


def extract_pub_metadata(these: dict) -> dict:
    """Extrait les métadonnées de publication d'une thèse.

    Retourne un dict utilisable par find_or_create et par insert_source_document.
    """
    title = these.get("titrePrincipal")
    doc_type = "thesis" if these.get("dateSoutenance") else "ongoing_thesis"

    pub_year = None
    date_sout = these.get("dateSoutenance")
    date_insc = these.get("datePremiereInscriptionDoctorat")
    if date_sout:
        try:
            pub_year = int(date_sout.split("/")[-1])
        except (ValueError, IndexError):
            pass
    if not pub_year and date_insc:
        try:
            pub_year = int(date_insc.split("/")[-1])
        except (ValueError, IndexError):
            pass

    doi = these.get("doi")
    nnt_clean = normalize_nnt(these.get("nnt"))
    title_norm = normalize_text(title) if title else None

    return dict(
        title=title,
        title_normalized=title_norm,
        pub_year=pub_year,
        doc_type=doc_type,
        doi=doi,
        nnt=nnt_clean,
        oa_status="closed",
        journal_id=None,
        container_title=None,
        language=None,
    )


def find_publication(cur, these: dict) -> int | None:
    """Cherche une publication existante sans en créer. Retourne l'id ou None.

    Déduplication en 2 étapes :
    1. Par DOI ou NNT (via find_or_create avec allow_create=False)
    2. Par titre normalisé + année + compatibilité auteur (spécifique thèses)
    """
    meta = extract_pub_metadata(these)
    title = meta["title"]
    if not title:
        return None

    pub_year = meta["pub_year"]
    doi = meta["doi"]
    nnt_clean = meta["nnt"]
    doc_type = meta["doc_type"]
    title_norm = meta["title_normalized"]

    # 1. Chercher par DOI ou NNT (sans créer)
    pub_id, _ = find_or_create(
        cur,
        title=title,
        title_normalized=title_norm,
        pub_year=pub_year,
        doc_type=doc_type,
        doi=doi,
        nnt=nnt_clean,
        allow_create=False,
    )
    if pub_id:
        return pub_id

    # 2. Dédup spécifique thèses : titre + année + auteur compatible
    if pub_year and title_norm:
        candidates = find_thesis_by_title(cur, title_norm, pub_year)
        if candidates:
            author = _extract_thesis_author(these)
            for cand in candidates:
                if not author or _thesis_author_compatible(cur, cand.id, author):
                    # Match trouvé → attribuer le DOI si nécessaire
                    try_merge_by_doi(cur, cand.id, doi)
                    return cand.id

    return None


def _parse_date_iso(date_str: str | None) -> str | None:
    """Convertit JJ/MM/AAAA → YYYY-MM-DD."""
    if not date_str:
        return None
    try:
        parts = date_str.strip().split("/")
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    except (IndexError, ValueError):
        return None


def _update_thesis_meta(cur, pub_id: int, these: dict):
    """Met à jour publications.meta avec les dates de thèse."""
    meta = {}
    ds = _parse_date_iso(these.get("dateSoutenance"))
    di = _parse_date_iso(these.get("datePremiereInscriptionDoctorat"))
    if ds:
        meta["date_soutenance"] = ds
    if di:
        meta["date_inscription"] = di
    if not meta:
        return
    cur.execute(
        """
        UPDATE publications
        SET meta = COALESCE(meta, '{}') || %s, updated_at = now()
        WHERE id = %s
    """,
        (Json(meta), pub_id),
    )


# =============================================================
# SOURCE DOCUMENTS
# =============================================================


def _build_source_meta(these: dict) -> dict | None:
    """Construit le meta jsonb pour source_publications à partir des données brutes."""
    meta = {}
    ds = _parse_date_iso(these.get("dateSoutenance"))
    di = _parse_date_iso(these.get("datePremiereInscriptionDoctorat"))
    if ds:
        meta["date_soutenance"] = ds
    if di:
        meta["date_inscription"] = di

    discipline = these.get("discipline")
    if discipline:
        meta["discipline"] = discipline

    ecoles = these.get("ecolesDoctorale") or []
    ecoles_clean = [{"nom": e["nom"], "ppn": e.get("ppn")} for e in ecoles if e.get("nom")]
    if ecoles_clean:
        meta["ecoles_doctorales"] = ecoles_clean

    partenaires = these.get("partenairesDeRecherche") or []
    partenaires_clean = [
        {"nom": p["nom"], "type": p.get("type")} for p in partenaires if p.get("nom")
    ]
    if partenaires_clean:
        meta["partenaires"] = partenaires_clean

    return meta or None


def insert_source_document(
    cur,
    these: dict,
    staging_id: int,
    theses_id: str,
    publication_id: int | None,
    pub_meta: dict | None = None,
) -> int:
    """Crée/retrouve l'entrée source_publications pour theses.fr."""
    title = these.get("titrePrincipal") or ""
    doc_type = "thesis" if these.get("dateSoutenance") else "ongoing_thesis"

    pub_year = None
    date_sout = these.get("dateSoutenance")
    date_insc = these.get("datePremiereInscriptionDoctorat")
    if date_sout:
        try:
            pub_year = int(date_sout.split("/")[-1])
        except (ValueError, IndexError):
            pass
    if not pub_year and date_insc:
        try:
            pub_year = int(date_insc.split("/")[-1])
        except (ValueError, IndexError):
            pass

    doi = these.get("doi")
    nnt = normalize_nnt(these.get("nnt"))
    external_ids = Json({"nnt": nnt}) if nnt else None

    # Keywords : sujets (mots-cles auteur)
    sujets = these.get("sujets") or []
    keywords = [s.get("libelle") for s in sujets if s.get("libelle")] or None

    # Topics : discipline + sujets Rameau
    topics = {}
    discipline = these.get("discipline")
    if discipline:
        topics["discipline"] = discipline
    rameau = these.get("sujetsRameau") or []
    rameau_list = [r.get("libelle") for r in rameau if r.get("libelle")]
    if rameau_list:
        topics["rameau"] = rameau_list
    topics_json = Json(topics) if topics else None

    # Meta spécifique thèse (discipline, écoles doctorales, partenaires, dates)
    source_meta = _build_source_meta(these)
    source_meta_json = Json(source_meta) if source_meta else None

    # Metadonnees de publication (pour creation differee)
    journal_id = pub_meta.get("journal_id") if pub_meta else None
    oa_status = pub_meta.get("oa_status") if pub_meta else None
    language = pub_meta.get("language") if pub_meta else None
    container_title = pub_meta.get("container_title") if pub_meta else None

    cur.execute(
        """
        INSERT INTO source_publications
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id, external_ids,
             journal_id, oa_status, language, container_title,
             keywords, topics, meta)
        VALUES ('theses', %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_publications.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, source_publications.doc_type),
            external_ids = COALESCE(source_publications.external_ids, '{}') || COALESCE(EXCLUDED.external_ids, '{}'),
            journal_id = COALESCE(EXCLUDED.journal_id, source_publications.journal_id),
            oa_status = COALESCE(EXCLUDED.oa_status, source_publications.oa_status),
            language = COALESCE(EXCLUDED.language, source_publications.language),
            container_title = COALESCE(EXCLUDED.container_title, source_publications.container_title),
            keywords = COALESCE(EXCLUDED.keywords, source_publications.keywords),
            topics = COALESCE(EXCLUDED.topics, source_publications.topics),
            meta = COALESCE(EXCLUDED.meta, source_publications.meta)
        RETURNING id
    """,
        (
            theses_id,
            doi,
            title,
            pub_year,
            doc_type,
            publication_id,
            staging_id,
            external_ids,
            journal_id,
            oa_status,
            language,
            container_title,
            keywords,
            topics_json,
            source_meta_json,
        ),
    )
    return cur.fetchone()["id"]


# =============================================================
# SOURCE AUTHORS
# =============================================================


def upsert_source_author(cur, person: dict) -> int | None:
    """Insère/retrouve un auteur theses.fr. Déduplique par PPN IdRef."""
    nom = person.get("nom")
    prenom = person.get("prenom")
    if not nom:
        return None

    full_name = f"{prenom} {nom}".strip() if prenom else nom
    ppn = person.get("ppn")

    # Par PPN (clé fiable)
    if ppn:
        cur.execute(
            """
            INSERT INTO source_persons
                (source, source_id, full_name, last_name, first_name, idref)
            VALUES ('theses', %s, %s, %s, %s, %s)
            ON CONFLICT (source, source_id) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                idref = COALESCE(source_persons.idref, EXCLUDED.idref)
            RETURNING id
        """,
            (ppn, full_name, nom, prenom, ppn),
        )
        return cur.fetchone()["id"]

    # Sans PPN : dédup par nom exact
    cur.execute(
        """
        SELECT id FROM source_persons
        WHERE source = 'theses'
          AND source_id LIKE 'nokey-%%'
          AND full_name = %s
          AND first_name IS NOT DISTINCT FROM %s
        LIMIT 1
    """,
        (full_name, prenom),
    )
    row = cur.fetchone()
    if row:
        return row["id"]

    # Nouveau sans identifiant
    cur.execute(
        """
        INSERT INTO source_persons
            (source, source_id, full_name, last_name, first_name)
        VALUES ('theses', 'nokey-' || nextval('source_persons_id_seq'), %s, %s, %s)
        RETURNING id
    """,
        (full_name, nom, prenom),
    )
    return cur.fetchone()["id"]


# =============================================================
# SOURCE AUTHORSHIPS
# =============================================================


def process_persons(cur, these: dict, source_publication_id: int):
    """Traite tous les rôles d'une thèse : auteurs, directeurs, rapporteurs, etc.

    Une même personne peut apparaître dans plusieurs champs (ex: directeur + jury).
    On regroupe les rôles par personne (via PPN ou nom).
    """
    # Collecter tous les (personne, rôles) par clé de dédup
    person_roles: dict[str, dict] = {}  # clé → {"person": dict, "roles": list[str]}

    for field, roles in THESES_FIELD_ROLES.items():
        if field == "president":
            # Champ singulier (pas un array)
            president = these.get("president")
            if president and president.get("nom"):
                persons = [president]
            else:
                continue
        else:
            persons = these.get(field) or []

        for person in persons:
            ppn = person.get("ppn")
            nom = person.get("nom")
            if not nom:
                continue

            key = ppn if ppn else f"name:{nom}:{person.get('prenom', '')}"

            if key not in person_roles:
                person_roles[key] = {"person": person, "roles": []}
            person_roles[key]["roles"].extend(roles)

    # Affiliations auteur : partenaires de recherche (labos)
    partenaires = these.get("partenairesDeRecherche") or []
    addr_parts = [p["nom"] for p in partenaires if p.get("nom")] or []

    # Insérer les authorships avec rôles fusionnés
    position = 0
    for key, info in person_roles.items():
        source_person_id = upsert_source_author(cur, info["person"])
        if not source_person_id:
            continue

        roles = merge_roles([info["roles"]])
        is_author = "author" in roles

        author_full_name = (
            info["person"].get("prenom", "") + " " + info["person"].get("nom", "")
        ).strip()

        cur.execute(
            """
            INSERT INTO source_authorships
                (source, source_publication_id, source_person_id, author_position,
                 author_name_normalized, roles,
                 raw_author_name)
            VALUES ('theses', %s, %s, %s, normalize_name_form(%s), %s, %s)
            ON CONFLICT (source_publication_id, source_person_id) DO UPDATE SET
                roles = EXCLUDED.roles,
                author_name_normalized = EXCLUDED.author_name_normalized,
                raw_author_name = EXCLUDED.raw_author_name
            RETURNING id
        """,
            (
                source_publication_id,
                source_person_id,
                position if is_author else None,
                author_full_name,
                roles,
                author_full_name,
            ),
        )
        row = cur.fetchone()
        sa_id = row[0] if isinstance(row, tuple) else row["id"]

        if addr_parts:
            link_addresses(cur, sa_id, addr_parts)
        if is_author:
            position += 1


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(cur, row: dict) -> bool:
    """Traite une thèse du staging."""
    staging_id = row["id"]
    theses_id = row["source_id"]
    these = row["raw_data"]

    try:
        title = these.get("titrePrincipal")
        if not title:
            logger.warning(f"Thèse {theses_id} sans titre — skip")
            return False

        # Métadonnées de publication (stockées sur source_publications)
        pub_meta = extract_pub_metadata(these)

        # Chercher une publication existante (sans créer)
        publication_id = None

        # Idempotence : réutiliser le publication_id existant
        cur.execute(
            "SELECT publication_id FROM source_publications WHERE source = 'theses' AND source_id = %s",
            (theses_id,),
        )
        existing_doc = cur.fetchone()
        if existing_doc and existing_doc["publication_id"]:
            publication_id = existing_doc["publication_id"]

        # Recherche par DOI/NNT/titre (sans création)
        if not publication_id:
            publication_id = find_publication(cur, these)

        # Enrichir la publication existante si trouvée
        # (try_merge_by_doi gère les fusions DOI, refresh_from_sources recalcule après)
        if publication_id:
            publication_id = try_merge_by_doi(cur, publication_id, pub_meta["doi"])

        # Document (source_publications) — publication_id peut être NULL
        source_publication_id = insert_source_document(
            cur, these, staging_id, theses_id, publication_id, pub_meta
        )

        # Personnes et authorships (avec rôles)
        process_persons(cur, these, source_publication_id)

        # Recalcul complet des métadonnées depuis toutes les sources
        if publication_id:
            refresh_from_sources(cur, publication_id)
            _update_thesis_meta(cur, publication_id, these)

        mark_staging_done(cur, staging_id)

        return True

    except Exception as e:
        logger.error(f"Erreur sur {theses_id}: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Normalisation theses.fr → tables structurées")
    parser.add_argument("--limit", type=int, help="Nombre max de thèses à traiter")
    parser.add_argument("--reset", action="store_true", help="Remettre processed=FALSE")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if args.reset:
            cur.execute("UPDATE staging SET processed = FALSE WHERE source = 'theses'")
            count = cur.rowcount
            conn.commit()
            logger.info(f"Reset : {count} thèses remises à processed=FALSE")
            return

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM staging WHERE source = 'theses' AND processed = FALSE"
        )
        total = cur.fetchone()["cnt"]
        logger.info(f"=== Normalisation theses.fr : {total} thèses à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = min(args.limit or total, total)
        logger.info(f"Traitement de {limit} thèses")

        cur.execute(
            """
            SELECT id, source_id, doi, raw_data
            FROM staging
            WHERE source = 'theses' AND processed = FALSE
            ORDER BY id
            LIMIT %s
        """,
            (limit,),
        )

        rows = cur.fetchall()
        processed = 0
        errors = 0

        for row in rows:
            try:
                if process_work(cur, row):
                    processed += 1
            except Exception:
                conn.rollback()
                errors += 1
                continue

            if processed % args.batch_size == 0 and processed > 0:
                conn.commit()
                logger.info(f"  {processed}/{limit} traités...")

        conn.commit()

        logger.info("\n=== Terminé ===")
        logger.info(f"Traités avec succès : {processed}")
        logger.info(f"Erreurs : {errors}")

        cur.execute("SELECT COUNT(*) AS cnt FROM source_publications WHERE source = 'theses'")
        logger.info(f"  source_publications (theses) : {cur.fetchone()['cnt']}")
        cur.execute("SELECT COUNT(*) AS cnt FROM source_persons WHERE source = 'theses'")
        logger.info(f"  source_persons (theses) : {cur.fetchone()['cnt']}")
        cur.execute("SELECT COUNT(*) AS cnt FROM source_authorships WHERE source = 'theses'")
        logger.info(f"  source_authorships (theses) : {cur.fetchone()['cnt']}")

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
