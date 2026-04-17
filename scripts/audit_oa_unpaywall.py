"""
Audit : compare le statut OA en base (principalement OpenAlex) avec Unpaywall.

Usage:
    python analysis/audit_oa_unpaywall.py [--limit N]
    python analysis/audit_oa_unpaywall.py --dry-run    # rapport CSV sans modifier la base
"""

import os, time, argparse, csv
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from config.settings import settings

EMAIL = "laurent.le-coz@uca.fr"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}?email={email}"
REQUEST_DELAY = 0.12  # ~8 req/s

OA_MAP = {
    "gold": "gold",
    "hybrid": "hybrid",
    "bronze": "bronze",
    "green": "green",
    "closed": "closed",
}


def fetch_unpaywall(doi: str) -> str | None:
    """Interroge Unpaywall et retourne le statut OA mappé, ou None si erreur."""
    try:
        r = requests.get(
            UNPAYWALL_URL.format(doi=doi, email=EMAIL),
            timeout=10,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        raw = data.get("oa_status", "")
        return OA_MAP.get(raw)
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Limiter le nombre de DOI")
    parser.add_argument("--dry-run", action="store_true",
                        help="Rapport CSV uniquement, sans modifier la base")
    args = parser.parse_args()

    conn = psycopg2.connect(**settings.db_args)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Récupérer les pubs avec DOI, statut connu, et source OpenAlex
    query = """
        SELECT p.id, p.doi, p.oa_status::text as oa_status
        FROM publications p
        WHERE p.doi IS NOT NULL
          AND p.oa_status != 'unknown'
          AND EXISTS (SELECT 1 FROM source_publications sd
                      WHERE sd.publication_id = p.id AND sd.source = 'openalex')
        ORDER BY p.id
    """
    if args.limit:
        query += f" LIMIT {args.limit}"
    cur.execute(query)
    pubs = cur.fetchall()
    total = len(pubs)
    print(f"Publications à auditer : {total}")

    # Audit
    report_path = os.path.join(os.path.dirname(__file__), "oa_audit_report.csv")
    matches = 0
    divergences = 0
    not_found = 0
    errors = 0
    updates = 0

    with open(report_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pub_id", "doi", "oa_current", "oa_unpaywall", "match"])

        for i, pub in enumerate(pubs):
            if i > 0 and i % 500 == 0:
                print(f"  {i}/{total} — {divergences} divergences, "
                      f"{matches} identiques, {not_found} non trouvés")

            time.sleep(REQUEST_DELAY)
            upw = fetch_unpaywall(pub["doi"])

            if upw is None:
                not_found += 1
                writer.writerow([pub["id"], pub["doi"], pub["oa_status"], "", "not_found"])
                continue

            is_match = upw == pub["oa_status"]
            if is_match:
                matches += 1
            else:
                divergences += 1
                if not args.dry_run:
                    cur.execute(
                        "UPDATE publications SET oa_status = %s::oa_type, "
                        "updated_at = now() WHERE id = %s",
                        (upw, pub["id"]),
                    )
                    updates += 1
                    if updates % 200 == 0:
                        conn.commit()

            writer.writerow([
                pub["id"], pub["doi"], pub["oa_status"], upw,
                "ok" if is_match else "DIFF",
            ])

    if not args.dry_run:
        conn.commit()

    conn.close()

    print(f"\n{'='*50}")
    print(f"Résultats audit ({total} publications)")
    print(f"  Identiques       : {matches:>6d}  ({100*matches/total:.1f}%)")
    print(f"  Divergences      : {divergences:>6d}  ({100*divergences/total:.1f}%)")
    print(f"  Non trouvés      : {not_found:>6d}  ({100*not_found/total:.1f}%)")
    if not args.dry_run:
        print(f"  Mis à jour       : {updates:>6d}")
    print(f"\nRapport CSV : {report_path}")

    # Matrice de confusion
    if divergences > 0:
        print(f"\nDétail des divergences (top transitions) :")
        transitions: dict[tuple[str, str], int] = {}
        with open(report_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["match"] == "DIFF":
                    key = (row["oa_current"], row["oa_unpaywall"])
                    transitions[key] = transitions.get(key, 0) + 1
        for (src, dst), n in sorted(transitions.items(), key=lambda x: -x[1]):
            print(f"  {src:8s} → {dst:8s} : {n}")


if __name__ == "__main__":
    main()
