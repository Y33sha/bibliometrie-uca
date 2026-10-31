"""Lecture des payloads Web of Science par la normalisation : conventions des champs de l'API Expanded et de l'export tabulé.

Les payloads de l'API sont les objets JSON bruts, sans schéma typé. Les fonctions `parse_export_*` lisent les champs d'un export tabulé de l'interface, où une balise de deux lettres désigne chaque colonne (`C1`, `RP`, `RI`…).
"""

import re
from collections.abc import Mapping

from domain.normalize import normalize_text
from domain.types import JsonValue

_EXPORT_SEPARATOR = "; "
_C1_ENTRY = re.compile(r"\[([^\]]*)\]\s*([^;\[]*)")
_RP_NAME = re.compile(r"(?:^|;\s*)([^;]+?) \(corresponding author\)")


def split_export_list(value: str | None) -> list[str]:
    """Renvoie les valeurs d'un champ d'export à valeurs multiples, séparées par « ; »."""
    return [v.strip() for v in (value or "").split(_EXPORT_SEPARATOR) if v.strip()]


def parse_export_addresses(c1: str | None) -> dict[str, list[str]]:
    """Renvoie les adresses de chaque auteur, d'après le champ `C1` : nom complet normalisé → adresses.

    Une adresse de `C1` sans crochets reste sans auteur.
    """
    addresses: dict[str, list[str]] = {}
    for names, address in _C1_ENTRY.findall(c1 or ""):
        address = address.strip()
        if not address:
            continue
        for name in split_export_list(names):
            addresses.setdefault(normalize_text(name), []).append(address)
    return addresses


def parse_export_corresponding(rp: str | None) -> set[str]:
    """Renvoie les noms abrégés normalisés des auteurs correspondants, d'après le champ `RP`."""
    return {normalize_text(name) for name in _RP_NAME.findall(rp or "")}


def parse_export_researcher_ids(ri: str | None) -> dict[str, str]:
    """Renvoie le ResearcherID de chaque auteur, d'après le champ `RI` : nom complet normalisé → identifiant."""
    ids: dict[str, str] = {}
    for entry in split_export_list(ri):
        name, _, rid = entry.rpartition("/")
        if name.strip() and rid.strip():
            ids[normalize_text(name)] = rid.strip()
    return ids


def is_wos_author_usable(author: Mapping[str, JsonValue]) -> bool:
    """Renvoie vrai si une entrée auteur WoS est exploitable : elle a un nom complet et un `daisng_id`.

    Le `daisng_id` est l'identifiant interne de l'auteur chez WoS, calculé et peu fiable : il reste hors de la base. Son absence signale une entrée mal lue, sur un record mal indexé ou incomplet.
    """
    return bool(author.get("daisng_id") and author.get("full_name"))
