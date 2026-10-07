"""Règles métier pures spécifiques à la source WoS.

Interprétation des champs propres au schéma WoS Expanded API — prédicats et extracteurs qui encapsulent la connaissance de la sémantique WoS pour le reste du pipeline.

Les `Mapping[str, JsonValue]` ici sont des payloads JSON bruts de l'API WoS (frontière dynamique avec une source externe, schéma non typé).

Les fonctions `parse_export_*` lisent les champs d'un export tabulé de l'interface WoS, où chaque colonne est désignée par une balise de deux lettres (`C1`, `RP`, `RI`…).
"""

import re
from collections.abc import Mapping

from domain.normalize import normalize_text
from domain.types import JsonValue

_EXPORT_SEPARATOR = "; "
_C1_ENTRY = re.compile(r"\[([^\]]*)\]\s*([^\[]*)")
_RP_NAME = re.compile(r"(?:^|;\s*)([^;]+?) \(corresponding author\)")


def split_export_list(value: str | None) -> list[str]:
    """Valeurs d'un champ d'export à valeurs multiples, séparées par « ; »."""
    return [v.strip() for v in (value or "").split(_EXPORT_SEPARATOR) if v.strip()]


def parse_export_addresses(c1: str | None) -> dict[str, list[str]]:
    """Adresses de chaque auteur, d'après le champ `C1` : nom complet normalisé → adresses.

    Une adresse que `C1` ne relie à aucun auteur (sans crochets) reste sans auteur.
    """
    addresses: dict[str, list[str]] = {}
    for names, address in _C1_ENTRY.findall(c1 or ""):
        address = address.strip().rstrip(";").strip()
        if not address:
            continue
        for name in split_export_list(names):
            addresses.setdefault(normalize_text(name), []).append(address)
    return addresses


def parse_export_corresponding(rp: str | None) -> set[str]:
    """Noms abrégés normalisés des auteurs correspondants, d'après le champ `RP`."""
    return {normalize_text(name) for name in _RP_NAME.findall(rp or "")}


def parse_export_researcher_ids(ri: str | None) -> dict[str, str]:
    """ResearcherID de chaque auteur, d'après le champ `RI` : nom complet normalisé → identifiant."""
    ids: dict[str, str] = {}
    for entry in split_export_list(ri):
        name, _, rid = entry.rpartition("/")
        if name.strip() and rid.strip():
            ids[normalize_text(name)] = rid.strip()
    return ids


def is_wos_author_exploitable(author: Mapping[str, JsonValue]) -> bool:
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
