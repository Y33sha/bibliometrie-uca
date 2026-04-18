"""
Explore les champs composés HAL qui pourraient lier auteurs et structures.
"""

import requests

# Quelques halId avec peu d'auteurs pour lire facilement
TEST_IDS = [
    "hal-05114304",  # 3 auteurs: Sabrina Alioui, Vanessa Serret, Kamal Si Mohammed
    "hal-05157466",  # 3 auteurs: Nicolas Baelen, Sylvain Marsat, Guillaume Pijourlet
    "hal-04967062",  # 3 auteurs: Emilie Bourlier-Bargues, Bertrand Valiorgue, Gazi Islam
]

# Champs composés potentiellement intéressants
COMPOUND_FIELDS = [
    "authFullName_s",
    "authIdHal_i",
    "authIdHal_s",
    "structHasAuthId_fs",
    "structHasAuthIdHal_fs",
    "authIdHasStructure_fs",
    "authStructId_i",
    "authIdHalFullName_fs",
    "authIdFullName_fs",
    "authFullNameId_fs",
    "authFullNameIdHal_fs",
    "authQuality_s",
]

BASE_URL = "https://api.archives-ouvertes.fr/search/"

for halid in TEST_IDS:
    resp = requests.get(
        BASE_URL,
        params={
            "q": f"halId_s:{halid}",
            "fl": ",".join(COMPOUND_FIELDS),
            "wt": "json",
        },
        timeout=15,
    )
    data = resp.json()
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        print(f"{halid}: pas trouvé\n")
        continue

    doc = docs[0]
    print(f"=== {halid} ===")
    for field in COMPOUND_FIELDS:
        val = doc.get(field)
        if val is not None:
            if isinstance(val, list) and len(val) > 8:
                print(f"  {field} ({len(val)}): {val[:5]}...")
            else:
                print(f"  {field}: {val}")
        # ne rien afficher si absent, pour réduire le bruit

    # Chercher TOUT champ contenant "auth" qu'on n'a pas demandé
    # (HAL peut renvoyer des champs supplémentaires)
    print()

# Deuxième passe : demander TOUS les champs pour un doc et grep auth/struct
print("\n=== TOUS LES CHAMPS d'un document (filtre auth/struct) ===\n")
resp = requests.get(
    BASE_URL,
    params={
        "q": f"halId_s:{TEST_IDS[0]}",
        "fl": "*",
        "wt": "json",
    },
    timeout=15,
)
doc = resp.json()["response"]["docs"][0]
for key in sorted(doc.keys()):
    if "auth" in key.lower() or "struct" in key.lower():
        val = doc[key]
        if isinstance(val, list) and len(val) > 5:
            print(f"  {key} ({len(val)}): {val[:3]}...")
        else:
            print(f"  {key}: {val}")
