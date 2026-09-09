"""Ordre des phases du pipeline.

Source de vérité unique de l'ordre d'exécution, consommée par l'orchestrateur (`run_pipeline`) et par la lecture d'observabilité (API, trame du ruban de l'interface). L'ordre de déclaration est l'ordre d'exécution. Module pur, sans I/O.
"""

from __future__ import annotations

PHASE_ORDER: tuple[str, ...] = (
    "extract",
    "resolve_ra",
    "fetch_missing",
    "fetch_stale",
    "fetch_truncated",
    "normalize",
    "affiliations",
    "publishers_journals",
    "metadata_correction",
    "publications",
    "persons",
    "authorships",
    "relations",
    "subjects",
    "countries",
    "oa_status",
)


PHASE_LIBELLES: dict[str, str] = {
    "extract": "Moissonnage des sources",
    "resolve_ra": "Résolution des agences d'enregistrement des DOI",
    "fetch_missing": "Recherche dans chaque source des documents trouvés dans les autres",
    "fetch_stale": "Rafraîchissement des documents les plus anciens",
    "fetch_truncated": "Récupération des listes d'auteurs tronquées",
    "normalize": "Mise en forme commune des documents moissonnés",
    "affiliations": "Rattachement des adresses aux structures",
    "publishers_journals": "Enrichissement des revues et des éditeurs",
    "metadata_correction": "Correction des métadonnées",
    "publications": "Regroupement des documents en publications",
    "persons": "Regroupement des signatures en personnes",
    "authorships": "Construction du lien entre publications et personnes",
    "relations": "Relations entre publications",
    "subjects": "Sujets et mots-clés",
    "countries": "Détection des pays",
    "oa_status": "Statut d'accès ouvert",
}
"""Ce que chaque phase produit, en une ligne lisible sans connaître le schéma."""


EXTRA_PHASES: frozenset[str] = frozenset({"relations", "subjects", "countries", "oa_status"})
"""Enrichissements terminaux, hors résolution d'entités : `--no-extras` les omet.

Rien en amont ne les lit — ni `persons`, ni `authorships` — et rien entre elles ne dépend d'une autre.
"""

if len(set(PHASE_ORDER)) != len(PHASE_ORDER):
    raise ValueError("Noms de phase dupliqués dans PHASE_ORDER")

if not EXTRA_PHASES <= set(PHASE_ORDER):
    raise ValueError("EXTRA_PHASES nomme une phase absente de PHASE_ORDER")

if set(PHASE_LIBELLES) != set(PHASE_ORDER):
    raise ValueError("PHASE_LIBELLES et PHASE_ORDER ne nomment pas les mêmes phases")
