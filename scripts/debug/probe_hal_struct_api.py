"""Inspecte l'API ref/structure HAL pour voir les champs disponibles."""
import requests
import json

# Chercher une structure connue (Institut Pascal = 1063693)
TEST_IDS = [1063693, 184846, 1063666]

for sid in TEST_IDS:
    url = "https://api.archives-ouvertes.fr/ref/structure/"
    params = {
        "q": f"docid:{sid}",
        "fl": "*",
        "wt": "json",
    }
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    docs = data.get("response", {}).get("docs", [])
    
    if docs:
        doc = docs[0]
        print(f"=== HAL structure #{sid} ===")
        for key in sorted(doc.keys()):
            val = doc[key]
            if isinstance(val, list) and len(val) > 3:
                print(f"  {key}: {val[:3]}... ({len(val)} items)")
            else:
                print(f"  {key}: {val}")
        print()
    else:
        print(f"=== HAL structure #{sid}: not found ===\n")
