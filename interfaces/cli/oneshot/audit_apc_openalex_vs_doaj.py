# STATUS: oneshot (2026-05-26)
"""
Audit (pure lecture) : sur les revues ayant un APC posé à la fois par
OpenAlex Sources (colonne `journals.apc_amount`) et par DOAJ (clé
``APC amount`` du payload, posée par l'import CSV historique ou par
le sub-step `enrich_journals_from_doaj` livré en Phase 4), quel est
l'écart entre les deux montants ?

Sert à trancher la Phase 7 du chantier
`METIER_pipeline-publishers-journals` : choisir entre

  (a) garder OpenAlex comme source primaire APC ;
  (b) basculer le sub-step OpenAlex pour ne plus écrire `apc_amount`,
      laisser DOAJ comme seule source du chiffre ;
  (c) garder les deux dimensions séparées en base et exposer les
      divergences en UI.

Ne fait AUCUNE écriture en base.

Usage :
    python -m interfaces.cli.oneshot.audit_apc_openalex_vs_doaj
"""

from __future__ import annotations

import os
import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("audit_apc_openalex_vs_doaj", os.path.dirname(__file__))

# Buckets d'écart relatif (en valeur absolue). Bornes inclusives à droite.
RELATIVE_BUCKETS: list[tuple[str, float]] = [
    ("identical (=0%)", 0.0),
    ("≤ 1%", 0.01),
    ("≤ 5%", 0.05),
    ("≤ 10%", 0.10),
    ("≤ 20%", 0.20),
    ("≤ 50%", 0.50),
    ("> 50%", float("inf")),
]

# Deux formats de payload coexistent en base pour la clé "APC amount" :
#   - Format API (sub-step Phase 4) : un seul chiffre, devise dans "APC currency".
#     Ex. {"APC amount": "2477", "APC currency": "USD"}
#   - Format CSV récent (import bootstrap) : string composite multi-devises,
#     pas de "APC currency". Ex. {"APC amount": "3390 EUR; 4090 USD; 2990 GBP"}
# Le parser ci-dessous gère les deux.
_COMPOSITE_TOKEN = re.compile(r"([\d.,]+)\s*([A-Z]{3})")


def parse_amount_simple(raw: str) -> Decimal | None:
    """Parse un montant nu (``"2500"``, ``"2500.00"``, ``"2,500"``, ``"$2500"``).

    Retourne ``None`` si rien d'exploitable (chaînes type ``"No APC"``,
    vide, ou ``"0"``).
    """
    cleaned = re.sub(r"[^\d.,\-]", "", raw).replace(",", ".")
    if not cleaned or cleaned in {".", "-"}:
        return None
    try:
        val = Decimal(cleaned)
    except InvalidOperation:
        return None
    return val if val > 0 else None


def parse_doaj_apc(amount_raw: str | None, currency_raw: str | None) -> dict[str, Decimal]:
    """Extrait un mapping ``{currency_iso3: amount}`` depuis le payload DOAJ.

    - Format API : ``amount_raw="2477"``, ``currency_raw="USD"`` →
      ``{"USD": Decimal("2477")}``.
    - Format CSV récent : ``amount_raw="3390 EUR; 4090 USD; 2990 GBP"``
      → ``{"EUR": 3390, "USD": 4090, "GBP": 2990}``. La devise séparée est ignorée.
    - Cas dégénérés (``"No APC"``, ``"Free"``, ``"0"``) → dict vide.
    """
    if not amount_raw:
        return {}
    # Tente le format composite d'abord (regex matche aussi le format API
    # si la devise séparée est concaténée — mais ici on a juste un nombre).
    composite = _COMPOSITE_TOKEN.findall(amount_raw)
    if composite:
        out: dict[str, Decimal] = {}
        for price_raw, cur in composite:
            val = parse_amount_simple(price_raw)
            if val is not None:
                out[cur.upper()] = val
        if out:
            return out
    # Fallback format API : montant nu + devise séparée.
    val = parse_amount_simple(amount_raw)
    if val is None:
        return {}
    cur = (currency_raw or "").strip().upper()
    if not cur:
        return {}
    return {cur: val}


def bucket_relative(diff_rel: float) -> str:
    """Range un écart relatif (|x|) dans un bucket nommé."""
    for label, upper in RELATIVE_BUCKETS:
        if diff_rel <= upper:
            return label
    return RELATIVE_BUCKETS[-1][0]


def main() -> int:
    engine = get_sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    j.id,
                    j.title,
                    j.apc_amount      AS oa_amount,
                    j.apc_currency    AS oa_currency,
                    j.doaj_payload->>'APC amount'   AS doaj_amount_raw,
                    j.doaj_payload->>'APC currency' AS doaj_currency
                FROM journals j
                WHERE j.apc_amount IS NOT NULL
                  AND j.doaj_payload IS NOT NULL
                  AND j.doaj_payload->>'APC amount' IS NOT NULL
                ORDER BY j.id
            """)
        ).all()
        total = len(rows)
        log.info("%d revues avec APC OpenAlex ET DOAJ amount renseigné dans le payload.", total)
        if total == 0:
            log.warning(
                "Audit vide. Vérifier que le pipeline `enrich_journals_from_openalex` "
                "a tourné ET qu'au moins un import DOAJ (CSV ou API) a alimenté le payload."
            )
            return 0

        comparable = 0
        no_overlap = 0  # OA currency absente de la dict DOAJ
        doaj_unparseable = 0
        amounts_diff_abs: list[Decimal] = []
        amounts_diff_rel: list[float] = []
        bucket_counter: Counter[str] = Counter()
        currency_pairs: Counter[tuple[str, str]] = Counter()
        # Top divergences pour inspection oculaire (same currency, |Δrel| max).
        top_divergences: list[tuple[float, int, str, Decimal, Decimal, str]] = []

        for row in rows:
            oa = Decimal(row.oa_amount)
            doaj_prices = parse_doaj_apc(row.doaj_amount_raw, row.doaj_currency)
            if not doaj_prices:
                doaj_unparseable += 1
                continue
            oa_cur = (row.oa_currency or "").strip().upper() or "?"
            doaj_currencies = "|".join(sorted(doaj_prices)) or "?"
            currency_pairs[(oa_cur, doaj_currencies)] += 1
            doaj = doaj_prices.get(oa_cur)
            if doaj is None:
                no_overlap += 1
                continue
            comparable += 1
            diff_abs = abs(oa - doaj)
            ref = max(oa, doaj)
            diff_rel = float(diff_abs / ref) if ref > 0 else 0.0
            amounts_diff_abs.append(diff_abs)
            amounts_diff_rel.append(diff_rel)
            bucket_counter[bucket_relative(diff_rel)] += 1
            top_divergences.append((diff_rel, row.id, row.title, oa, doaj, oa_cur))

        log.info("─" * 70)
        log.info("Bilan sur %d revues candidates :", total)
        log.info("  doaj_unparseable (rien d'extractible du payload)     : %d", doaj_unparseable)
        log.info("  no_overlap (OA cur absente des devises DOAJ listées) : %d", no_overlap)
        log.info("  comparable (OA cur présente côté DOAJ)               : %d", comparable)
        log.info("─" * 70)

        if currency_pairs:
            log.info("Distribution OA cur → devises listées par DOAJ :")
            for (oa_c, doaj_c), n in currency_pairs.most_common():
                tag = "✓" if oa_c in doaj_c.split("|") else "✗"
                log.info("  %s  OA=%-4s  DOAJ=%-15s  %d", tag, oa_c, doaj_c, n)
            log.info("─" * 70)

        if comparable > 0:
            log.info("Distribution des écarts relatifs (comparable only) :")
            for label, _upper in RELATIVE_BUCKETS:
                n = bucket_counter.get(label, 0)
                pct = (100.0 * n / comparable) if comparable else 0.0
                log.info("  %-18s  %4d  (%.1f %%)", label, n, pct)

            sorted_rel = sorted(amounts_diff_rel)
            n = len(sorted_rel)
            median = sorted_rel[n // 2]
            p90 = sorted_rel[int(n * 0.9)] if n >= 10 else sorted_rel[-1]
            p99 = sorted_rel[int(n * 0.99)] if n >= 100 else sorted_rel[-1]
            mean_abs = sum(amounts_diff_abs) / n
            log.info("─" * 70)
            log.info(
                "Écart relatif (comparable) : médiane=%.1f%% p90=%.1f%% p99=%.1f%%",
                100 * median,
                100 * p90,
                100 * p99,
            )
            log.info("Écart absolu moyen : %.2f", mean_abs)
            log.info("─" * 70)

            # Top 10 divergences pour inspection
            log.info("Top 10 divergences (comparable, classées par |Δrel|) :")
            top_divergences.sort(reverse=True)
            for diff_rel, jid, title, oa, doaj, cur in top_divergences[:10]:
                log.info(
                    "  #%d  '%s'  OA=%s%s  DOAJ=%s%s  Δrel=%.0f%%",
                    jid,
                    title[:50],
                    oa,
                    cur,
                    doaj,
                    cur,
                    100 * diff_rel,
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
