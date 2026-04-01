"""
Répare les fusions erronées de publications.

Détecte les publications ayant plusieurs hal_documents qui ne sont manifestement
pas la même publication (container/journal différent, ou DOIs distincts).
Pour chaque cas, garde le premier hal_document sur la publication existante et
crée de nouvelles publications pour les autres.

Usage:
    python processing/split_bad_merges.py [--dry-run]
"""

import sys, os, json, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg2
from psycopg2.extras import RealDictCursor
from config.settings import DB

HAL_DOCTYPE_MAP = {
    "ART": "article", "COMM": "conference_paper", "POSTER": "conference_paper",
    "OUV": "book", "COUV": "book_chapter", "DOUV": "book_chapter",
    "THESE": "thesis", "HDR": "thesis", "PREPRINT": "preprint",
    "UNDEFINED": "other", "OTHER": "other", "REPORT": "report",
    "MEM": "thesis", "LECTURE": "other", "IMG": "other",
    "VIDEO": "other", "SON": "other", "MAP": "other", "SOFTWARE": "other",
}


def normalize_text(s: str | None) -> str | None:
    if not s:
        return None
    import unicodedata
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def get_container(raw: dict) -> str | None:
    """Extrait le container (journal ou ouvrage/conférence) du raw staging."""
    for key in ("journalTitle_s", "bookTitle_s", "conferenceTitle_s"):
        val = raw.get(key)
        if isinstance(val, list):
            val = val[0] if val else None
        if val:
            return val
    return None


def get_title(raw: dict) -> str | None:
    for key in ("title_s", "en_title_s", "fr_title_s"):
        val = raw.get(key)
        if isinstance(val, list):
            val = val[0] if val else None
        if val:
            return val
    return None


def docs_are_same(a: dict, b: dict) -> bool:
    """Heuristique : deux hal_documents pointent-ils vers la même vraie publication ?"""
    # DOIs différents non-null → différents
    doi_a = a.get("doi")
    doi_b = b.get("doi")
    if doi_a and doi_b and doi_a != doi_b:
        return False

    # Containers différents → différents
    cont_a = normalize_text(get_container(a))
    cont_b = normalize_text(get_container(b))
    if cont_a and cont_b and cont_a != cont_b:
        return False

    # Même DOI non-null → même publication
    if doi_a and doi_b and doi_a == doi_b:
        return True

    # Même container et même titre → probablement la même
    title_a = normalize_text(get_title(a))
    title_b = normalize_text(get_title(b))
    if cont_a and cont_b and cont_a == cont_b and title_a == title_b:
        return True

    # Pas de container de part et d'autre ET pas de DOI → incertain,
    # considérer comme différents (précaution)
    if not cont_a and not cont_b and not doi_a and not doi_b:
        return False

    # Un a un container, l'autre non → différents
    if bool(cont_a) != bool(cont_b):
        return False

    return False


def group_docs(docs: list[dict]) -> list[list[dict]]:
    """Regroupe les documents en clusters de 'même publication'."""
    groups: list[list[dict]] = []
    for doc in docs:
        placed = False
        for group in groups:
            if docs_are_same(group[0], doc):
                group.append(doc)
                placed = True
                break
        if not placed:
            groups.append([doc])
    return groups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche ce qui serait fait sans modifier la BDD")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Trouver les publications avec >1 hal_document
    cur.execute("""
        SELECT hd.publication_id, COUNT(*) as n
        FROM hal_documents hd
        WHERE hd.publication_id IS NOT NULL
        GROUP BY hd.publication_id
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC
    """)
    candidates = cur.fetchall()
    print(f"Publications avec >1 hal_document : {len(candidates)}")

    total_splits = 0
    total_new_pubs = 0

    for cand in candidates:
        pub_id = cand["publication_id"]

        # Récupérer les hal_documents avec leur staging raw_data
        cur.execute("""
            SELECT hd.id as hd_id, hd.halid, hd.doi, hd.title, hd.pub_year,
                   hd.doc_type, hd.staging_id,
                   sh.raw_data
            FROM hal_documents hd
            LEFT JOIN staging_hal sh ON sh.id = hd.staging_id
            WHERE hd.publication_id = %s
            ORDER BY hd.id
        """, (pub_id,))
        docs = cur.fetchall()

        # Construire les raw dicts pour comparaison
        for d in docs:
            if d["raw_data"] is None:
                # Pas de staging — on construit un pseudo-raw
                d["_raw"] = {"doi": d["doi"]}
            elif isinstance(d["raw_data"], str):
                d["_raw"] = json.loads(d["raw_data"])
            else:
                d["_raw"] = d["raw_data"]
            d["_raw"]["doi"] = d["doi"]  # assurer cohérence

        groups = group_docs([{"doc": d, **d["_raw"]} for d in docs])

        if len(groups) <= 1:
            # Tous les docs appartiennent à la même publication — OK
            continue

        # Il faut éclater : le premier groupe garde pub_id, les autres
        # reçoivent une nouvelle publication chacun
        total_splits += 1
        keep_group = groups[0]
        split_groups = groups[1:]

        keep_halids = [d["doc"]["halid"] for d in keep_group]
        pub_title_short = (docs[0]["title"] or "")[:50]

        if args.dry_run:
            print(f"\n  pub {pub_id} ({pub_title_short}): "
                  f"{len(groups)} groupes, {len(docs)} docs")
            print(f"    Garder sur pub {pub_id}: {keep_halids}")
            for gi, g in enumerate(split_groups):
                halids = [d["doc"]["halid"] for d in g]
                container = get_container(g[0]) or "(aucun)"
                print(f"    Nouveau groupe {gi+1}: {halids} | container={container}")
            continue

        for g in split_groups:
            ref_doc = g[0]["doc"]
            raw = ref_doc["_raw"]

            # Créer nouvelle publication à partir du staging
            title = get_title(raw) or ref_doc["title"]
            title_norm = normalize_text(title)
            pub_year = raw.get("producedDateY_i") or ref_doc["pub_year"]
            doi = ref_doc["doi"]
            raw_doc_type = ref_doc["doc_type"] or "other"
            doc_type = HAL_DOCTYPE_MAP.get(raw_doc_type, raw_doc_type)
            if doc_type not in ("article", "review", "conference_paper", "book",
                                "book_chapter", "thesis", "preprint", "editorial",
                                "report", "other"):
                doc_type = "other"
            oa_status = "green" if raw.get("openAccess_bool") else "closed"
            container_title = get_container(raw)

            # Chercher journal_id via container
            journal_id = None
            journal_title = raw.get("journalTitle_s")
            if isinstance(journal_title, list):
                journal_title = journal_title[0] if journal_title else None
            if journal_title:
                jt_norm = normalize_text(journal_title)
                cur.execute(
                    "SELECT id FROM journals WHERE title_normalized = %s LIMIT 1",
                    (jt_norm,)
                )
                jr = cur.fetchone()
                if jr:
                    journal_id = jr["id"]

            # Vérifier si un DOI existe déjà (ne pas créer de doublon)
            new_pub_id = None
            if doi:
                cur.execute("SELECT id FROM publications WHERE lower(doi) = lower(%s)", (doi,))
                existing = cur.fetchone()
                if existing:
                    new_pub_id = existing["id"]

            if not new_pub_id:
                cur.execute("""
                    INSERT INTO publications
                        (title, title_normalized, doc_type, pub_year, doi,
                         oa_status, journal_id, container_title)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (title, title_norm, doc_type, pub_year, doi,
                      oa_status, journal_id, container_title))
                new_pub_id = cur.fetchone()["id"]
                total_new_pubs += 1

            # Rattacher les hal_documents du groupe à la nouvelle pub
            hd_ids = [d["doc"]["hd_id"] for d in g]
            for hd_id in hd_ids:
                cur.execute(
                    "UPDATE hal_documents SET publication_id = %s WHERE id = %s",
                    (new_pub_id, hd_id)
                )

            # Rattacher les authorships liées
            for hd_id in hd_ids:
                cur.execute("""
                    UPDATE authorships a
                    SET publication_id = %s, updated_at = now()
                    WHERE a.hal_authorship_id IN (
                        SELECT has.id FROM hal_authorships has
                        WHERE has.hal_document_id = %s
                    )
                    AND a.publication_id = %s
                """, (new_pub_id, hd_id, pub_id))

            # Déplacer les openalex_documents dont le DOI match un hal_doc du groupe
            group_dois = [d["doc"]["doi"] for d in g if d["doc"]["doi"]]
            if group_dois:
                cur.execute("""
                    UPDATE openalex_documents SET publication_id = %s
                    WHERE publication_id = %s AND doi = ANY(%s)
                    RETURNING id, openalex_id
                """, (new_pub_id, pub_id, group_dois))
                moved_oa = cur.fetchall()
                # Déplacer aussi les authorships OA correspondantes
                for oa_row in moved_oa:
                    cur.execute("""
                        UPDATE authorships a
                        SET publication_id = %s, updated_at = now()
                        WHERE a.openalex_authorship_id IN (
                            SELECT oas.id FROM openalex_authorships oas
                            WHERE oas.openalex_document_id = %s
                        )
                        AND a.publication_id = %s
                    """, (new_pub_id, oa_row["id"], pub_id))

            halids = [d["doc"]["halid"] for d in g]
            oa_moved = [r["openalex_id"] for r in moved_oa] if group_dois else []
            extra = f" + OA {oa_moved}" if oa_moved else ""
            print(f"  pub {pub_id} → new pub {new_pub_id}: {halids}{extra}")

    if not args.dry_run:
        conn.commit()
        print(f"\n{'='*50}")
        print(f"Publications éclatées : {total_splits}")
        print(f"Nouvelles publications créées : {total_new_pubs}")
    else:
        print(f"\n{'='*50}")
        print(f"[DRY RUN] Publications à éclater : {total_splits}")

    conn.close()


if __name__ == "__main__":
    main()
