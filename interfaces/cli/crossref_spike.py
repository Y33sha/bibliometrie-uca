#!/usr/bin/env python3
"""Spike CrossRef — phase 0 du chantier ``docs/chantiers/crossref.md``.

Échantillonne ~100 DOI UCA stratifiés (année × doc_type × signature de
sources) et interroge l'API CrossRef pour mesurer ce qui sera réellement
exploitable en phase 1 :

- couverture ORCID par tranche d'année et au global
- couverture des relations (preprint, version, has-dataset, etc.)
- présence des champs notables (license, funder, ROR, abstract, references)
- distribution des ``type`` CrossRef (amorce de ``_SOURCE_MAPS["crossref"]``)
- conflits potentiels ``doc_type`` canonique vs CrossRef brut
- gain potentiel pour la phase 3 (promotion ORCID) — combien d'ORCIDs
  CrossRef croisent ``person_identifiers`` UCA et dans quel statut

Réponses brutes mises en cache local (idempotent : relancer ne refait
pas les appels). Rapport markdown dans ``docs/chantiers/crossref-spike.md``.

Usage::

    python -m interfaces.cli.crossref_spike --sample-size 100
    python -m interfaces.cli.crossref_spike --report-only  # ré-analyse seule
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

import requests

from infrastructure import PROJECT_ROOT
from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger

CONTACT_EMAIL = "laura.le_coz@uca.fr"
USER_AGENT = f"BibliometrieUCA-spike/0.1 (mailto:{CONTACT_EMAIL})"
CACHE_DIR = PROJECT_ROOT / "docs" / "chantiers" / "crossref-spike-data"
REPORT_PATH = PROJECT_ROOT / "docs" / "chantiers" / "crossref-spike.md"
API_BASE = "https://api.crossref.org/works"
RATE_DELAY = 0.05  # 50 ms entre appels — polite pool grâce au mailto

YEAR_BUCKETS: list[tuple[str, int, int]] = [
    ("≤2009", 0, 2009),
    ("2010-2014", 2010, 2014),
    ("2015-2019", 2015, 2019),
    ("2020-2024", 2020, 2024),
    ("≥2025", 2025, 9999),
]
NO_YEAR_BUCKET = "no_year"

log = setup_logger("crossref_spike", os.path.dirname(__file__))


# ── Sampling ──────────────────────────────────────────────────────


def bucket_for_year(year: int | None) -> str:
    if year is None:
        return NO_YEAR_BUCKET
    for label, lo, hi in YEAR_BUCKETS:
        if lo <= year <= hi:
            return label
    return NO_YEAR_BUCKET


def sample_dois(cur: Any, sample_size: int) -> list[dict[str, Any]]:
    """Tire un échantillon stratifié par (bucket année × doc_type × signature sources).

    On parcourt les cellules en round-robin pour maximiser la diversité.
    Seed RNG fixe (42) pour reproductibilité d'une exécution à l'autre.
    """
    cur.execute(
        """
        SELECT p.id, p.doi, p.pub_year, p.doc_type,
               array_agg(DISTINCT sp.source ORDER BY sp.source) AS sources
        FROM publications p
        JOIN source_publications sp ON sp.publication_id = p.id
        WHERE p.doi IS NOT NULL
          AND p.doi <> ''
        GROUP BY p.id
        """
    )
    rows = cur.fetchall()
    log.info(f"{len(rows)} publications avec DOI éligibles au tirage")

    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        sources = r["sources"] or []
        sig = ",".join(sources) if sources else "(none)"
        key = (bucket_for_year(r["pub_year"]), r["doc_type"] or "(none)", sig)
        buckets[key].append(
            {
                "id": r["id"],
                "doi": r["doi"],
                "pub_year": r["pub_year"],
                "doc_type": r["doc_type"],
                "sources": sources,
            }
        )

    log.info(f"{len(buckets)} cellules de stratification")

    rng = random.Random(42)
    cell_keys = sorted(buckets.keys())
    for k in cell_keys:
        rng.shuffle(buckets[k])

    sample: list[dict[str, Any]] = []
    while len(sample) < sample_size:
        progress = False
        for k in cell_keys:
            if buckets[k]:
                sample.append(buckets[k].pop())
                progress = True
                if len(sample) >= sample_size:
                    break
        if not progress:
            break
    return sample


def get_known_orcids(cur: Any) -> dict[str, str]:
    """Map ORCID (16 chars) → status pour tous les ORCIDs en base."""
    cur.execute("SELECT id_value, status FROM person_identifiers WHERE id_type = 'orcid'")
    return {r["id_value"]: r["status"] for r in cur.fetchall()}


# ── CrossRef fetch ─────────────────────────────────────────────────


def cache_path_for(doi: str) -> Path:
    safe = urllib.parse.quote(doi, safe="").replace("%", "_")
    return CACHE_DIR / f"{safe}.json"


def fetch_crossref(doi: str) -> dict[str, Any]:
    """Appel API CrossRef, avec cache disque. Retourne le ``message`` ou un
    stub ``{"_status": ...}`` si erreur/404."""
    cp = cache_path_for(doi)
    if cp.exists():
        with cp.open() as f:
            return json.load(f)

    url = f"{API_BASE}/{urllib.parse.quote(doi, safe='/()')}"
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 404:
            data: dict[str, Any] = {"_status": "not_found"}
        elif r.status_code != 200:
            data = {"_status": f"http_{r.status_code}", "_text": r.text[:300]}
        else:
            payload = r.json()
            data = payload.get("message", {})
            data["_status"] = "ok"
    except Exception as e:
        data = {"_status": "exception", "_error": str(e)}

    cp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    time.sleep(RATE_DELAY)
    return data


# ── Analyse ────────────────────────────────────────────────────────


def normalize_orcid(raw: str) -> str:
    """Extrait l'ORCID 16 chars depuis la forme URL CrossRef."""
    return raw.rstrip("/").split("/")[-1]


def detect_ror(authors: list[dict[str, Any]]) -> bool:
    for a in authors:
        for aff in a.get("affiliation", []) or []:
            for idobj in aff.get("id", []) or []:
                if idobj.get("id-type", "").upper() == "ROR":
                    return True
    return False


def detect_authenticated_orcid(authors: list[dict[str, Any]]) -> bool:
    for a in authors:
        if a.get("authenticated-orcid") is True:
            return True
    return False


def analyze(
    samples: list[dict[str, Any]], known_orcids: dict[str, str]
) -> dict[str, Any]:
    """Calcule les métriques agrégées sur les samples enrichis."""
    by_bucket: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total": 0,
            "found": 0,
            "not_found": 0,
            "error": 0,
            "with_orcid": 0,
            "n_authors": 0,
            "n_orcid": 0,
            "with_authenticated": 0,
            "with_relation": 0,
            "with_license": 0,
            "with_funder": 0,
            "with_ror": 0,
            "with_abstract": 0,
            "with_references": 0,
        }
    )
    type_dist: Counter[str] = Counter()
    relation_types: Counter[str] = Counter()
    doc_type_pairs: list[dict[str, Any]] = []
    orcid_match: Counter[str] = Counter()

    for s in samples:
        bucket = bucket_for_year(s["pub_year"])
        b = by_bucket[bucket]
        b["total"] += 1
        msg = s.get("crossref") or {}
        status = msg.get("_status", "unknown")

        if status == "not_found":
            b["not_found"] += 1
            continue
        if status != "ok":
            b["error"] += 1
            continue
        b["found"] += 1

        crtype = msg.get("type")
        if crtype:
            type_dist[crtype] += 1
            doc_type_pairs.append(
                {
                    "doi": s["doi"],
                    "canonical": s["doc_type"],
                    "crossref_type": crtype,
                    "crossref_subtype": msg.get("subtype"),
                }
            )

        authors = msg.get("author", []) or []
        b["n_authors"] += len(authors)
        n_orcid = 0
        for a in authors:
            orcid = a.get("ORCID")
            if not orcid:
                continue
            n_orcid += 1
            norm = normalize_orcid(orcid)
            if norm in known_orcids:
                orcid_match[known_orcids[norm]] += 1
            else:
                orcid_match["unknown_in_uca"] += 1
        b["n_orcid"] += n_orcid
        if n_orcid > 0:
            b["with_orcid"] += 1
        if detect_authenticated_orcid(authors):
            b["with_authenticated"] += 1

        if msg.get("relation"):
            b["with_relation"] += 1
            for rt in msg["relation"]:
                relation_types[rt] += 1

        if msg.get("license"):
            b["with_license"] += 1
        if msg.get("funder"):
            b["with_funder"] += 1
        if detect_ror(authors):
            b["with_ror"] += 1
        if msg.get("abstract"):
            b["with_abstract"] += 1
        if msg.get("reference"):
            b["with_references"] += 1

    return {
        "by_bucket": dict(by_bucket),
        "type_distribution": dict(type_dist.most_common()),
        "relation_types": dict(relation_types.most_common()),
        "doc_type_pairs": doc_type_pairs,
        "orcid_match": dict(orcid_match),
    }


# ── Report ─────────────────────────────────────────────────────────


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "—"


def write_report(metrics: dict[str, Any], requested: int, sampled: int) -> None:
    bucket_order = [label for label, _, _ in YEAR_BUCKETS] + [NO_YEAR_BUCKET]
    lines: list[str] = []
    lines.append("# Spike CrossRef — résultats phase 0\n")
    lines.append(
        f"_Échantillon : {sampled} DOI tirés (sur {requested} demandés). "
        f"Voir [chantiers/crossref.md](crossref.md) pour le contexte._\n"
    )

    # Statut API
    lines.append("## Statut des appels API\n")
    lines.append("| Bucket | total | trouvés | introuvables | erreurs |")
    lines.append("|---|---:|---:|---:|---:|")
    grand: dict[str, int] = defaultdict(int)
    for label in bucket_order:
        b = metrics["by_bucket"].get(label)
        if not b:
            continue
        for k, v in b.items():
            grand[k] += v
        lines.append(
            f"| {label} | {b['total']} | {b['found']} | {b['not_found']} | {b['error']} |"
        )
    lines.append(
        f"| **total** | **{grand['total']}** | **{grand['found']}** | "
        f"**{grand['not_found']}** | **{grand['error']}** |"
    )
    lines.append("")

    # ORCID
    lines.append("## Couverture ORCID par bucket\n")
    lines.append(
        "| Bucket | trouvés | publis ≥1 ORCID | % publis | auteurs | auteurs ORCID | % auteurs | "
        "publis avec authenticated-orcid:true |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for label in bucket_order:
        b = metrics["by_bucket"].get(label)
        if not b or b["found"] == 0:
            continue
        lines.append(
            f"| {label} | {b['found']} | {b['with_orcid']} | {_pct(b['with_orcid'], b['found'])} | "
            f"{b['n_authors']} | {b['n_orcid']} | {_pct(b['n_orcid'], b['n_authors'])} | "
            f"{b['with_authenticated']} |"
        )
    lines.append(
        f"| **total** | **{grand['found']}** | **{grand['with_orcid']}** | "
        f"**{_pct(grand['with_orcid'], grand['found'])}** | **{grand['n_authors']}** | "
        f"**{grand['n_orcid']}** | **{_pct(grand['n_orcid'], grand['n_authors'])}** | "
        f"**{grand['with_authenticated']}** |"
    )
    lines.append("")

    # Champs
    lines.append("## Présence des autres champs (par bucket)\n")
    lines.append("| Bucket | trouvés | relation | license | funder | ROR | abstract | references |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for label in bucket_order:
        b = metrics["by_bucket"].get(label)
        if not b or b["found"] == 0:
            continue
        lines.append(
            f"| {label} | {b['found']} | {b['with_relation']} | {b['with_license']} | "
            f"{b['with_funder']} | {b['with_ror']} | {b['with_abstract']} | {b['with_references']} |"
        )
    lines.append(
        f"| **total** | **{grand['found']}** | **{grand['with_relation']}** | "
        f"**{grand['with_license']}** | **{grand['with_funder']}** | **{grand['with_ror']}** | "
        f"**{grand['with_abstract']}** | **{grand['with_references']}** |"
    )
    lines.append("")

    # Types
    lines.append("## Distribution des `type` CrossRef\n")
    if metrics["type_distribution"]:
        for t, n in metrics["type_distribution"].items():
            lines.append(f"- `{t}` : {n}")
    else:
        lines.append("_Aucun type observé._")
    lines.append("")

    # Relations
    lines.append("## Types de relations observés\n")
    if metrics["relation_types"]:
        for r, n in metrics["relation_types"].items():
            lines.append(f"- `{r}` : {n}")
    else:
        lines.append("_Aucune relation observée dans l'échantillon._")
    lines.append("")

    # ORCID match
    lines.append("## Match des ORCIDs CrossRef avec `person_identifiers` UCA\n")
    lines.append(
        "_Pour chaque ORCID rencontré dans CrossRef, on regarde s'il existe "
        "côté UCA et son statut._\n"
    )
    if metrics["orcid_match"]:
        for status, n in sorted(
            metrics["orcid_match"].items(), key=lambda x: -x[1]
        ):
            lines.append(f"- `{status}` : {n}")
    else:
        lines.append("_Aucun ORCID CrossRef à comparer._")
    lines.append("")

    # doc_type pairs
    pairs = metrics["doc_type_pairs"]
    lines.append("## doc_type canonique vs `type` CrossRef\n")
    lines.append(
        f"_{len(pairs)} paires observées. Sert d'amorce au mapping `_SOURCE_MAPS[\"crossref\"]`._\n"
    )
    pair_counter: Counter[tuple[str | None, str | None, str | None]] = Counter()
    for p in pairs:
        pair_counter[(p["canonical"], p["crossref_type"], p.get("crossref_subtype"))] += 1
    lines.append("| canonique | CrossRef type | subtype | n |")
    lines.append("|---|---|---|---:|")
    for (canon, crtype, subt), n in pair_counter.most_common():
        lines.append(f"| {canon or '—'} | {crtype or '—'} | {subt or '—'} | {n} |")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines) + "\n")


# ── Entry point ───────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Ne pas refaire les appels API ; ré-analyser depuis le cache",
    )
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"Cache : {CACHE_DIR}")
    log.info(f"User-Agent : {USER_AGENT}")

    with get_connection() as conn:
        with conn.cursor() as cur:
            samples = sample_dois(cur, args.sample_size)
            known_orcids = get_known_orcids(cur)

    log.info(f"Échantillon final : {len(samples)} DOI")
    log.info(f"ORCIDs connus côté UCA : {len(known_orcids)}")

    if args.report_only:
        for s in samples:
            cp = cache_path_for(s["doi"])
            if cp.exists():
                with cp.open() as f:
                    s["crossref"] = json.load(f)
            else:
                s["crossref"] = {"_status": "missing_in_cache"}
    else:
        for i, s in enumerate(samples, 1):
            log.info(f"[{i}/{len(samples)}] {s['doi']}")
            s["crossref"] = fetch_crossref(s["doi"])

    metrics = analyze(samples, known_orcids)
    write_report(metrics, requested=args.sample_size, sampled=len(samples))
    log.info(f"Rapport écrit : {REPORT_PATH}")


if __name__ == "__main__":
    main()
