# STATUS: oneshot (2026-05-23)
"""
Spike Phase 3 — chantier METIER_doi-ra-datacite.

Compare le payload DataCite (`api.datacite.org/dois/{doi}`) au payload natif renvoyé par l'API du repository pour ~N DOIs UCA réels, sur deux repositories phares :

- **Zenodo** (préfixe `10.5281`, client `cern.zenodo`) — API `https://zenodo.org/api/records/{record_id}`.
- **INRAE** (préfixes `10.14758`, `10.15454`, `10.17180`, client `inist.inra`) — API Dataverse `https://data.inrae.fr/api/datasets/:persistentId?persistentId=doi:{doi}`. Option (a) retenue : on ne garde que les DOIs qui renvoient 200 côté Dataverse (orphelins historiques exclus, ils gonfleraient le bruit sans aider la décision).

Stockage : payloads bruts en JSON, un fichier par repo, sous `docs/chantiers/datacite-vs-natives-spike-data/`. L'analyse champ-par-champ se fait à la main sur les payloads — la grille comparative tabulée est en bonus en fin de run.

Usage :
    python -m interfaces.cli.oneshot.datacite_vs_natives_spike \\
        [--repo zenodo|inrae|both] [--sample-size N] [--seed S]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.config import get_polite_pool_email

log = setup_logger("datacite_vs_natives_spike", os.path.dirname(__file__))

DATA_DIR = (
    Path(__file__).resolve().parents[3] / "docs" / "chantiers" / "datacite-vs-natives-spike-data"
)

DATACITE_DOI_URL = "https://api.datacite.org/dois"
ZENODO_RECORD_URL = "https://zenodo.org/api/records"
INRAE_DATASET_URL = "https://data.inrae.fr/api/datasets/:persistentId"

ZENODO_PREFIX = "10.5281"
INRAE_PREFIXES = ["10.14758", "10.15454", "10.17180"]

SLEEP_BETWEEN_CALLS = 0.2


def _user_agent(email: str) -> str:
    return f"UCA-bibliometrie-spike/0.1 (mailto:{email})"


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def sample_dois(conn: Connection, prefixes: list[str], n: int, rng: random.Random) -> list[str]:
    """Tire `n` DOIs UCA réels parmi les préfixes donnés. Ordre stable via `rng` seedé."""
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT doi
            FROM publications
            WHERE doi IS NOT NULL AND doi <> ''
              AND split_part(doi, '/', 1) = ANY(:prefixes)
            ORDER BY doi
            """
        ),
        {"prefixes": prefixes},
    ).fetchall()
    dois = [r.doi for r in rows]
    rng.shuffle(dois)
    return dois[:n]


def fetch_datacite_doi(client: httpx.Client, doi: str) -> dict[str, Any]:
    """GET `api.datacite.org/dois/{doi}`. Renvoie `{status, data|error}`."""
    try:
        resp = client.get(
            f"{DATACITE_DOI_URL}/{urllib.parse.quote(doi, safe='')}",
            headers={"Accept": "application/vnd.api+json"},
        )
        if resp.status_code == 200:
            return {"status": 200, "data": resp.json()}
        return {"status": resp.status_code}
    except Exception as exc:
        return {"error": repr(exc)}


def fetch_zenodo(client: httpx.Client, doi: str) -> dict[str, Any]:
    """GET `zenodo.org/api/records/{record_id}` où `record_id` = partie après `10.5281/zenodo.`."""
    if not doi.startswith(f"{ZENODO_PREFIX}/zenodo."):
        return {"skipped": "pattern non Zenodo standard (10.5281/zenodo.*)"}
    record_id = doi.split("zenodo.", 1)[1]
    try:
        resp = client.get(
            f"{ZENODO_RECORD_URL}/{record_id}",
            headers={"Accept": "application/json"},
        )
        if resp.status_code == 200:
            return {"status": 200, "data": resp.json()}
        return {"status": resp.status_code}
    except Exception as exc:
        return {"error": repr(exc)}


def fetch_inrae(client: httpx.Client, doi: str) -> dict[str, Any]:
    """GET `data.inrae.fr/api/datasets/:persistentId?persistentId=doi:{doi}`. 404 = orphelin (DOI historique pas dans Dataverse)."""
    try:
        resp = client.get(
            INRAE_DATASET_URL,
            params={"persistentId": f"doi:{doi}"},
            headers={"Accept": "application/json"},
        )
        if resp.status_code == 200:
            return {"status": 200, "data": resp.json()}
        return {"status": resp.status_code}
    except Exception as exc:
        return {"error": repr(exc)}


def run_zenodo(
    conn: Connection, client: httpx.Client, sample_size: int, rng: random.Random
) -> dict[str, Any]:
    log.info("▶ Zenodo (préfixe %s) — sample_size=%d", ZENODO_PREFIX, sample_size)
    dois = sample_dois(conn, [ZENODO_PREFIX], sample_size, rng)
    log.info("  %d DOIs sélectionnés", len(dois))
    pairs: dict[str, dict[str, Any]] = {}
    for i, doi in enumerate(dois, 1):
        log.info("  [%d/%d] %s", i, len(dois), doi)
        datacite = fetch_datacite_doi(client, doi)
        time.sleep(SLEEP_BETWEEN_CALLS)
        native = fetch_zenodo(client, doi)
        time.sleep(SLEEP_BETWEEN_CALLS)
        pairs[doi] = {"datacite": datacite, "zenodo": native}
        log.info(
            "      datacite=%s native=%s",
            datacite.get("status") or datacite.get("error") or datacite.get("skipped"),
            native.get("status") or native.get("error") or native.get("skipped"),
        )
    _save_json(DATA_DIR / "zenodo_samples.json", pairs)
    return pairs


def run_inrae(
    conn: Connection, client: httpx.Client, sample_size: int, rng: random.Random
) -> dict[str, Any]:
    log.info(
        "▶ INRAE (préfixes %s) — sample_size=%d (option a : Dataverse vivant uniquement)",
        INRAE_PREFIXES,
        sample_size,
    )
    dois = sample_dois(conn, INRAE_PREFIXES, sample_size * 3, rng)
    log.info("  %d DOIs candidats (tirage élargi pour absorber les orphelins)", len(dois))
    pairs: dict[str, dict[str, Any]] = {}
    kept = 0
    for doi in dois:
        if kept >= sample_size:
            break
        log.info("  candidate %s …", doi)
        native = fetch_inrae(client, doi)
        time.sleep(SLEEP_BETWEEN_CALLS)
        if native.get("status") != 200:
            log.info("    skip (native=%s)", native.get("status") or native.get("error"))
            continue
        datacite = fetch_datacite_doi(client, doi)
        time.sleep(SLEEP_BETWEEN_CALLS)
        pairs[doi] = {"datacite": datacite, "inrae": native}
        kept += 1
        log.info("    keep (datacite=%s) — %d/%d", datacite.get("status"), kept, sample_size)
    log.info("  → %d paires retenues sur %d candidats testés", kept, len(dois))
    _save_json(DATA_DIR / "inrae_samples.json", pairs)
    return pairs


def lightweight_grid(pairs_by_repo: dict[str, dict[str, dict[str, Any]]]) -> None:
    """Bonus : grille en bonus à plat sur quelques champs faciles à extraire. Pas le cœur du spike — sert juste à fournir une première lecture en lisant le log."""
    log.info("▶ Grille bonus (lecture rapide ; l'analyse de fond se fait sur les payloads bruts)")
    for repo, pairs in pairs_by_repo.items():
        log.info("  Repo %s : %d paires", repo, len(pairs))
        for doi, sides in pairs.items():
            datacite_payload = (sides.get("datacite") or {}).get("data") or {}
            native_payload = (sides.get(repo) or {}).get("data") or {}
            datacite_attr = (datacite_payload.get("data") or {}).get("attributes") or {}
            datacite_creators = datacite_attr.get("creators") or []
            datacite_related = datacite_attr.get("relatedIdentifiers") or []
            datacite_descr = datacite_attr.get("descriptions") or []
            # Champs natifs : structures variables selon le repo.
            if repo == "zenodo":
                meta = native_payload.get("metadata") or {}
                native_creators = meta.get("creators") or []
                native_related = meta.get("related_identifiers") or []
                native_descr_len = len(meta.get("description") or "")
            else:  # inrae / Dataverse
                meta = ((native_payload.get("data") or {}).get("latestVersion") or {}).get(
                    "metadataBlocks"
                ) or {}
                citation = (meta.get("citation") or {}).get("fields") or []
                native_creators = next(
                    (f.get("value") for f in citation if f.get("typeName") == "author"), []
                )
                native_related = []  # Dataverse expose les related dans un autre bloc
                ds_descr_field: Any = next(
                    (f.get("value") for f in citation if f.get("typeName") == "dsDescription"), []
                )
                native_descr_len = sum(
                    len((d.get("dsDescriptionValue") or {}).get("value") or "")
                    for d in (ds_descr_field if isinstance(ds_descr_field, list) else [])
                )
            log.info(
                "    %s  creators DC=%d / native=%d  related DC=%d / native=%d  descr DC=%d / native_len=%d",
                doi,
                len(datacite_creators),
                len(native_creators) if isinstance(native_creators, list) else 0,
                len(datacite_related),
                len(native_related),
                len(datacite_descr),
                native_descr_len,
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", choices=["zenodo", "inrae", "both"], default="both")
    parser.add_argument("--sample-size", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    engine = get_sync_engine()
    pairs_by_repo: dict[str, dict[str, dict[str, Any]]] = {}
    with engine.connect() as conn:
        user_agent = _user_agent(get_polite_pool_email(conn))
        with httpx.Client(
            headers={"User-Agent": user_agent}, timeout=30.0, follow_redirects=True
        ) as client:
            if args.repo in ("zenodo", "both"):
                pairs_by_repo["zenodo"] = run_zenodo(conn, client, args.sample_size, rng)
            if args.repo in ("inrae", "both"):
                pairs_by_repo["inrae"] = run_inrae(conn, client, args.sample_size, rng)
    lightweight_grid(pairs_by_repo)
    log.info("✓ outputs dans %s", DATA_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
