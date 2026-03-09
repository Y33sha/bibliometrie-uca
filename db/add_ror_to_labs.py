"""
Ajoute les ROR IDs aux laboratoires et met à jour la table laboratories.

Usage: python add_ror_to_labs.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

# Mapping HAL collection code → ROR ID
# Construit manuellement à partir de labos.json et des collections HAL
HAL_TO_ROR = {
    "INSTITUT_PASCAL": "https://ror.org/03vgfxd91",
    "UNH":            "https://ror.org/003qhrc72",
    "GEOLAB":         "https://ror.org/00e4pqm50",
    "CLERMA":         "https://ror.org/00nf46858",
    "LIMOS":          "https://ror.org/00t3fpp34",
    "LPC-CLERMONT":   "https://ror.org/0214k6v65",
    "LAPSCO":         "https://ror.org/01t4k8953",
    "CERHAC":         "https://ror.org/02wmc6m46",
    "LMGE":           "https://ror.org/020ahr442",
    "TERRITOIRES":    "https://ror.org/026tc4g97",
    "ND":             "https://ror.org/028m9sy08",
    "M2ISH":          "https://ror.org/02q7f3j18",
    "LMV":            "https://ror.org/02vnq7240",
    "LAMP":           "https://ror.org/03gz4y884",
    "ICC":            "https://ror.org/045qszf23",
    "MEDIS":          "https://ror.org/03d0rdy88",
    "PIAF":           "https://ror.org/03atqv648",
    "GDEC":           "https://ror.org/04397qy32",
    "UMR6620":        "https://ror.org/05sd5r855",
    "GRED":           "https://ror.org/052d1cv78",
    "CERDI":          "https://ror.org/01hg13988",
    "UMRF":           "https://ror.org/01xbd2h58",
    "RESSOURCES":     "https://ror.org/0394www40",
    "IMOST":          "https://ror.org/03y61y350",
    "ACCEPPT":        "https://ror.org/005caq902",
    "ACTE":           "https://ror.org/010kha811",
    "PHIER":          "https://ror.org/01cd4f636",
    "CROC":           "https://ror.org/01rp22j96",
    "CMH":            "https://ror.org/01vmzej98",
    "CELIS":          "https://ror.org/02gy1r431",
    "LRL":            "https://ror.org/02xmyxb72",
    "CHEC":           "https://ror.org/03rny4b03",
    "CHELTER":        "https://ror.org/0402qmp47",
    "LABCS":          "https://ror.org/03zzbzq91",
    "LESCORES":       "https://ror.org/04pya0t36",
    "AME2P":          "https://ror.org/059wd2y60",
    "OPGC":           "https://ror.org/01bch8q67",
    "MSH":            "https://ror.org/016vzeb02"
}


def main():
    conn = get_connection()
    cur = conn.cursor()

    # Ajouter la colonne ror_id si elle n'existe pas
    cur.execute("""
        ALTER TABLE laboratories
        ADD COLUMN IF NOT EXISTS ror_id TEXT UNIQUE
    """)

    updated = 0
    for hal_code, ror_id in HAL_TO_ROR.items():
        cur.execute("""
            UPDATE laboratories SET ror_id = %s
            WHERE hal_collection = %s
        """, (ror_id, hal_code))
        if cur.rowcount > 0:
            updated += 1

    conn.commit()
    print(f"{updated} laboratoires mis à jour avec ROR ID.")

    # Vérification
    cur.execute("""
        SELECT code, name, hal_collection, ror_id
        FROM laboratories
        ORDER BY code
    """)
    for row in cur.fetchall():
        ror = row[3] or "(pas de ROR)"
        print(f"  {row[0]:20s} {row[1]:20s} HAL:{row[2]:20s} {ror}")

    conn.close()


if __name__ == "__main__":
    main()
