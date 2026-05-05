"""Règles métier pures spécifiques à la source OpenAlex.

Interprétation des champs propres au schéma OpenAlex — prédicats et
extracteurs qui encapsulent la connaissance de la sémantique OpenAlex
pour le reste du pipeline.
"""

# Statuts OA exposés par OpenAlex (`open_access.oa_status`). OpenAlex
# utilise les mêmes labels que notre enum canonique, plus `diamond`
# qu'ils ont commencé à exposer en 2023. Le set est utilisé pour
# valider/dispatcher dans `map_openalex_oa_status`.
_KNOWN_OA_STATUSES = frozenset({"gold", "diamond", "hybrid", "bronze", "green", "closed"})


def map_openalex_oa_status(raw: str | None) -> str | None:
    """Mapping OpenAlex `open_access.oa_status` → enum oa_status canonique.

    OpenAlex utilise les mêmes labels que notre enum (gold, diamond,
    hybrid, bronze, green, closed). Mapping identitaire pour les
    valeurs connues, plus :

    - `None` ou `""` → `None` (OpenAlex ne s'est pas prononcé ; on
      délègue aux autres sources via `best_oa_status` côté
      `refresh_from_sources`. Cas rare : OpenAlex peuple presque
      toujours `open_access.oa_status` quand `open_access` est
      présent. Cohérent avec la sémantique HAL/ScanR : on ne mappe
      pas un champ vide à `closed`.)
    - valeur inattendue → `'unknown'` (catch-all si OpenAlex introduit
      un nouveau label qu'on n'a pas encore intégré au mapping).
    """
    if not raw:
        return None
    if raw in _KNOWN_OA_STATUSES:
        return raw
    return "unknown"
