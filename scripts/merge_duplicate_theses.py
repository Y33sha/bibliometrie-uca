"""
Fusion rétroactive des thèses en doublon.

Critères de fusion :
- Même title_normalized + même pub_year
- doc_type IN ('thesis', 'ongoing_thesis')
- Auteur unique (role='author') avec noms compatibles entre les doublons

Usage:
    python scripts/merge_duplicate_theses.py              # dry-run
    python scripts/merge_duplicate_theses.py --apply       # appliquer
"""

import argparse
import os

from psycopg2.extras import RealDictCursor

from db.connection import get_connection
from application.publications import merge_publications
from infrastructure.log import setup_logger
from domain.names import names_compatible
from domain.normalize import normalize_name

logger = setup_logger(
    "merge_dup_theses", os.path.join(os.path.dirname(__file__), "../processing/logs")
)


def _name_tokens_match(ln1, fn1, ln2, fn2):
    """Fallback : les tokens du nom complet sont les mêmes (gère les particules)."""
    tokens_a = set(f"{ln1} {fn1}".split())
    tokens_b = set(f"{ln2} {fn2}".split())
    return tokens_a == tokens_b and len(tokens_a) >= 2


def find_duplicate_groups(cur):
    """Trouve les groupes de thèses avec même titre normalisé + année."""
    cur.execute("""
        SELECT title_normalized, pub_year,
               array_agg(id ORDER BY id) AS pub_ids
        FROM publications
        WHERE doc_type IN ('thesis', 'ongoing_thesis')
          AND title_normalized IS NOT NULL
          AND pub_year IS NOT NULL
        GROUP BY title_normalized, pub_year
        HAVING COUNT(*) > 1
        ORDER BY pub_year DESC, title_normalized
    """)
    return cur.fetchall()


def get_thesis_author(cur, pub_id):
    """Retourne (last_name, first_name) normalisés de l'auteur d'une thèse.

    Cherche dans source_authorships le rôle 'author'.
    Retourne None si pas d'auteur unique trouvé.
    """
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
        return None
    ln = normalize_name(row["last_name"] or "")
    fn = normalize_name(row["first_name"] or "")
    return (ln, fn) if ln else None


def choose_target(cur, pub_ids):
    """Choisit la publication cible (celle à garder).

    Priorité : celle avec DOI > celle avec le plus de source_publications > id le plus bas.
    """
    cur.execute(
        """
        SELECT p.id, p.doi,
               (SELECT COUNT(*) FROM source_publications sd WHERE sd.publication_id = p.id) AS sd_count
        FROM publications p
        WHERE p.id = ANY(%s)
        ORDER BY
            (p.doi IS NOT NULL) DESC,
            (SELECT COUNT(*) FROM source_publications sd WHERE sd.publication_id = p.id) DESC,
            p.id ASC
    """,
        (pub_ids,),
    )
    return cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description="Fusion rétroactive des thèses en doublon")
    parser.add_argument("--apply", action="store_true", help="Appliquer les fusions")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        groups = find_duplicate_groups(cur)
        logger.info(f"Groupes de doublons potentiels : {len(groups)}")

        merged_total = 0
        skipped = 0
        errors = 0

        for group in groups:
            title_norm = group["title_normalized"]
            pub_year = group["pub_year"]
            pub_ids = group["pub_ids"]

            # Collecter les auteurs de chaque publication
            authors = {}
            for pid in pub_ids:
                author = get_thesis_author(cur, pid)
                if author:
                    authors[pid] = author

            if not authors:
                skipped += 1
                continue

            # Vérifier la compatibilité des noms d'auteurs entre tous les doublons
            author_list = list(authors.items())
            all_compatible = True
            for i in range(len(author_list)):
                for j in range(i + 1, len(author_list)):
                    pid_a, (ln_a, fn_a) = author_list[i]
                    pid_b, (ln_b, fn_b) = author_list[j]
                    if not (
                        names_compatible(ln_a, fn_a, ln_b, fn_b)
                        or _name_tokens_match(ln_a, fn_a, ln_b, fn_b)
                    ):
                        all_compatible = False
                        break
                if not all_compatible:
                    break

            if not all_compatible:
                logger.info(
                    f'  SKIP ({pub_year}) "{title_norm[:70]}" '
                    f"— auteurs incompatibles : "
                    + ", ".join(f"{pid}={ln} {fn}" for pid, (ln, fn) in author_list)
                )
                skipped += 1
                continue

            # Choisir la cible et fusionner
            ranked = choose_target(cur, pub_ids)
            target = ranked[0]
            sources = ranked[1:]

            for source in sources:
                label = (
                    f"pub {source['id']}"
                    f"{' (doi=' + source['doi'] + ')' if source['doi'] else ''}"
                    f" → {target['id']}"
                    f"{' (doi=' + target['doi'] + ')' if target['doi'] else ''}"
                )

                if not args.apply:
                    logger.info(f"  DRY  {label}  [{pub_year}] {title_norm[:60]}")
                    merged_total += 1
                    continue

                try:
                    cur.execute("SAVEPOINT merge_thesis")
                    merge_publications(cur, target["id"], source["id"])
                    cur.execute("RELEASE SAVEPOINT merge_thesis")
                    logger.info(f"  MERGE {label}")
                    merged_total += 1
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT merge_thesis")
                    logger.error(f"  ERREUR {label}: {e}")
                    errors += 1

        if args.apply:
            conn.commit()

        logger.info("\n=== Résumé ===")
        logger.info(f"  Groupes analysés : {len(groups)}")
        logger.info(f"  Fusions {'appliquées' if args.apply else '(dry-run)'} : {merged_total}")
        logger.info(f"  Ignorés (auteurs incompatibles/absents) : {skipped}")
        logger.info(f"  Erreurs : {errors}")
        if not args.apply and merged_total:
            logger.info("\nDry-run — ajouter --apply pour appliquer.")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
