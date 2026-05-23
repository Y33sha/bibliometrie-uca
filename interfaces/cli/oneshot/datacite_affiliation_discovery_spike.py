# STATUS: oneshot (2026-05-23)
"""
Spike Phase 3 (suite) — chantier METIER_doi-ra-datacite.

Évalue si `api.datacite.org/dois?query=...` permet de retrouver des publications UCA via leur affiliation textuelle, sans passer par un DOI déjà connu. Les affiliations sont souvent composées ("Université Clermont Auvergne, CNRS, Institut Pascal, …"), donc on teste des phrase queries qui matchent la sous-chaîne `Université Clermont Auvergne` quel que soit le reste.

Si le volume retourné est significatif et que l'intersection avec `publications.doi` montre des DOIs **absents** de la base, DataCite devient une **source d'extraction de plein droit** (affiliation-driven), au même titre que HAL/OpenAlex — pas seulement un fallback DOI-driven.

Trois variantes de query testées :
- `creators.affiliation.name:"Université Clermont Auvergne"` (auteurs principaux)
- `contributors.affiliation.name:"Université Clermont Auvergne"` (contributeurs secondaires)
- recherche libre `Université Clermont Auvergne` (tous champs indexés)

Usage :
    python -m interfaces.cli.oneshot.datacite_affiliation_discovery_spike \\
        [--max-pages N]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.config import get_openalex_email

log = setup_logger("datacite_affiliation_discovery_spike", os.path.dirname(__file__))

DATA_DIR = (
    Path(__file__).resolve().parents[3] / "docs" / "chantiers" / "datacite-vs-natives-spike-data"
)

DATACITE_DOIS_URL = "https://api.datacite.org/dois"
UCA_NAME = "Université Clermont Auvergne"
PAGE_SIZE = 1000
SLEEP_BETWEEN_PAGES = 0.3

QUERIES = {
    "creators_phrase": f'creators.affiliation.name:"{UCA_NAME}"',
    "contributors_phrase": f'contributors.affiliation.name:"{UCA_NAME}"',
    "broad_query": UCA_NAME,
}


def _user_agent(email: str) -> str:
    return f"UCA-bibliometrie-spike/0.1 (mailto:{email})"


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_first_page(client: httpx.Client, query: str) -> dict[str, Any]:
    """Une seule page pour mesurer le volume total (meta.total) et inspecter un échantillon."""
    resp = client.get(
        DATACITE_DOIS_URL,
        params={"query": query, "page[size]": 5},
    )
    resp.raise_for_status()
    return resp.json()


def paginate_dois(client: httpx.Client, query: str, max_pages: int) -> list[str]:
    """Récupère les DOIs (juste les IDs) via pagination cursor. Cap à `max_pages`."""
    dois: list[str] = []
    next_url: str | None = None
    params: dict[str, Any] | None = {
        "query": query,
        "page[size]": PAGE_SIZE,
        "page[cursor]": 1,
    }
    for page in range(max_pages):
        if next_url:
            resp = client.get(next_url)
        else:
            resp = client.get(DATACITE_DOIS_URL, params=params)
        resp.raise_for_status()
        payload = resp.json()
        page_dois = [(d.get("id") or "").lower() for d in payload.get("data", []) if d.get("id")]
        dois.extend(page_dois)
        log.info("    page %d : +%d DOIs (cumul %d)", page + 1, len(page_dois), len(dois))
        links = payload.get("links") or {}
        next_url = links.get("next")
        params = None
        if not next_url or not page_dois:
            break
        time.sleep(SLEEP_BETWEEN_PAGES)
    return dois


def get_known_uca_dois(conn: Connection) -> set[str]:
    """DOIs déjà présents en base (publications)."""
    rows = conn.execute(
        text("SELECT lower(doi) AS doi FROM publications WHERE doi IS NOT NULL AND doi <> ''")
    ).fetchall()
    return {r.doi for r in rows}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help=(
            f"Cap de pages (PAGE_SIZE={PAGE_SIZE} par page) "
            "lors du paginage de la query la plus prometteuse"
        ),
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    engine = get_sync_engine()

    with engine.connect() as conn:
        user_agent = _user_agent(get_openalex_email(conn))
        known_dois = get_known_uca_dois(conn)
        log.info("Base connue : %d DOIs UCA en publications", len(known_dois))

        with httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "application/vnd.api+json"},
            timeout=30.0,
        ) as client:
            # Étape 1 : volume par variante
            log.info("▶ Étape 1 — volume par variante de query")
            volumes: dict[str, dict[str, Any]] = {}
            for label, query in QUERIES.items():
                log.info("  Query %s : %s", label, query)
                payload = fetch_first_page(client, query)
                total = (payload.get("meta") or {}).get("total")
                sample_dois = [d.get("id") for d in payload.get("data", [])[:3]]
                log.info("    total=%s, sample=%s", total, sample_dois)
                volumes[label] = {
                    "query": query,
                    "total": total,
                    "sample_dois": sample_dois,
                    "first_page": payload,
                }
                time.sleep(SLEEP_BETWEEN_PAGES)

            _save_json(DATA_DIR / "affiliation_discovery_volumes.json", volumes)

            # Étape 2 : pagination complète sur la query la plus prometteuse
            best_label = max(volumes, key=lambda k: volumes[k]["total"] or 0)
            best_query = volumes[best_label]["query"]
            log.info(
                "▶ Étape 2 — pagination de la query %s (total=%s)",
                best_label,
                volumes[best_label]["total"],
            )
            all_dois = paginate_dois(client, best_query, args.max_pages)
            log.info(
                "  Récupéré %d DOIs (cap=%d pages × %d)", len(all_dois), args.max_pages, PAGE_SIZE
            )

            _save_json(
                DATA_DIR / "affiliation_discovery_dois.json",
                {"query_label": best_label, "query": best_query, "dois": all_dois},
            )

            # Étape 3 : diff avec la base
            discovered = set(all_dois)
            overlap = discovered & known_dois
            new = discovered - known_dois
            log.info("▶ Étape 3 — diff avec publications.doi")
            log.info("  DOIs DataCite trouvés : %d", len(discovered))
            log.info(
                "  Déjà en base : %d (%.1f %%)",
                len(overlap),
                100 * len(overlap) / max(1, len(discovered)),
            )
            log.info(
                "  Nouveaux candidats : %d (%.1f %%)",
                len(new),
                100 * len(new) / max(1, len(discovered)),
            )

            # Échantillon de nouveaux DOIs avec leur préfixe pour aperçu
            new_by_prefix: dict[str, int] = {}
            for doi in new:
                p = doi.split("/", 1)[0] if "/" in doi else "?"
                new_by_prefix[p] = new_by_prefix.get(p, 0) + 1
            top_prefixes = sorted(new_by_prefix.items(), key=lambda kv: -kv[1])[:20]
            log.info("  Top préfixes des nouveaux candidats :")
            for p, n in top_prefixes:
                log.info("    %s : %d", p, n)

            _save_json(
                DATA_DIR / "affiliation_discovery_diff.json",
                {
                    "discovered_total": len(discovered),
                    "already_in_db": len(overlap),
                    "new_candidates": len(new),
                    "new_by_prefix_top20": top_prefixes,
                    "sample_new_dois": sorted(new)[:50],
                },
            )

    log.info("✓ outputs dans %s", DATA_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
