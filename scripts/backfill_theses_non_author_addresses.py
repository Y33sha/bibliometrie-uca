#!/usr/bin/env python3
"""
Backfill : copie les adresses des auteurs de thèses vers les rôles non-auteur
(directeurs, rapporteurs, jury) de la même thèse.

Usage:
    python scripts/backfill_theses_non_author_addresses.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_connection
from utils.log import setup_logger

log = setup_logger("backfill_theses_addresses", os.path.join(os.path.dirname(__file__), "../processing/logs"))


def main():
    conn = get_connection()
    cur = conn.cursor()

    # Pour chaque authorship thèse non-auteur sans adresses,
    # copier les liens adresses de l'auteur de la même publication
    cur.execute("""
        INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
        SELECT sa_target.id, saa_author.address_id
        FROM source_authorships sa_target
        JOIN source_publications sd ON sd.id = sa_target.source_publication_id
        JOIN source_authorships sa_author
            ON sa_author.source_publication_id = sa_target.source_publication_id
            AND sa_author.source = 'theses'
            AND sa_author.roles && ARRAY['author']::text[]
        JOIN source_authorship_addresses saa_author
            ON saa_author.source_authorship_id = sa_author.id
        WHERE sa_target.source = 'theses'
          AND NOT (sa_target.roles && ARRAY['author']::text[])
          AND NOT EXISTS (
              SELECT 1 FROM source_authorship_addresses saa
              WHERE saa.source_authorship_id = sa_target.id
          )
        ON CONFLICT (source_authorship_id, address_id) DO NOTHING
    """)
    linked = cur.rowcount
    conn.commit()
    log.info("%d liens adresse créés pour les rôles non-auteur des thèses", linked)

    conn.close()


if __name__ == "__main__":
    main()
