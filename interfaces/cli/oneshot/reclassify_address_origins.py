# STATUS: oneshot (2026-11-04)
"""Reclasse l'origine du texte des adresses déjà classées, après passage de la règle « Nom (Pays) » avant la règle de la virgule.

Le script recalcule l'origine de chaque adresse et met à jour celles qui changent. Il affiche les passages d'une origine à l'autre et un échantillon par passage.

Usage :
    uv run python -m interfaces.cli.oneshot.reclassify_address_origins [--dry-run]
"""

import argparse
import json
from collections import Counter, defaultdict

from sqlalchemy import text

from domain.addresses.address_origin import AddressOrigin, address_origin
from infrastructure.db.engine import build_sync_engine
from pipeline.transformation.structures.address_origin import CHUNK_SIZE, load_referentials

_SAMPLE_SIZE = 15

_FETCH = text("""
    SELECT id, raw_text, normalized_text, origin::text AS origin, publication_count FROM addresses
    WHERE origin IS NOT NULL AND id > :after
    ORDER BY id LIMIT :limit
""")

_UPDATE = text("""
    UPDATE addresses a SET origin = CAST(t.origin AS address_origin)
    FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS t(id integer, origin text)
    WHERE a.id = t.id
""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="mesure sans écrire")
    args = parser.parse_args()

    transitions: Counter[tuple[str, str]] = Counter()
    publications: Counter[tuple[str, str]] = Counter()
    samples: dict[tuple[str, str], list[str]] = defaultdict(list)
    seen = 0
    with build_sync_engine().begin() as conn:
        referentials = load_referentials(conn)
        after_id = 0
        while rows := conn.execute(_FETCH, {"after": after_id, "limit": CHUNK_SIZE}).all():
            after_id = rows[-1].id
            seen += len(rows)
            changes = []
            for r in rows:
                origin = address_origin(r.raw_text, r.normalized_text, referentials)
                if origin != AddressOrigin(r.origin):
                    key = (r.origin, origin.value)
                    transitions[key] += 1
                    publications[key] += r.publication_count or 0
                    samples[key].append(r.raw_text)
                    changes.append({"id": r.id, "origin": origin.value})
            if changes and not args.dry_run:
                conn.execute(_UPDATE, {"payload": json.dumps(changes)})

    print(f"{seen} adresses relues, {transitions.total()} reclassées")
    for key, count in transitions.most_common():
        print(f"\n{key[0]} → {key[1]} : {count} adresses, {publications[key]} publications")
        step = max(1, len(samples[key]) // _SAMPLE_SIZE)
        for raw_text in samples[key][::step][:_SAMPLE_SIZE]:
            print(f"  {raw_text[:140]}")
    if args.dry_run:
        print("\n(dry-run : rien n'est écrit)")


if __name__ == "__main__":
    main()
