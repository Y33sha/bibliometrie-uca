"""Règles métier pures spécifiques à la source WoS.

Interprétation des champs propres au schéma WoS Expanded API — prédicats et extracteurs qui encapsulent la connaissance de la sémantique WoS pour le reste du pipeline.

Les `dict[str, Any]` ici sont des payloads JSON bruts de l'API WoS (frontière dynamique avec une source externe, schéma non typé).
"""

from typing import Any


def is_wos_author_exploitable(author: dict[str, Any]) -> bool:
    """Indique si une entrée auteur WoS est utilisable côté pipeline.

    `daisng_id` (Distinct Author Identification System) est l'identifiant interne WoS de l'auteur. Pas utilisé côté DB (entité algorithmique WoS, non fiable) mais c'est un signal de **qualité** : son absence indique un parsing API WoS douteux (typiquement les enregistrements mal indexés ou incomplets). Combiné à l'exigence d'un `full_name`, le filtre garde une bonne approximation « auteur réel exploitable » et écarte les fragments d'erreur.
    """
    return bool(author.get("daisng_id") and author.get("full_name"))


# TODO: quand `journals.oa_model` sera disponible côté pipeline, ce mapping
# devient superflu (signal OA WoS trop pauvre) : retirer `journal_oas_gold`
# de l'extracteur et supprimer cette fonction.
def derive_wos_api_oa_status(journal_oas_gold: str | None) -> str | None:
    """Mapping du signal OA WoS API → enum oa_status canonique.

    Le format WoS n'expose qu'un signal binaire `journal_oas_gold` (`dynamic_data.cluster_related.publishing.publishing_information.journal_oas_gold`, `"Y"`/`"N"`/absent) : full-OA ou non, sans nuance hybrid / bronze / green.
      - 'Y' → 'gold' (journal répertorié WoS comme full-OA)
      - autre (incl. 'N', None, vide) → None (délégation aux autres sources via `best_oa_status` ; un 'N' WoS reste distinct de 'closed' au sens canonique)
    """
    if journal_oas_gold == "Y":
        return "gold"
    return None
