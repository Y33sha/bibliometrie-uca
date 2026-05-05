"""Règles métier pures spécifiques à la source WoS.

Interprétation des champs propres au schéma WoS Expanded API —
prédicats et extracteurs qui encapsulent la connaissance de la
sémantique WoS pour le reste du pipeline.
"""


def derive_wos_api_oa_status(journal_oas_gold: str | None) -> str | None:
    """Mapping minimal du signal OA WoS API → enum oa_status canonique.

    Le format API WoS n'expose pour le statut OA qu'un signal binaire
    `dynamic_data.cluster_related.publishing.publishing_information.
    journal_oas_gold` (`"Y"`/`"N"`/absent). Pas de nuance hybrid /
    bronze / green — WoS classe seulement « le journal est full-OA »
    vs « le reste ».

    Sémantique :
      - 'Y' → 'gold' (le journal est répertorié WoS comme full-OA)
      - autre (incl. 'N', None, vide) → None (délégation aux autres
        sources via best_oa_status — WoS ne connaît pas la voie
        green/hybrid/bronze, et un 'N' WoS ne signifie pas « closed »
        au sens canonique)

    NOTE: cette fonction est destinée à disparaître quand le chantier
    « journals comme source complémentaire » sera en place — le signal
    OA WoS est si pauvre que dès qu'on a la donnée journal côté
    pipeline (`journals.oa_model`), l'extraction et le mapping WoS
    pour OA deviennent superflus. À ce moment-là, on pourra retirer
    `journal_oas_gold` de l'extracteur et supprimer cette fonction.
    """
    if journal_oas_gold == "Y":
        return "gold"
    return None
