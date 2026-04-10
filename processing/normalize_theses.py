"""
Normalisation des données theses.fr : staging → tables structurées.

Usage:
    python normalize_theses.py              # traiter tous les works non traités
    python normalize_theses.py --limit 100  # traiter N works (pour test)
    python normalize_theses.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publications                (table de vérité)
    source_documents            (source='theses')
    source_authors              (source='theses')
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
import sys
import time

from psycopg2.extras import Json, RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from services.publications import find_or_create, find_thesis_by_title, _enrich, update_sources
from utils.log import setup_logger
from utils.normalize import normalize_text, normalize_name
from utils.names import names_compatible
from utils.authorship_roles import THESES_FIELD_ROLES, merge_roles

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
    cur.execute("""
        SELECT sa.last_name, sa.first_name
        FROM source_authorships sas
        JOIN source_documents sd ON sd.id = sas.source_document_id
        JOIN source_authors sa ON sa.id = sas.source_author_id
        WHERE sd.publication_id = %s
          AND 'author' = ANY(sas.roles)
        ORDER BY sd.id, sas.author_position
        LIMIT 1
    """, (pub_id,))
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


def find_or_insert_publication(cur, these: dict) -> tuple[int | None, bool]:
    """Trouve ou crée la publication pour une thèse.

    Déduplication en 3 étapes :
    1. Par DOI ou NNT (via find_or_create standard)
    2. Par titre normalisé + année + compatibilité auteur (spécifique thèses)
    3. Création
    """
    title = these.get("titrePrincipal")
    if not title:
        return None, False

    status = these.get("status")
    doc_type = "ongoing_thesis" if status == "enCours" else "thesis"

    # Année : depuis dateSoutenance ou datePremiereInscriptionDoctorat
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
    nnt = these.get("nnt")
    lookup_doi = doi or nnt
    title_norm = normalize_text(title)

    # 1. Chercher par DOI/NNT (sans créer)
    pub_id, is_new = find_or_create(
        cur, title=title, title_normalized=title_norm,
        pub_year=pub_year, doc_type=doc_type, doi=lookup_doi,
        allow_create=False)
    if pub_id:
        return pub_id, False

    # 2. Dédup spécifique thèses : titre + année + auteur compatible
    if pub_year and title_norm:
        candidates = find_thesis_by_title(cur, title_norm, pub_year)
        if candidates:
            author = _extract_thesis_author(these)
            for cand in candidates:
                if not author or _thesis_author_compatible(cur, cand.id, author):
                    # Match trouvé → enrichir
                    _enrich(cur, cand.id, doi=lookup_doi, doc_type=doc_type)
                    return cand.id, False

    # 3. Créer
    return find_or_create(
        cur, title=title, title_normalized=title_norm,
        pub_year=pub_year, doc_type=doc_type, doi=lookup_doi)


# =============================================================
# SOURCE DOCUMENTS
# =============================================================

def insert_source_document(cur, these: dict, staging_id: int,
                           theses_id: str, publication_id: int | None) -> int:
    """Crée/retrouve l'entrée source_documents pour theses.fr."""
    title = these.get("titrePrincipal") or ""
    status = these.get("status")
    doc_type = "ongoing_thesis" if status == "enCours" else "thesis"

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

    cur.execute("""
        INSERT INTO source_documents
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id)
        VALUES ('theses', %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_documents.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, source_documents.doc_type)
        RETURNING id
    """, (theses_id, doi, title, pub_year, doc_type, publication_id, staging_id))
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
        cur.execute("""
            INSERT INTO source_authors
                (source, source_id, full_name, last_name, first_name, idref)
            VALUES ('theses', %s, %s, %s, %s, %s)
            ON CONFLICT (source, source_id) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                idref = COALESCE(source_authors.idref, EXCLUDED.idref)
            RETURNING id
        """, (ppn, full_name, nom, prenom, ppn))
        return cur.fetchone()["id"]

    # Sans PPN : dédup par nom exact
    cur.execute("""
        SELECT id FROM source_authors
        WHERE source = 'theses'
          AND source_id LIKE 'nokey-%%'
          AND full_name = %s
          AND first_name IS NOT DISTINCT FROM %s
        LIMIT 1
    """, (full_name, prenom))
    row = cur.fetchone()
    if row:
        return row["id"]

    # Nouveau sans identifiant
    cur.execute("""
        INSERT INTO source_authors
            (source, source_id, full_name, last_name, first_name)
        VALUES ('theses', 'nokey-' || nextval('source_authors_id_seq'), %s, %s, %s)
        RETURNING id
    """, (full_name, nom, prenom))
    return cur.fetchone()["id"]


# =============================================================
# SOURCE AUTHORSHIPS
# =============================================================

def process_persons(cur, these: dict, source_document_id: int):
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
    raw_affiliations = [p["nom"] for p in partenaires if p.get("nom")] or None

    # Insérer les authorships avec rôles fusionnés
    position = 0
    for key, info in person_roles.items():
        source_author_id = upsert_source_author(cur, info["person"])
        if not source_author_id:
            continue

        roles = merge_roles([info["roles"]])
        is_author = "author" in roles

        cur.execute("""
            INSERT INTO source_authorships
                (source, source_document_id, source_author_id, author_position,
                 author_name_normalized, roles, in_perimeter, raw_affiliations)
            VALUES ('theses', %s, %s, %s, normalize_name_form(%s), %s, %s, %s)
            ON CONFLICT (source_document_id, source_author_id) DO UPDATE SET
                roles = EXCLUDED.roles,
                author_name_normalized = EXCLUDED.author_name_normalized,
                in_perimeter = EXCLUDED.in_perimeter,
                raw_affiliations = EXCLUDED.raw_affiliations
        """, (source_document_id, source_author_id,
              position if is_author else None,
              info["person"].get("prenom", "") + " " + info["person"].get("nom", ""),
              roles, is_author,
              Json(raw_affiliations) if is_author and raw_affiliations else None))
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

        # Idempotence : si source_documents a déjà cette thèse avec un publication_id,
        # le réutiliser
        cur.execute(
            "SELECT publication_id FROM source_documents WHERE source = 'theses' AND source_id = %s",
            (theses_id,))
        existing_doc = cur.fetchone()
        if existing_doc and existing_doc["publication_id"]:
            publication_id = existing_doc["publication_id"]
            # Re-traitement : enrichir (ex: ongoing_thesis → thesis après soutenance)
            status = these.get("status")
            doc_type = "ongoing_thesis" if status == "enCours" else "thesis"
            doi = these.get("doi") or these.get("nnt")
            _enrich(cur, publication_id, doi=doi, doc_type=doc_type)
        else:
            publication_id, _ = find_or_insert_publication(cur, these)

        if not publication_id:
            logger.warning(f"Impossible d'insérer {theses_id} — échec publication")
            return False

        # Document
        source_document_id = insert_source_document(
            cur, these, staging_id, theses_id, publication_id
        )
        update_sources(cur, publication_id)

        # Personnes et authorships (avec rôles)
        process_persons(cur, these, source_document_id)

        cur.execute(
            "UPDATE staging SET processed = TRUE WHERE id = %s",
            (staging_id,))

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

        cur.execute("SELECT COUNT(*) AS cnt FROM staging WHERE source = 'theses' AND processed = FALSE")
        total = cur.fetchone()["cnt"]
        logger.info(f"=== Normalisation theses.fr : {total} thèses à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = min(args.limit or total, total)
        logger.info(f"Traitement de {limit} thèses")

        cur.execute("""
            SELECT id, source_id, doi, raw_data
            FROM staging
            WHERE source = 'theses' AND processed = FALSE
            ORDER BY id
            LIMIT %s
        """, (limit,))

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

        logger.info(f"\n=== Terminé ===")
        logger.info(f"Traités avec succès : {processed}")
        logger.info(f"Erreurs : {errors}")

        cur.execute("SELECT COUNT(*) AS cnt FROM source_documents WHERE source = 'theses'")
        logger.info(f"  source_documents (theses) : {cur.fetchone()['cnt']}")
        cur.execute("SELECT COUNT(*) AS cnt FROM source_authors WHERE source = 'theses'")
        logger.info(f"  source_authors (theses) : {cur.fetchone()['cnt']}")
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
