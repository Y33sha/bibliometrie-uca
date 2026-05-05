"""Règles métier pures spécifiques à la source OpenAlex.

Interprétation des champs propres au schéma OpenAlex — prédicats et
extracteurs qui encapsulent la connaissance de la sémantique OpenAlex
pour le reste du pipeline.
"""

from domain.doc_types import map_doc_type

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


def correct_openalex_doc_type(
    raw_type: str | None,
    *,
    is_theses_fr: bool,
    landing_page_url: str | None,
) -> str:
    """Détermine le doc_type canonique d'une publication associée à un
    work OpenAlex, en corrigeant les imprécisions OpenAlex à partir de
    signaux source-spécifiques.

    OpenAlex classe parfois de manière imprécise les ressources hébergées
    par certaines sources canoniques (theses.fr, dumas, …). Cette fonction
    applique les overrides connus avant de retomber sur le mapping
    OpenAlex standard.

    Cascade :
      1. is_theses_fr → 'thesis' (theses.fr fait autorité sur les thèses
         françaises, peu importe la classification OpenAlex)
      2. raw_type=='dissertation' + URL en `dumas.*` → 'memoir'
         (DUMAS héberge des mémoires de master, classés à tort en
         'dissertation' par OpenAlex)
      3. sinon → `map_doc_type(raw_type, 'openalex')` (mapping standard)

    À noter : cette fonction sert à la **création/lookup de la table
    canonique `publications`**. La colonne `source_publications.doc_type`
    stocke quant à elle le raw OpenAlex sans correction, par convention
    (`work.get("type")` lu directement dans `insert_openalex_document`).

    À étendre avec le chantier suppléments : ajouter signaux DOI/title
    pour reclasser les figshare/Zenodo « Additional file… » en `'other'`.

    Note d'architecture : ces règles sont **conceptuellement
    source-agnostiques** (« theses.fr fait toujours autorité sur les
    thèses », « dumas → mémoire », « Zenodo supplément → other »).
    En pratique seul OpenAlex provoque ces erreurs de doc_type
    aujourd'hui (parce qu'il moissonne ces sources sans en respecter
    la nomenclature), donc on garde la fonction ici. Si un jour une
    autre source produit le même type d'imprécisions, on pourra
    promouvoir la fonction (ou ses helpers) dans `domain/doc_types.py`.
    """
    if is_theses_fr:
        return "thesis"
    if (raw_type or "").lower() == "dissertation":
        if landing_page_url and "dumas." in landing_page_url:
            return "memoir"
    return map_doc_type(raw_type, "openalex")
