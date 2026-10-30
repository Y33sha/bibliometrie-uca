# STATUS: recurring (dev)
"""Captures d'écran du guide utilisateur, prises dans l'application en cours d'exécution.

Usage :
    uv run python -m interfaces.cli.dev.screenshots [--base-url URL] [--only NOM ...]

L'application doit tourner (`bash start.sh`). Les captures des pages d'administration demandent une session : le script se connecte avec `SCREENSHOT_LOGIN` et `SCREENSHOT_PASSWORD`, lus dans l'environnement. Sans eux, il saute ces captures.

Les pages d'exemple (une structure, l'établissement, une revue, un éditeur, un sujet) se trouvent par la recherche de l'API, d'après les noms de `SAMPLES`. Les fichiers vont dans `docs/img/screenshots/`, sous le nom de chaque capture.
"""

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import APIRequestContext, Page, sync_playwright

from infrastructure import PROJECT_ROOT

OUT_DIR = PROJECT_ROOT / "docs" / "img" / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}

# Entités montrées en exemple : (route de recherche, clé de la liste, champ comparé, valeur cherchée).
SAMPLES = {
    "structure": ("structures", "structures", "acronym", "LMV"),
    # Les pages d'adresses montrent l'établissement : les adresses d'un laboratoire contiennent souvent des courriels personnels.
    "institution": ("structures", "structures", "code", "uca"),
    "serial": ("serials", "serials", "title", "Journal of High Energy Physics"),
    "publisher": ("publishers", "publishers", "name", "Elsevier"),
    "subject": ("subjects", "items", "label", "Volcanologie"),
}


@dataclass(frozen=True)
class Shot:
    """Une capture : le fichier produit, la page (avec `{structure}`, `{institution}`, `{serial}`, `{publisher}`, `{subject}` remplacés par l'identifiant de l'exemple) et la session demandée."""

    name: str
    path: str
    admin: bool = False
    full_page: bool = False


SHOTS = [
    Shot("stats", "stats"),
    Shot("publications", "publications"),
    Shot("theses", "theses"),
    Shot("persons", "persons"),
    Shot("structures", "structures"),
    Shot("structure_dashboard", "structures/{structure}"),
    Shot("structure_partners", "structures/{structure}?tab=collaborations"),
    Shot("journal_dashboard", "journals/{serial}"),
    Shot("publisher_dashboard", "publishers/{publisher}"),
    Shot("subjects", "subjects"),
    Shot("subject_graph", "subjects/{subject}"),
    Shot("hal_problems", "hal-problems/affiliation-conflicts"),
    # Le volet de l'établissement montre les identifiants de structure des sources, que les laboratoires n'ont pas.
    Shot("admin_structure_management", "structures?structure={institution}", admin=True),
    Shot("admin_config", "admin/config", admin=True, full_page=True),
    Shot("admin_addresses", "admin/addresses?structure_id={institution}", admin=True),
    Shot("admin_countries", "admin/countries", admin=True),
    Shot("admin_pipeline", "admin/pipeline", admin=True),
    Shot("admin_publications", "publications?tab=suspect-merges", admin=True),
    Shot("admin_orphan_contributions", "admin/orphan-contributions", admin=True),
]


def sample_ids(api: APIRequestContext, base_url: str) -> dict[str, int]:
    """Identifiant de chaque entité de `SAMPLES`, trouvé par la recherche de l'API."""
    ids: dict[str, int] = {}
    for key, (endpoint, items, field, value) in SAMPLES.items():
        response = api.get(f"{base_url}/api/{endpoint}", params={"search": value, "per_page": 20})
        if not response.ok:
            raise SystemExit(f"Recherche refusée ({response.status}) : {endpoint}")
        matches = [item for item in response.json()[items] if item.get(field) == value]
        if not matches:
            raise SystemExit(f"Exemple introuvable : {key} {field}={value!r}")
        ids[key] = matches[0]["id"]
    return ids


def login(page: Page, base_url: str) -> bool:
    """Ouvre une session d'administration avec les identifiants de l'environnement. Faux sans identifiants."""
    username = os.environ.get("SCREENSHOT_LOGIN")
    password = os.environ.get("SCREENSHOT_PASSWORD")
    if not username or not password:
        return False
    response = page.request.post(
        f"{base_url}/api/auth/login", data={"username": username, "password": password}
    )
    if not response.ok:
        raise SystemExit(f"Connexion refusée ({response.status})")
    return True


def capture(page: Page, base_url: str, shot: Shot, ids: dict[str, int]) -> Path:
    """Ouvre la page de `shot`, attend la fin de ses requêtes et de ses graphiques, et enregistre la capture."""
    page.goto(f"{base_url}/{shot.path.format(**ids)}", wait_until="networkidle")
    # Les graphiques s'animent après le chargement des données.
    page.wait_for_timeout(1500)
    out = OUT_DIR / f"{shot.name}.png"
    page.screenshot(path=str(out), full_page=shot.full_page)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:5173/bibliometrie")
    parser.add_argument("--only", nargs="*", help="Noms des captures à refaire, toutes par défaut.")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    shots = [s for s in SHOTS if not args.only or s.name in args.only]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, locale="fr-FR")
        page = context.new_page()
        ids = sample_ids(context.request, base_url)
        for shot in [s for s in shots if not s.admin]:
            print(capture(page, base_url, shot, ids))
        admin_shots = [s for s in shots if s.admin]
        if admin_shots and login(page, base_url):
            for shot in admin_shots:
                print(capture(page, base_url, shot, ids))
        elif admin_shots:
            print(
                "SCREENSHOT_LOGIN et SCREENSHOT_PASSWORD absents : captures d'administration sautées."
            )
        browser.close()


if __name__ == "__main__":
    main()
