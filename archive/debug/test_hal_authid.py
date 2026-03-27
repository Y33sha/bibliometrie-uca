"""
Test rapide : vérifie si authId_i est aligné avec authFullName_s dans l'API HAL.

Usage:
    python test_hal_authid.py

Interroge l'API HAL sur quelques documents et compare les longueurs des tableaux.
"""
import json
import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

# Prendre quelques halId depuis le staging pour tester
conn = get_connection()
cur = conn.cursor()
cur.execute("""
    SELECT halid FROM staging_hal
    WHERE jsonb_array_length(raw_data->'authFullName_s') BETWEEN 3 AND 10
    LIMIT 10
""")
hal_ids = [r[0] if isinstance(r, tuple) else r['halid'] for r in cur.fetchall()]
cur.close()
conn.close()

print(f"Test sur {len(hal_ids)} documents HAL\n")

FIELDS = "halId_s,authFullName_s,authId_i,authIdHal_s,authOrcid_s,authIdHal_i"
BASE_URL = "https://api.archives-ouvertes.fr/search/"

for halid in hal_ids:
    resp = requests.get(BASE_URL, params={
        "q": f"halId_s:{halid}",
        "fl": FIELDS,
        "wt": "json",
    }, timeout=15)
    data = resp.json()
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        print(f"  {halid}: pas trouvé")
        continue

    doc = docs[0]
    names = doc.get("authFullName_s", [])
    n = len(names)

    print(f"--- {halid} : {n} auteurs ---")
    print(f"  authFullName_s ({n}): {names[:5]}{'...' if n > 5 else ''}")

    for field in ["authId_i", "authIdHal_s", "authIdHal_i", "authOrcid_s"]:
        vals = doc.get(field)
        if vals is not None:
            vlen = len(vals) if isinstance(vals, list) else "scalar"
            aligned = "✓ ALIGNÉ" if isinstance(vals, list) and len(vals) == n else f"✗ ({vlen} vs {n})"
            preview = vals[:5] if isinstance(vals, list) else vals
            print(f"  {field} ({vlen}): {preview}  [{aligned}]")
        else:
            print(f"  {field}: absent")

    print()
