# Structures, périmètres et adresses

*À jour le 2026-10-26.*

Une structure est un établissement (université, école, CHU, organisme de recherche), un laboratoire, un site ou un service administratif. Les structures forment un référentiel saisi à la main. Un périmètre est un ensemble de structures, désigné par ses racines. Une adresse est le texte d'affiliation qu'une source donne pour une contribution source. Le pipeline reconnaît des structures dans les adresses, et en déduit l'appartenance des contributions sources au périmètre.

Schéma PostgreSQL `structures`.

## Structures

| Table | Contenu | Contrainte |
|---|---|---|
| `structures` | Code court (`uca`, `cnrs`), nom, acronyme, type, identifiants [ROR](../glossaire.md#ror) et RNSR, collection HAL, identifiants dans les sources (`api_ids`) | Code unique, ROR unique |
| `structure_parents` | Tutelle : rattachement d'une structure à une structure parente | Le graphe des tutelles est sans cycle |
| `structure_name_forms` | Formes de nom qui désignent la structure dans une adresse | Une forme de six caractères ou moins exige une frontière de mot |
| `idref_structures` | Structure d'un laboratoire partenaire de thèse, désigné par son PPN IdRef | |

Les options `is_word_boundary`, `is_excluding` et `requires_context_of` règlent la [reconnaissance des formes de nom](../pipeline/04-affiliations.md) dans les adresses.

## Périmètres

| Table | Contenu | Contrainte |
|---|---|---|
| `perimeters` | Code, nom, structures racines (`root_structure_ids`) | Code unique |
| `perimeter_structures` | Racines du périmètre et tous leurs descendants par les tutelles | |

Deux clés de la [configuration](08-ref-et-ops.md) désignent les périmètres en service. `perimeter_extraction` désigne les structures interrogées au moissonnage et l'appartenance des contributions sources au périmètre. `perimeter_persons` désigne le périmètre de création des personnes.

`root_structure_ids` est un tableau sans clé étrangère. La suppression d'une structure la retire des racines de chaque périmètre.

## Adresses

| Table | Contenu | Contrainte |
|---|---|---|
| `addresses` | Texte brut et texte normalisé, pays retenus (`countries`), nombre de publications | Une adresse par texte normalisé |
| `address_structures` | Rattachement d'une adresse à une structure. `matched_form_id` : forme de nom détectée, vide pour un rattachement saisi à la main. `is_confirmed` : vide en attente, vrai si confirmé, faux si rejeté | Un rattachement par adresse et structure |
| `address_country_candidates` | Pays proposé pour une adresse par un moyen de détection : source, nom de pays, institution, ville, saisie manuelle | Un pays par adresse et par moyen |

Les contributions sources sont reliées à leurs adresses par `source_contribution_addresses` ([enregistrements sources](02-sources.md)).

## Écriture

**Administration :**

- Structures, tutelles et formes de nom (`application/services/structures.py`). Une suppression de structure ou un changement de tutelle recalcule `perimeter_structures`.
- Périmètres (`application/services/perimeters.py`). Une création ou une modification recalcule `perimeter_structures`. La suppression d'un périmètre désigné par la configuration est refusée.
- Rattachements des adresses et pays saisis à la main (`application/services/addresses.py`). Le périmètre des contributions sources, des contributions et des publications concernées est recalculé aussitôt. La vue `contribution_structures` est recalculée à l'exécution suivante de la phase `finalize`.

**Pipeline :**

- Le pipeline recalcule `perimeter_structures` avant sa première phase.
- La phase [`normalize`](../pipeline/03-normalize.md) crée les adresses et les pays qu'en donnent les sources.
- La phase [`affiliations`](../pipeline/04-affiliations.md) écrit les rattachements détectés et `idref_structures`. Elle conserve les rattachements confirmés ou saisis à la main.
- La phase `publications` compte les publications des adresses.
- La phase [`countries`](../pipeline/11-enrichissements.md#pays-des-adresses-countries) détecte et retient les pays des adresses.
