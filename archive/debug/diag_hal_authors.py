"""
Exploration des champs auteur disponibles dans les données brutes HAL.
Vérifie quels champs sont alignés avec authFullName_s.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

conn = get_connection()
cur = conn.cursor()

# Champs auteur potentiellement intéressants
AUTHOR_FIELDS = [
    "authFullName_s",
    "authId_i",
    "authIdHal_s",
    "authIdHal_i",
    "authOrcid_s",
    "authIdForm_i",
    "authQuality_s",
    "authAlphaLastNameFirstNameId_s",
    "authLastName_s",
    "authFirstName_s",
    "authLastNameFirstName_s",
    "authIdFormPerson_s",
]

# Prendre un échantillon de documents avec plusieurs auteurs
cur.execute("""
    SELECT raw_data FROM staging_hal
    WHERE jsonb_array_length(raw_data->'authFullName_s') >= 3
    LIMIT 20
""")
rows = cur.fetchall()

print(f"=== Analyse de {len(rows)} documents HAL avec 3+ auteurs ===\n")

for i, row in enumerate(rows):
    doc = row['raw_data'] if isinstance(row, dict) else row[0]
    if isinstance(doc, str):
        doc = json.loads(doc)

    names = doc.get("authFullName_s", [])
    n = len(names)

    print(f"--- Doc {i+1}: {n} auteurs ---")
    print(f"  authFullName_s ({n}): {names[:5]}{'...' if n > 5 else ''}")

    for field in AUTHOR_FIELDS:
        if field == "authFullName_s":
            continue
        vals = doc.get(field)
        if vals is not None:
            vlen = len(vals) if isinstance(vals, list) else 'scalar'
            aligned = "✓ ALIGNÉ" if isinstance(vals, list) and len(vals) == n else "✗ sparse/différent"
            preview = vals[:5] if isinstance(vals, list) else vals
            print(f"  {field} ({vlen}): {preview}  [{aligned}]")

    # Chercher tout champ commençant par auth qu'on n'aurait pas listé
    extra = [k for k in doc.keys() if k.startswith("auth") and k not in AUTHOR_FIELDS]
    if extra:
        for field in extra:
            vals = doc.get(field)
            vlen = len(vals) if isinstance(vals, list) else 'scalar'
            print(f"  ** NOUVEAU ** {field} ({vlen}): {str(vals)[:120]}")

    print()
    if i >= 9:
        break

# Stats globales sur la présence des champs
print("\n=== Présence des champs sur l'ensemble du staging ===\n")
for field in AUTHOR_FIELDS + ["authStructId_i"]:
    cur.execute(f"""
        SELECT COUNT(*) FROM staging_hal
        WHERE raw_data ? '{field}'
    """)
    count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM staging_hal")
    total = cur.fetchone()[0]
    print(f"  {field}: {count}/{total} docs ({100*count//total}%)")

cur.close()
conn.close()
