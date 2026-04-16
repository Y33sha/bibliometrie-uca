"""
Dédoublonnage des source_authorships et source_persons HAL en double.

Après une restructuration de la table source_persons, certains auteurs HAL
ont été recréés avec un source_id de format différent (person_id_ -> person_id_formId),
produisant des source_authorships en double pour le même (source_document, position).

Ce script en deux phases :

Phase 1 — Source_authorships en double :
  1. Détecte les groupes de doublons (même source_publication_id + author_position, source='hal')
  2. Fusionne chaque groupe : garde le plus récent (id max), transfère les champs
     non-null de l'ancien vers le nouveau si celui-ci est null
  3. Supprime les source_authorships obsolètes
  4. Supprime les source_persons devenus orphelins

Phase 2 — Source_authors en double (même hal_person_id) :
  Pour les source_persons HAL restants avec le même hal_person_id mais des ids différents
  (cas où les authorships n'étaient pas en double mais pointaient vers des auteurs distincts),
  migrer les source_authorships vers le nouveau, transférer les champs manquants,
  supprimer l'ancien.

Usage:
    python scripts/deduplicate_hal_source_authorships.py              # dry-run
    python scripts/deduplicate_hal_source_authorships.py --apply      # appliquer
"""

import argparse
import os
import sys

from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.log import setup_logger

logger = setup_logger("dedup_hal_sa", os.path.join(os.path.dirname(__file__), "../processing/logs"))

# Champs transférables de l'ancien source_authorship vers le nouveau (si nouveau est null)
SA_TRANSFER_FIELDS = [
    "in_perimeter", "excluded", "structure_ids", "source_struct_ids",
    "countries", "person_id", "author_name_normalized", "is_corresponding",
    "roles", "source_data", "authorship_id",
]

# Règles de résolution de conflits (les deux non-null et différents)
# "old" = garder la valeur de l'ancien, "new" = garder le nouveau, "true" = garder True
SA_CONFLICT_RULES = {
    "in_perimeter": "old",       # false est le default, l'ancien a la vraie valeur
    "is_corresponding": "new",   # false est le default, le nouveau a la vraie valeur (renseigné avec roles)
    "excluded": "true",          # si l'un des deux est exclu, c'est vrai
    "author_name_normalized": "new",  # dérivé du source_person_id, doit être cohérent avec le nouveau
}

# Champs transférables de l'ancien source_author vers le nouveau (si nouveau est null)
AUTHOR_TRANSFER_FIELDS = ["orcid", "idref", "person_id"]


def find_duplicate_groups(cur):
    """Trouve tous les groupes de source_authorships HAL en double."""
    cur.execute("""
        SELECT source_publication_id, author_position,
               array_agg(id ORDER BY id) AS sa_ids,
               array_agg(source_person_id ORDER BY id) AS author_ids
        FROM source_authorships
        WHERE source = 'hal'
        GROUP BY source_publication_id, author_position
        HAVING count(*) > 1
        ORDER BY source_publication_id, author_position
    """)
    return cur.fetchall()


def merge_source_authorships(cur, group, dry_run):
    """Fusionne un groupe de source_authorships.

    Garde le dernier (id max), transfère les champs null depuis les anciens.
    Retourne (keep_id, delete_ids, conflicts) où conflicts = {field: (old_val, new_val)}.
    """
    sa_ids = group["sa_ids"]
    keep_id = sa_ids[-1]  # id le plus grand = le plus récent
    delete_ids = sa_ids[:-1]

    # Lire toutes les lignes
    cur.execute(
        "SELECT * FROM source_authorships WHERE id = ANY(%s) ORDER BY id",
        (sa_ids,),
    )
    rows = cur.fetchall()
    keep_row = rows[-1]
    old_rows = rows[:-1]

    # Détecter les transferts et conflits
    transfers = {}
    conflicts = {}
    for field in SA_TRANSFER_FIELDS:
        if keep_row[field] is not None:
            # Le nouveau a une valeur : vérifier si un ancien diffère
            for old in old_rows:
                if old[field] is not None and old[field] != keep_row[field]:
                    rule = SA_CONFLICT_RULES.get(field)
                    if rule == "old":
                        transfers[field] = old[field]
                    elif rule == "true":
                        if old[field] is True:
                            transfers[field] = True
                    elif rule == "new":
                        pass  # on garde la valeur du nouveau, rien à faire
                    else:
                        # Pas de règle : signaler le conflit
                        conflicts[field] = (old[field], keep_row[field])
                    break
        else:
            # Le nouveau est null : chercher une valeur dans les anciens
            for old in old_rows:
                if old[field] is not None:
                    transfers[field] = old[field]
                    break

    if transfers and not dry_run:
        set_clause = ", ".join(f"{f} = %({f})s" for f in transfers)
        transfers["id"] = keep_id
        cur.execute(
            f"UPDATE source_authorships SET {set_clause} WHERE id = %(id)s",
            transfers,
        )

    if not dry_run:
        # Supprimer les éventuelles source_authorship_addresses liées aux anciens
        cur.execute(
            "DELETE FROM source_authorship_addresses WHERE source_authorship_id = ANY(%s)",
            (delete_ids,),
        )
        cur.execute(
            "DELETE FROM source_authorships WHERE id = ANY(%s)",
            (delete_ids,),
        )

    return keep_id, delete_ids, conflicts


def merge_source_persons(cur, keep_author_id, old_author_ids, dry_run):
    """Fusionne les source_persons : transfère les champs manquants, supprime les anciens."""
    cur.execute("SELECT * FROM source_persons WHERE id = %s", (keep_author_id,))
    keep = cur.fetchone()

    transfers = {}
    for old_id in old_author_ids:
        cur.execute("SELECT * FROM source_persons WHERE id = %s", (old_id,))
        old = cur.fetchone()
        if not old:
            continue
        for field in AUTHOR_TRANSFER_FIELDS:
            if field not in transfers and keep[field] is None and old[field] is not None:
                transfers[field] = old[field]

    if transfers and not dry_run:
        set_clause = ", ".join(f"{f} = %({f})s" for f in transfers)
        transfers["id"] = keep_author_id
        cur.execute(
            f"UPDATE source_persons SET {set_clause} WHERE id = %(id)s",
            transfers,
        )

    # Supprimer les anciens source_persons s'ils n'ont plus de source_authorships
    if not dry_run:
        for old_id in old_author_ids:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM source_authorships WHERE source_person_id = %s)",
                (old_id,),
            )
            if not cur.fetchone()["exists"]:
                cur.execute("DELETE FROM source_persons WHERE id = %s", (old_id,))


def find_duplicate_authors(cur):
    """Trouve les groupes de source_persons HAL avec le même hal_person_id."""
    cur.execute("""
        SELECT (source_ids->>'hal_person_id')::int AS hal_person_id,
               array_agg(id ORDER BY id) AS author_ids
        FROM source_persons
        WHERE source = 'hal' AND source_ids->>'hal_person_id' IS NOT NULL
        GROUP BY (source_ids->>'hal_person_id')::int
        HAVING count(*) > 1
        ORDER BY (source_ids->>'hal_person_id')::int
    """)
    return cur.fetchall()


def merge_duplicate_authors(cur, group, dry_run):
    """Fusionne un groupe de source_persons avec le même hal_person_id.

    Garde le plus récent (id max), migre les source_authorships, transfère
    les champs manquants, supprime les anciens.
    Retourne le nombre d'anciens supprimés.
    """
    author_ids = group["author_ids"]
    keep_id = author_ids[-1]
    old_ids = author_ids[:-1]

    # Migrer les source_authorships des anciens vers le nouveau
    # Supprimer celles qui créeraient un doublon (source_publication_id, source_person_id)
    if not dry_run:
        for old_id in old_ids:
            # Supprimer les authorships qui existent déjà pour le nouveau source_author
            cur.execute("""
                DELETE FROM source_authorship_addresses
                WHERE source_authorship_id IN (
                    SELECT sa_old.id
                    FROM source_authorships sa_old
                    JOIN source_authorships sa_new
                      ON sa_new.source_publication_id = sa_old.source_publication_id
                     AND sa_new.source_person_id = %s
                    WHERE sa_old.source_person_id = %s
                )
            """, (keep_id, old_id))
            cur.execute("""
                DELETE FROM source_authorships sa_old
                USING source_authorships sa_new
                WHERE sa_old.source_person_id = %s
                  AND sa_new.source_person_id = %s
                  AND sa_new.source_publication_id = sa_old.source_publication_id
            """, (old_id, keep_id))
            # Migrer les restantes
            cur.execute(
                "UPDATE source_authorships SET source_person_id = %s WHERE source_person_id = %s",
                (keep_id, old_id),
            )

    # Transférer les champs manquants et supprimer
    merge_source_persons(cur, keep_id, old_ids, dry_run)

    deleted = 0
    if not dry_run:
        for old_id in old_ids:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM source_authorships WHERE source_person_id = %s)",
                (old_id,),
            )
            if not cur.fetchone()["exists"]:
                cur.execute("DELETE FROM source_persons WHERE id = %s", (old_id,))
                deleted += 1
    else:
        deleted = len(old_ids)

    return deleted


def run(dry_run=True):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ── Phase 1 : source_authorships en double ──
            logger.info("=== Phase 1 : source_authorships en double ===")
            groups = find_duplicate_groups(cur)
            logger.info("Groupes de doublons : %d", len(groups))

            all_conflicts = {}
            sa_deleted = 0
            authors_to_merge = {}  # keep_author_id -> set(old_author_ids)

            for group in groups:
                keep_id, delete_ids, conflicts = merge_source_authorships(
                    cur, group, dry_run
                )
                sa_deleted += len(delete_ids)
                if conflicts:
                    all_conflicts[
                        (group["source_publication_id"], group["author_position"])
                    ] = conflicts

                # Collecter les fusions d'auteurs
                keep_author = group["author_ids"][-1]
                old_authors = set(group["author_ids"][:-1]) - {keep_author}
                if old_authors:
                    existing = authors_to_merge.setdefault(keep_author, set())
                    existing.update(old_authors)

            # Rapport conflits
            conflict_fields = {}
            for key, cfl in all_conflicts.items():
                for field in cfl:
                    conflict_fields[field] = conflict_fields.get(field, 0) + 1

            if conflict_fields:
                logger.info("Conflits (champs differents non-null dans les deux) :")
                for field, count in sorted(conflict_fields.items(), key=lambda x: -x[1]):
                    logger.info("  %-25s : %d cas", field, count)

            logger.info(
                "Source_authorships : %d supprimés, %d groupes avec conflits",
                sa_deleted,
                len(all_conflicts),
            )

            # Fusion des source_persons orphelins (phase 1)
            authors_deleted_p1 = 0
            for keep_id, old_ids in authors_to_merge.items():
                merge_source_persons(cur, keep_id, list(old_ids), dry_run)
                if not dry_run:
                    for old_id in old_ids:
                        cur.execute(
                            "SELECT EXISTS(SELECT 1 FROM source_persons WHERE id = %s)",
                            (old_id,),
                        )
                        if not cur.fetchone()["exists"]:
                            authors_deleted_p1 += 1

            logger.info(
                "Source_authors (phase 1) : %d a fusionner, %d supprimés",
                len(authors_to_merge),
                authors_deleted_p1,
            )

            # ── Phase 2 : source_persons en double (même hal_person_id) ──
            logger.info("=== Phase 2 : source_persons en double (meme hal_person_id) ===")
            author_groups = find_duplicate_authors(cur)
            logger.info("Groupes de source_persons en double : %d", len(author_groups))

            authors_deleted_p2 = 0
            for group in author_groups:
                authors_deleted_p2 += merge_duplicate_authors(cur, group, dry_run)

            logger.info(
                "Source_authors (phase 2) : %d supprimés", authors_deleted_p2
            )

            if dry_run:
                logger.info("DRY-RUN -- aucune modification appliquée")
                conn.rollback()
            else:
                conn.commit()
                logger.info("Modifications appliquées avec succes")

    except Exception:
        conn.rollback()
        logger.exception("Erreur lors du dedoublonnage")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dédoublonnage source_authorships HAL")
    parser.add_argument("--apply", action="store_true", help="Appliquer les modifications")
    args = parser.parse_args()
    run(dry_run=not args.apply)
