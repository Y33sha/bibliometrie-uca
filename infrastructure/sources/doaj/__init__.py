"""Client API DOAJ + mapper API→format CSV.

Endpoint : ``GET {base}/search/journals/issn:{issn}`` (v3, redirige vers
v4). Retourne un wrapper ``{total, results[]}`` ; ``total == 0`` = revue
absente de DOAJ.

Choix non-orthodoxe assumé (cf. fiche
`METIER_pipeline-publishers-journals.md`, Phase 4) : le payload stocké
en base n'est pas la réponse API brute, mais un dict aux **mêmes clés
que le dump CSV DOAJ** historiquement importé par
`interfaces/cli/imports/import_doaj_csv.py`. Ça préserve les
consommateurs existants (front qui hardcode les clés CSV dans
`READABLE_DOAJ_FIELDS`, audit APC prévu en Phase 7 qui requête
`doaj_payload->>'APC amount'`) au prix d'un mapping manuel ici.

Divergences API/CSV conservées telles quelles dans le mapper (pas
d'effort de normalisation supplémentaire vers le format CSV historique) :

- ``Country of publisher`` reste l'ISO-2 brut de l'API
  (``bibjson.publisher.country`` = ``"US"``), là où le CSV mettait le
  nom long (``"United States"``).
- ``Languages…`` reste la liste de codes ISO-639-1 jointe (``"EN|FR"``),
  là où le CSV mettait les noms longs.

Une seule clé est ajoutée par rapport au CSV : ``"DOAJ id"`` (= ``id``
racine de l'API), nécessaire pour reconstruire l'URL de la fiche DOAJ
côté front en Phase 6 (``https://doaj.org/toc/{id}``).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import requests

DOAJ_SEARCH_PATH = "search/journals/issn:{issn}"


def fetch_doaj_journal(
    issn: str,
    *,
    base_url: str,
    user_agent: str,
    logger: logging.Logger,
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """GET sur l'API DOAJ pour un ISSN.

    Retourne le 1er document du tableau ``results`` (= record DOAJ
    complet : ``{id, last_updated, bibjson, ...}``), ``None`` si la
    revue n'est pas dans DOAJ (``total == 0``) ou si la requête échoue.

    Si ``total > 1`` (improbable — un ISSN identifie 1 journal), on
    prend le 1er résultat et on loggue un warning.
    """
    url = f"{base_url.rstrip('/')}/{DOAJ_SEARCH_PATH.format(issn=quote(issn))}"
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        body = resp.json()
    except requests.RequestException as e:
        logger.warning("DOAJ fetch failed for ISSN %s : %s", issn, e)
        return None

    results = body.get("results") if isinstance(body, dict) else None
    if not results:
        return None
    if len(results) > 1:
        logger.warning("DOAJ : %d résultats pour ISSN %s (1er retenu)", len(results), issn)
    first = results[0]
    return first if isinstance(first, dict) else None


def build_doaj_user_agent(mailto: str) -> str:
    """User-Agent courtois pour les requêtes DOAJ (contact email)."""
    return f"bibliometrie-uca/1.0 (mailto:{mailto})"


# ── Mapping API → format CSV ────────────────────────────────────────


_CSV_SEP = "|"
"""Séparateur historique du dump CSV DOAJ pour les champs multi-valeur (subjects, languages)."""


def _join_terms(items: list[Any] | None, key: str | None = None) -> str | None:
    """Joint une liste de valeurs (str ou dicts) avec ``|``.

    - ``items=None`` ou liste vide → ``None``.
    - ``key`` fournie → ne garde que les dicts et extrait ``item[key]``.
      Les entrées non-dict sont ignorées (tolérance payload abîmé).
    - ``key`` None → str(item), filtre les vides.
    """
    if not items:
        return None
    parts: list[str] = []
    for it in items:
        if key is not None:
            if not isinstance(it, dict):
                continue
            v = it.get(key)
        else:
            v = it
        if v is None:
            continue
        s = str(v).strip()
        if s:
            parts.append(s)
    return _CSV_SEP.join(parts) if parts else None


def to_csv_shape(api_doc: dict[str, Any]) -> dict[str, str]:
    """Transforme un record DOAJ API en dict aux clés CSV.

    Filtre les clés vides (cohérent avec ``_clean_row`` de l'import CSV
    historique) — un consommateur SQL ``doaj_payload->>'X'`` retourne
    ``NULL`` quand X est absent, ce qui simplifie le code aval.

    Valeurs systématiquement stringifiées (``"2477"`` plutôt que
    ``2477``) pour rester homogène avec le dump CSV stocké tel quel.
    """

    def _as_dict(v: Any) -> dict[str, Any]:
        return v if isinstance(v, dict) else {}

    def _as_list(v: Any) -> list[Any]:
        return v if isinstance(v, list) else []

    bibjson = _as_dict(api_doc.get("bibjson"))
    publisher = _as_dict(bibjson.get("publisher"))
    apc = _as_dict(bibjson.get("apc"))
    ref = _as_dict(bibjson.get("ref"))
    licenses = _as_list(bibjson.get("license"))

    out: dict[str, str] = {}

    def put(k: str, v: Any) -> None:
        if v is None:
            return
        s = str(v).strip()
        if s:
            out[k] = s

    put("Journal title", bibjson.get("title"))
    put("Journal URL", ref.get("journal"))
    put("Publisher", publisher.get("name"))
    put("Country of publisher", publisher.get("country"))
    put("Subjects", _join_terms(bibjson.get("subject"), key="term"))
    put("Languages in which the journal accepts manuscripts", _join_terms(bibjson.get("language")))
    put(
        "When did the journal start to publish all content using an open license?",
        bibjson.get("oa_start"),
    )
    if licenses and isinstance(licenses[0], dict):
        put("Journal license", licenses[0].get("type"))

    has_apc = apc.get("has_apc")
    if isinstance(has_apc, bool):
        put("Journal article processing charges (APCs)", "Yes" if has_apc else "No")
    max_prices = apc.get("max")
    if isinstance(max_prices, list) and max_prices and isinstance(max_prices[0], dict):
        # Le CSV historique ne stocke qu'un montant — on prend le 1er
        # (DOAJ peut lister plusieurs devises pour les revues qui
        # facturent en USD ET EUR).
        put("APC amount", max_prices[0].get("price"))
        put("APC currency", max_prices[0].get("currency"))

    # Clé inédite vs CSV — nécessaire pour reconstruire l'URL fiche DOAJ
    # côté front (Phase 6) : `https://doaj.org/toc/{id}`.
    put("DOAJ id", api_doc.get("id"))

    return out
