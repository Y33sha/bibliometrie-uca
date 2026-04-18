"""
Debug : inspecte la réponse brute de l'API ref auteur HAL.
"""

import json

import requests

# Quelques IDs numériques HAL connus depuis les tests précédents
TEST_IDS = [179576, 740464, 179323, 180901, 21937]

for hid in TEST_IDS:
    # Tentative 1: endpoint direct
    url1 = f"https://api.archives-ouvertes.fr/ref/author/{hid}"
    r1 = requests.get(url1, timeout=10)
    print(f"=== HAL author #{hid} ===")
    print(f"  GET {url1}")
    print(f"  Status: {r1.status_code}")
    print(f"  Content-Type: {r1.headers.get('content-type')}")
    print(f"  Body (500 chars): {r1.text[:500]}")
    print()

    # Tentative 2: endpoint search avec filtre
    url2 = "https://api.archives-ouvertes.fr/ref/author/"
    params = {
        "q": f"docid:{hid}",
        "fl": "docid,fullName_s,firstName_s,lastName_s,idHal_s,idHal_i,orcid_s",
        "wt": "json",
    }
    r2 = requests.get(url2, params=params, timeout=10)
    print(f"  GET {url2}?q=docid:{hid}")
    print(f"  Status: {r2.status_code}")
    try:
        data = r2.json()
        docs = data.get("response", {}).get("docs", [])
        print(f"  numFound: {data.get('response', {}).get('numFound', '?')}")
        if docs:
            print(f"  Doc: {json.dumps(docs[0], indent=2, ensure_ascii=False)}")
        else:
            print("  Pas de résultat")
    except Exception as e:
        print(f"  Parse error: {e}")
        print(f"  Body: {r2.text[:300]}")

    print()
