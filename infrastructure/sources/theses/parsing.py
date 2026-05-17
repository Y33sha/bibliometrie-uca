"""Pure functions de parsing pour l'extraction theses.fr.

Vit à côté de `extract_theses.py` (wiring HTTP). Ne fait aucun I/O.
"""

from __future__ import annotations

import argparse


def build_query(ppn: str, status: str | None = None) -> str:
    """Construit la chaîne de recherche pour l'API theses.fr.

    Filtre par PPN d'établissement (`etabSoutenancePpn:(ppn)`) + statut
    optionnel (`status:(soutenue|enCours)`).
    """
    q = f"etabSoutenancePpn:({ppn})"
    if status:
        q += f" AND status:({status})"
    return q


def extract_theses_id(these: dict) -> str:
    """Extrait l'identifiant unique d'une thèse (champ `id`).

    Pour les thèses soutenues, c'est le NNT (ex: `2021UCFAC022`) ;
    pour les thèses en cours, c'est un id theses.fr (ex: `s367812`).
    Les deux vivent dans la même colonne `id` de l'API recherche.
    """
    return these.get("id", "")


def extract_doi(these: dict) -> str | None:
    """Extrait le DOI s'il est présent et non vide, sinon `None`."""
    doi = these.get("doi")
    if doi and isinstance(doi, str) and doi.strip():
        return doi.strip()
    return None


def resolve_statuses(args: argparse.Namespace) -> list[str]:
    """Détermine les statuts à extraire depuis les args CLI `--soutenues` / `--en-cours`.

    Aucun des deux flags (ou les deux) → on extrait les deux statuts.
    Un seul flag → on n'extrait que celui-ci.
    """
    if args.soutenues and args.en_cours:
        return ["soutenue", "enCours"]
    if args.soutenues:
        return ["soutenue"]
    if args.en_cours:
        return ["enCours"]
    return ["soutenue", "enCours"]
