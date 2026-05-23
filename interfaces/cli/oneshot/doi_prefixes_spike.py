# STATUS: oneshot (2026-05-19)
"""
Spike Phase 0 — chantier METIER_doi-ra-datacite.

Inventaire des préfixes DOI dans le corpus UCA + résolution Registration
Agency (doi.org/ra) + mapping prefix → publisher (api.crossref.org) +
audit de cohérence `doc_type × RA` + échantillon DataCite. Sert à
trancher le go/no-go de la Phase 2 (ingestion DataCite).

Usage :
    python -m interfaces.cli.oneshot.doi_prefixes_spike [--phase X] [--sample-size N]

Phases (toutes par défaut, dans l'ordre) :
    inventory          : SQL only — préfixes par publications, source_publications, staging
    resolve-ra         : doi.org/ra pour chaque préfixe distinct (cache local)
    publishers         : api.crossref.org/prefixes/{p} pour les préfixes RA=Crossref
    coherence          : matrice doc_type × RA, anomalies
    sample-datacite    : ~N DOIs DataCite via api.datacite.org/dois/{doi} (stratifié par doc_type)
    prefixes-datacite  : api.datacite.org/prefixes/{p} pour les préfixes DataCite déjà
                         résolus en base (`doi_prefixes.ra='DataCite'`). Cible : voir si
                         on peut récupérer un client/repository par préfixe (analogue
                         CrossRef → publisher) et envisager l'intégration dans la phase
                         pipeline `resolve_doi_prefixes`.

Outputs : docs/chantiers/doi-prefixes-spike-data/*.json (gitignored).
La note de synthèse `docs/chantiers/doi-prefixes-spike.md` est rédigée
à la main à partir de ces sorties.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.config import get_polite_pool_email

log = setup_logger("doi_prefixes_spike", os.path.dirname(__file__))

DATA_DIR = Path(__file__).resolve().parents[3] / "docs" / "chantiers" / "doi-prefixes-spike-data"
RA_CACHE = DATA_DIR / "ra_cache.json"
PUBLISHER_CACHE = DATA_DIR / "publisher_cache.json"
DATACITE_PREFIX_CACHE = DATA_DIR / "datacite_prefix_cache.json"

DOI_RA_URL = "https://doi.org/ra"
CROSSREF_PREFIX_URL = "https://api.crossref.org/prefixes"
DATACITE_DOI_URL = "https://api.datacite.org/dois"
DATACITE_PREFIX_URL = "https://api.datacite.org/prefixes"
SLEEP_BETWEEN_CALLS = 0.1


def _user_agent(email: str) -> str:
    return f"UCA-bibliometrie-spike/0.1 (mailto:{email})"


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def phase_inventory(conn: Connection) -> dict[str, Any]:
    log.info("▶ inventory : préfixes par publications / source_publications / staging")

    publications = [
        dict(r._mapping)
        for r in conn.execute(
            text(
                """
                SELECT split_part(doi, '/', 1) AS prefix,
                       doc_type::text AS doc_type,
                       COUNT(*)::int AS n
                FROM publications
                WHERE doi IS NOT NULL AND doi <> ''
                GROUP BY 1, 2
                ORDER BY n DESC, prefix
                """
            )
        )
    ]

    source_publications = [
        dict(r._mapping)
        for r in conn.execute(
            text(
                """
                SELECT split_part(doi, '/', 1) AS prefix,
                       source::text AS source,
                       COUNT(*)::int AS n
                FROM source_publications
                WHERE doi IS NOT NULL AND doi <> ''
                GROUP BY 1, 2
                ORDER BY n DESC, prefix
                """
            )
        )
    ]

    staging = [
        dict(r._mapping)
        for r in conn.execute(
            text(
                """
                SELECT split_part(doi, '/', 1) AS prefix,
                       source::text AS source,
                       SUM(CASE WHEN not_found THEN 1 ELSE 0 END)::int AS n_not_found,
                       COUNT(*)::int AS n_total
                FROM staging
                WHERE doi IS NOT NULL AND doi <> ''
                GROUP BY 1, 2
                ORDER BY n_total DESC, prefix
                """
            )
        )
    ]

    # Un DOI sample par préfixe (le plus court : moins d'encodage à faire)
    samples = [
        dict(r._mapping)
        for r in conn.execute(
            text(
                """
                SELECT DISTINCT ON (split_part(doi, '/', 1))
                    split_part(doi, '/', 1) AS prefix,
                    doi AS sample_doi
                FROM publications
                WHERE doi IS NOT NULL AND doi <> ''
                ORDER BY split_part(doi, '/', 1), length(doi)
                """
            )
        )
    ]

    distinct_prefixes = sorted(
        {row["prefix"] for row in publications}
        | {row["prefix"] for row in source_publications}
        | {row["prefix"] for row in staging}
    )

    log.info(
        f"  publications : {len(publications)} (prefix, doc_type) rows, "
        f"{len({r['prefix'] for r in publications})} préfixes distincts"
    )
    log.info(
        f"  source_publications : {len(source_publications)} (prefix, source) rows, "
        f"{len({r['prefix'] for r in source_publications})} préfixes distincts"
    )
    log.info(
        f"  staging : {len(staging)} (prefix, source) rows, "
        f"{len({r['prefix'] for r in staging})} préfixes distincts"
    )
    log.info(f"  total préfixes distincts (union) : {len(distinct_prefixes)}")

    inventory = {
        "publications": publications,
        "source_publications": source_publications,
        "staging": staging,
        "prefix_samples": samples,
        "distinct_prefixes": distinct_prefixes,
    }
    _save_json(DATA_DIR / "inventory.json", inventory)
    return inventory


def phase_resolve_ra(prefix_samples: list[dict[str, str]], user_agent: str) -> dict[str, str]:
    log.info(f"▶ resolve-ra : doi.org/ra pour {len(prefix_samples)} préfixes")
    cache: dict[str, str] = _load_json(RA_CACHE, {})
    todo = [s for s in prefix_samples if s["prefix"] not in cache]
    log.info(f"  {len(cache)} en cache, {len(todo)} à résoudre")

    with httpx.Client(
        headers={"User-Agent": user_agent, "Accept": "application/json"}, timeout=15.0
    ) as client:
        for i, sample in enumerate(todo, 1):
            prefix = sample["prefix"]
            doi = sample["sample_doi"]
            try:
                resp = client.get(f"{DOI_RA_URL}/{urllib.parse.quote(doi, safe='')}")
                if resp.status_code != 200:
                    log.warning(f"  [{i}/{len(todo)}] {prefix} via {doi}: HTTP {resp.status_code}")
                    cache[prefix] = "error"
                else:
                    data = resp.json()
                    # Format: [{"DOI":"...","RA":"Crossref"|"DataCite"|...|"DOI Not Found"}]
                    ra = data[0].get("RA", "unknown") if data else "unknown"
                    cache[prefix] = ra
                    log.info(f"  [{i}/{len(todo)}] {prefix} → {ra}")
            except Exception as exc:
                log.error(f"  [{i}/{len(todo)}] {prefix} : {exc!r}")
                cache[prefix] = "error"

            if i % 25 == 0:
                _save_json(RA_CACHE, cache)
            time.sleep(SLEEP_BETWEEN_CALLS)

    _save_json(RA_CACHE, cache)

    distribution = Counter(cache.values())
    log.info(f"  distribution RA : {dict(distribution)}")
    return cache


def phase_publishers(ra_cache: dict[str, str], user_agent: str) -> dict[str, dict[str, Any]]:
    crossref_prefixes = sorted(p for p, ra in ra_cache.items() if ra == "Crossref")
    log.info(
        f"▶ publishers : api.crossref.org/prefixes pour {len(crossref_prefixes)} préfixes Crossref"
    )

    cache: dict[str, dict[str, Any]] = _load_json(PUBLISHER_CACHE, {})
    todo = [p for p in crossref_prefixes if p not in cache]
    log.info(f"  {len(cache)} en cache, {len(todo)} à résoudre")

    with httpx.Client(
        headers={"User-Agent": user_agent, "Accept": "application/json"}, timeout=15.0
    ) as client:
        for i, prefix in enumerate(todo, 1):
            try:
                resp = client.get(f"{CROSSREF_PREFIX_URL}/{prefix}")
                if resp.status_code != 200:
                    log.warning(f"  [{i}/{len(todo)}] {prefix} : HTTP {resp.status_code}")
                    cache[prefix] = {"error": resp.status_code}
                else:
                    data = resp.json()
                    msg = data.get("message", {})
                    cache[prefix] = {
                        "name": msg.get("name"),
                        "member": msg.get("member"),
                    }
                    log.info(f"  [{i}/{len(todo)}] {prefix} → {cache[prefix]['name']!r}")
            except Exception as exc:
                log.error(f"  [{i}/{len(todo)}] {prefix} : {exc!r}")
                cache[prefix] = {"error": repr(exc)}

            if i % 25 == 0:
                _save_json(PUBLISHER_CACHE, cache)
            time.sleep(SLEEP_BETWEEN_CALLS)

    _save_json(PUBLISHER_CACHE, cache)
    return cache


def phase_coherence(
    inventory: dict[str, Any], ra_cache: dict[str, str], publisher_cache: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    log.info("▶ coherence : matrice doc_type × RA")

    # Matrice doc_type × RA, comptée depuis publications
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in inventory["publications"]:
        ra = ra_cache.get(row["prefix"], "unresolved")
        matrix[row["doc_type"]][ra] += row["n"]

    # Anomalies à inspecter
    suspect_articles_datacite = [
        row
        for row in inventory["publications"]
        if row["doc_type"] == "article" and ra_cache.get(row["prefix"]) == "DataCite"
    ]
    suspect_theses_crossref = [
        row
        for row in inventory["publications"]
        if row["doc_type"] == "thesis" and ra_cache.get(row["prefix"]) == "Crossref"
    ]

    # Top préfixes par volume cumulé (toutes doc_types confondues)
    prefix_volumes: dict[str, int] = defaultdict(int)
    for row in inventory["publications"]:
        prefix_volumes[row["prefix"]] += row["n"]
    top_prefixes = sorted(prefix_volumes, key=lambda p: -prefix_volumes[p])[:50]

    coherence = {
        "matrix": {dt: dict(ras) for dt, ras in matrix.items()},
        "suspect_articles_datacite": suspect_articles_datacite,
        "suspect_theses_crossref": suspect_theses_crossref,
        "publisher_for_top_prefixes": [
            {
                "prefix": p,
                "volume": prefix_volumes[p],
                "ra": ra_cache.get(p, "unresolved"),
                "publisher_name": publisher_cache.get(p, {}).get("name"),
            }
            for p in top_prefixes
        ],
    }
    _save_json(DATA_DIR / "coherence.json", coherence)

    log.info("  matrice doc_type × RA :")
    all_ras = sorted({ra for d in matrix.values() for ra in d.keys()})
    header = f"    {'doc_type':<15} " + " ".join(f"{ra:>12}" for ra in all_ras)
    log.info(header)
    for dt in sorted(matrix.keys()):
        line = f"    {dt:<15} " + " ".join(f"{matrix[dt].get(ra, 0):>12}" for ra in all_ras)
        log.info(line)

    log.info(
        f"  suspects article+DataCite : {sum(r['n'] for r in suspect_articles_datacite)} publis"
    )
    log.info(f"  suspects thesis+Crossref  : {sum(r['n'] for r in suspect_theses_crossref)} publis")

    return coherence


def phase_sample_datacite(
    conn: Connection,
    ra_cache: dict[str, str],
    sample_size: int,
    user_agent: str,
) -> list[dict[str, Any]]:
    datacite_prefixes = [p for p, ra in ra_cache.items() if ra == "DataCite"]
    log.info(
        f"▶ sample-datacite : {sample_size} DOIs depuis {len(datacite_prefixes)} préfixes DataCite"
    )

    if not datacite_prefixes:
        log.warning("  aucun préfixe DataCite résolu — phase précédente requise")
        return []

    # Stratification par doc_type : on tire ~équilibré sur les buckets dispos
    rows = [
        dict(r._mapping)
        for r in conn.execute(
            text(
                """
                SELECT id, doi, doc_type::text AS doc_type, title, pub_year
                FROM publications
                WHERE doi IS NOT NULL AND doi <> ''
                  AND split_part(doi, '/', 1) = ANY(:prefixes)
                """
            ),
            {"prefixes": datacite_prefixes},
        )
    ]
    log.info(f"  {len(rows)} publis DataCite candidates en base")

    by_doctype: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_doctype[row["doc_type"]].append(row)

    rng = random.Random(42)
    per_bucket = max(1, sample_size // max(1, len(by_doctype)))
    selected: list[dict[str, Any]] = []
    for dt, bucket in by_doctype.items():
        rng.shuffle(bucket)
        picked = bucket[:per_bucket]
        log.info(f"  bucket {dt} : {len(picked)}/{len(bucket)}")
        selected.extend(picked)
    selected = selected[:sample_size]

    samples: list[dict[str, Any]] = []
    with httpx.Client(
        headers={"User-Agent": user_agent, "Accept": "application/vnd.api+json"}, timeout=15.0
    ) as client:
        for i, row in enumerate(selected, 1):
            doi = row["doi"]
            try:
                resp = client.get(f"{DATACITE_DOI_URL}/{urllib.parse.quote(doi, safe='')}")
                if resp.status_code == 404:
                    log.warning(
                        f"  [{i}/{len(selected)}] {doi} : 404 (DOI DataCite inconnu de l'API)"
                    )
                    samples.append({"doi": doi, "doc_type_in_db": row["doc_type"], "status": 404})
                elif resp.status_code != 200:
                    log.warning(f"  [{i}/{len(selected)}] {doi} : HTTP {resp.status_code}")
                    samples.append(
                        {"doi": doi, "doc_type_in_db": row["doc_type"], "status": resp.status_code}
                    )
                else:
                    samples.append(
                        {
                            "doi": doi,
                            "doc_type_in_db": row["doc_type"],
                            "status": 200,
                            "data": resp.json().get("data", {}),
                        }
                    )
                    log.info(f"  [{i}/{len(selected)}] {doi} ✓")
            except Exception as exc:
                log.error(f"  [{i}/{len(selected)}] {doi} : {exc!r}")
                samples.append({"doi": doi, "doc_type_in_db": row["doc_type"], "error": repr(exc)})
            time.sleep(SLEEP_BETWEEN_CALLS)

    _save_json(DATA_DIR / "datacite_samples.json", samples)
    return samples


def phase_prefixes_datacite(conn: Connection, user_agent: str) -> dict[str, Any]:
    """`api.datacite.org/prefixes/{p}` pour les préfixes DataCite en base.

    Source = `doi_prefixes` (table de prod post-Phase 1), pas le cache
    JSON de la phase 0. On veut voir, par préfixe, le ou les *clients*
    DataCite associés (un client = un repository : Zenodo, figshare,
    theses.fr, dépôt institutionnel…) ainsi que le *provider* (consortium
    ou organisme parent). Cible : évaluer s'il y a un mapping propre
    préfixe → client utilisable comme analogue du `name`/`member`
    Crossref dans `resolve_doi_prefixes`.
    """
    log.info("▶ prefixes-datacite : api.datacite.org/prefixes/{p} pour préfixes DataCite en base")

    rows = conn.execute(
        text("SELECT prefix FROM doi_prefixes WHERE ra = 'DataCite' ORDER BY prefix")
    ).fetchall()
    datacite_prefixes = [r[0] for r in rows]
    log.info(f"  {len(datacite_prefixes)} préfixes DataCite dans doi_prefixes")

    if not datacite_prefixes:
        log.warning("  aucun préfixe DataCite en base — phase 1 du chantier requise")
        return {}

    cache: dict[str, Any] = _load_json(DATACITE_PREFIX_CACHE, {})
    todo = [p for p in datacite_prefixes if p not in cache]
    log.info(f"  {len(cache)} en cache, {len(todo)} à résoudre")

    with httpx.Client(
        headers={"User-Agent": user_agent, "Accept": "application/vnd.api+json"},
        timeout=15.0,
    ) as client:
        for i, prefix in enumerate(todo, 1):
            try:
                resp = client.get(
                    f"{DATACITE_PREFIX_URL}/{prefix}",
                    params={"include": "clients,providers"},
                )
                if resp.status_code != 200:
                    log.warning(f"  [{i}/{len(todo)}] {prefix} : HTTP {resp.status_code}")
                    cache[prefix] = {"status": resp.status_code}
                else:
                    cache[prefix] = {"status": 200, "data": resp.json()}
                    log.info(f"  [{i}/{len(todo)}] {prefix} ✓")
            except Exception as exc:
                log.error(f"  [{i}/{len(todo)}] {prefix} : {exc!r}")
                cache[prefix] = {"error": repr(exc)}

            if i % 25 == 0:
                _save_json(DATACITE_PREFIX_CACHE, cache)
            time.sleep(SLEEP_BETWEEN_CALLS)

    _save_json(DATACITE_PREFIX_CACHE, cache)

    # Extraction client(s) + provider(s) par préfixe via la section `included`
    # du JSON:API. Un préfixe peut techniquement avoir plusieurs clients (cas
    # historiques de réallocation), on garde la liste pour audit.
    client_distribution: Counter = Counter()
    provider_distribution: Counter = Counter()
    multi_client_prefixes: list[dict[str, Any]] = []
    by_prefix: list[dict[str, Any]] = []
    parse_errors: list[str] = []

    for prefix, entry in cache.items():
        if entry.get("status") != 200:
            continue
        payload = entry.get("data") or {}
        try:
            relationships = payload.get("data", {}).get("relationships", {}) or {}
            client_ids = [
                c.get("id") for c in (relationships.get("clients", {}) or {}).get("data", []) or []
            ]
            provider_ids = [
                p.get("id")
                for p in (relationships.get("providers", {}) or {}).get("data", []) or []
            ]
            included_index = {
                (item.get("type"), item.get("id")): item
                for item in payload.get("included", []) or []
            }
            client_names = [
                (included_index.get(("clients", cid), {}).get("attributes", {}) or {}).get("name")
                for cid in client_ids
            ]
            provider_names = [
                (included_index.get(("providers", pid), {}).get("attributes", {}) or {}).get("name")
                for pid in provider_ids
            ]
            client_distribution.update(n for n in client_names if n)
            provider_distribution.update(n for n in provider_names if n)
            entry_summary = {
                "prefix": prefix,
                "client_ids": client_ids,
                "client_names": client_names,
                "provider_ids": provider_ids,
                "provider_names": provider_names,
            }
            by_prefix.append(entry_summary)
            if len(client_ids) > 1:
                multi_client_prefixes.append(entry_summary)
        except Exception as exc:
            parse_errors.append(f"{prefix}: {exc!r}")

    by_prefix.sort(key=lambda r: r["prefix"])

    summary = {
        "by_prefix": by_prefix,
        "client_distribution": dict(client_distribution.most_common()),
        "provider_distribution": dict(provider_distribution.most_common()),
        "multi_client_prefixes": multi_client_prefixes,
        "parse_errors": parse_errors,
        "stats": {
            "prefixes_total": len(datacite_prefixes),
            "prefixes_resolved": sum(1 for e in cache.values() if e.get("status") == 200),
            "distinct_clients": len(client_distribution),
            "distinct_providers": len(provider_distribution),
            "multi_client_prefixes_n": len(multi_client_prefixes),
        },
    }
    _save_json(DATA_DIR / "datacite_prefix_summary.json", summary)

    log.info(f"  clients distincts : {len(client_distribution)}")
    log.info(f"  providers distincts : {len(provider_distribution)}")
    log.info(f"  préfixes multi-clients : {len(multi_client_prefixes)}")
    log.info(f"  top clients : {client_distribution.most_common(15)}")
    log.info(f"  top providers : {provider_distribution.most_common(15)}")
    if parse_errors:
        log.warning(f"  parse errors : {len(parse_errors)} (cf. summary.parse_errors)")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--phase",
        choices=[
            "inventory",
            "resolve-ra",
            "publishers",
            "coherence",
            "sample-datacite",
            "prefixes-datacite",
            "all",
        ],
        default="all",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=100,
        help="nombre de DOIs DataCite à échantillonner (phase sample-datacite)",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    engine = get_sync_engine()
    with engine.connect() as conn:
        user_agent = _user_agent(get_polite_pool_email(conn))
        inventory: dict[str, Any] | None = None
        ra_cache: dict[str, str] = {}
        publisher_cache: dict[str, dict[str, Any]] = {}

        if args.phase in ("inventory", "all"):
            inventory = phase_inventory(conn)
        else:
            inventory = _load_json(DATA_DIR / "inventory.json", None)

        if args.phase in ("resolve-ra", "all"):
            if inventory is None:
                log.error("inventory manquant — lance d'abord --phase inventory")
                return 1
            ra_cache = phase_resolve_ra(inventory["prefix_samples"], user_agent)
        else:
            ra_cache = _load_json(RA_CACHE, {})

        if args.phase in ("publishers", "all"):
            publisher_cache = phase_publishers(ra_cache, user_agent)
        else:
            publisher_cache = _load_json(PUBLISHER_CACHE, {})

        if args.phase in ("coherence", "all"):
            if inventory is None:
                log.error("inventory manquant pour la phase coherence")
                return 1
            phase_coherence(inventory, ra_cache, publisher_cache)

        if args.phase in ("sample-datacite", "all"):
            phase_sample_datacite(conn, ra_cache, args.sample_size, user_agent)

        if args.phase in ("prefixes-datacite", "all"):
            phase_prefixes_datacite(conn, user_agent)

    log.info(f"✓ outputs dans {DATA_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
