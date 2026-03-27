"""
Vérifie si authIdHal_i est réellement aligné avec authFullName_s.

Pour chaque document où len(authIdHal_i) == len(authFullName_s),
on résout chaque ID numérique via l'API ref auteur HAL et on compare
le nom retourné avec le nom à la même position.

Usage:
    python verify_hal_alignment.py
"""
import json
import sys
import os
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.normalize import normalize_name as normalize


def fetch_hal_author(hal_author_id):
    """Interroge l'API ref auteur HAL pour obtenir le nom."""
    url = f"https://api.archives-ouvertes.fr/ref/author/{hal_author_id}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # L'API retourne directement les infos de l'auteur
            full = data.get("fullName_s") or ""
            first = data.get("firstName_s") or ""
            last = data.get("lastName_s") or ""
            idhal = data.get("idHal_s") or ""
            return {"full": full, "first": first, "last": last, "idhal": idhal}
        else:
            return None
    except Exception:
        return None


# Récupérer des documents depuis le staging via l'API HAL (pour avoir authIdHal_i)
conn = get_connection()
cur = conn.cursor()
cur.execute("""
    SELECT halid FROM staging_hal
    WHERE jsonb_array_length(raw_data->'authFullName_s') BETWEEN 3 AND 8
    LIMIT 50
""")
hal_ids = [r[0] if isinstance(r, tuple) else r['halid'] for r in cur.fetchall()]
cur.close()
conn.close()

FIELDS = "halId_s,authFullName_s,authIdHal_i"
BASE_URL = "https://api.archives-ouvertes.fr/search/"

total_checked = 0
total_match = 0
total_mismatch = 0
docs_aligned = 0

print(f"Vérification sur {len(hal_ids)} documents HAL\n")

for halid in hal_ids:
    resp = requests.get(BASE_URL, params={
        "q": f"halId_s:{halid}",
        "fl": FIELDS,
        "wt": "json",
    }, timeout=15)
    data = resp.json()
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        continue

    doc = docs[0]
    names = doc.get("authFullName_s", [])
    hal_ids_i = doc.get("authIdHal_i")

    if not hal_ids_i or len(hal_ids_i) != len(names):
        continue

    docs_aligned += 1
    print(f"--- {halid} : {len(names)} auteurs ---")

    for pos, (name, hid) in enumerate(zip(names, hal_ids_i)):
        author_info = fetch_hal_author(hid)
        time.sleep(0.1)  # rate limit

        if not author_info:
            print(f"  [{pos}] {name} → HAL#{hid} : API error")
            continue

        total_checked += 1
        name_norm = normalize(name)
        api_norm = normalize(author_info["full"])
        last_norm = normalize(author_info["last"])

        # Comparaison souple : le nom de famille de l'API doit apparaître dans le nom du doc
        match = last_norm in name_norm or name_norm in api_norm or api_norm == name_norm
        if match:
            total_match += 1
            symbol = "✓"
        else:
            total_mismatch += 1
            symbol = "✗ MISMATCH"

        print(f"  [{pos}] {name} → HAL#{hid} → {author_info['full']} "
              f"(idHAL: {author_info['idhal']}) [{symbol}]")

    print()

    if docs_aligned >= 8:
        break

print(f"\n=== RÉSUMÉ ===")
print(f"Documents alignés testés : {docs_aligned}")
print(f"Auteurs vérifiés : {total_checked}")
print(f"  ✓ Match  : {total_match}")
print(f"  ✗ Mismatch : {total_mismatch}")
if total_checked > 0:
    print(f"  Taux de match : {100*total_match//total_checked}%")
