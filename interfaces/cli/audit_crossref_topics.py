"""Audit one-shot des champs ontologiques exposés par l'API CrossRef.

Phase 3 du chantier sujets / mots-clés : on ré-interroge CrossRef sur un
échantillon de DOIs et on inventorie les clés top-level rencontrées + les
champs candidats pour des sujets / mots-clés / topics au-delà de `subject[]`
(déjà extrait par `normalize_crossref.py`).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
from collections import Counter

import httpx
import psycopg
from psycopg.rows import dict_row

from infrastructure.app_config import get_crossref_email
from infrastructure.settings import settings

SAMPLE_SIZE = 100
USER_AGENT = "BibliometrieUCA-audit/1.0 (mailto:{email})"


def fetch_dois(n: int) -> list[str]:
    """Échantillon aléatoire de DOIs CrossRef-sourcés en base."""
    with (
        psycopg.connect(
            dbname=settings.db_name,
            user=settings.db_user,
            host=settings.db_host,
            port=settings.db_port,
            password=settings.db_password or None,
            row_factory=dict_row,
        ) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            "SELECT source_id FROM source_publications "
            "WHERE source = 'crossref' AND publication_id IS NOT NULL "
            "ORDER BY random() LIMIT %s",
            (n,),
        )
        return [r["source_id"] for r in cur.fetchall()]


def get_email() -> str:
    with (
        psycopg.connect(
            dbname=settings.db_name,
            user=settings.db_user,
            host=settings.db_host,
            port=settings.db_port,
            password=settings.db_password or None,
            row_factory=dict_row,
        ) as conn,
        conn.cursor() as cur,
    ):
        return get_crossref_email(cur)


def fetch_one(client: httpx.Client, doi: str) -> dict | None:
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/()')}"
    try:
        resp = client.get(url, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"  ! {doi}: {e}", file=sys.stderr)
        return None
    return resp.json().get("message")


def main() -> None:
    email = get_email()
    headers = {"User-Agent": USER_AGENT.format(email=email)}
    dois = fetch_dois(SAMPLE_SIZE)
    print(f"Audit sur {len(dois)} DOIs CrossRef.\n")

    key_counter: Counter[str] = Counter()
    # Champs candidats topics / sujets / mots-clés au-delà de `subject`.
    # On capture leur valeur sur 3 échantillons par champ pour inspection.
    subject_stats = {"present_empty": 0, "present_non_empty": 0, "absent": 0}
    candidates: dict[str, list[tuple[str, object]]] = {
        "subject": [],
        "concept": [],
        "categories": [],
        "category-name": [],
        "tags": [],
        "groups": [],
        "topic": [],
        "topics": [],
        "keyword": [],
        "keywords": [],
        "discipline": [],
        "subject-category": [],
        "scheme": [],
        "tdm-mining": [],  # text and data mining
        "type": [],  # juste pour vérifier que la fetch marche
    }

    with httpx.Client(headers=headers) as client:
        for i, doi in enumerate(dois, 1):
            msg = fetch_one(client, doi)
            if msg is None:
                continue
            for key in msg:
                key_counter[key] += 1
            # Statistique fine sur `subject` (déjà extrait par normalize_crossref).
            if "subject" not in msg:
                subject_stats["absent"] += 1
            elif msg["subject"]:
                subject_stats["present_non_empty"] += 1
                if len(candidates["subject"]) < 5:
                    candidates["subject"].append((doi, msg["subject"]))
            else:
                subject_stats["present_empty"] += 1
            for cand in candidates:
                if cand == "subject":
                    continue
                if cand in msg and len(candidates[cand]) < 3:
                    candidates[cand].append((doi, msg[cand]))
            if i % 10 == 0:
                print(f"  {i}/{len(dois)}…", file=sys.stderr)
            time.sleep(0.1)  # polite pool

    print("\n=== Clés top-level rencontrées (fréquence sur l'échantillon) ===\n")
    for key, count in sorted(key_counter.items(), key=lambda kv: -kv[1]):
        print(f"  {count:3d}  {key}")

    print("\n=== Statistique sur le champ `subject` (déjà extrait) ===\n")
    for label, count in subject_stats.items():
        print(f"  {count:3d}  {label}")

    print("\n=== Échantillons pour les champs candidats topics/sujets ===\n")
    for cand, samples in candidates.items():
        if not samples:
            continue
        print(f"\n--- {cand} ({len(samples)} obs) ---")
        for doi, value in samples:
            print(f"  {doi}: {json.dumps(value, ensure_ascii=False)[:200]}")


if __name__ == "__main__":
    main()
