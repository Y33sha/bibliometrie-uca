# Vocabulaire du code

*À jour le 2026-10-20.*

Une notion, un mot. Chaque notion a un mot dans les textes (docstrings, journaux, interface, documentation) et un identifiant dans le code. Les notions bibliométriques (affiliation, APC, collection HAL…) sont définies dans le [glossaire métier](../glossaire.md).

## Deux niveaux

Le niveau source décrit une entité telle qu'une source la donne. Le niveau consolidé réunit les descriptions des sources.

| Texte | Code | Ce que c'est |
|---|---|---|
| enregistrement source | `source_records` | Une publication telle qu'une source la décrit (HAL, OpenAlex, Crossref…). |
| publication | `publications` | Une publication du référentiel, construite à partir de ses enregistrements sources. Couvre aussi les jeux de données, les logiciels et les thèses. |
| contribution source | `source_contributions` | Un contributeur sur un enregistrement source, avec ses rôles et ses adresses. |
| contribution | `contributions` | Le lien consolidé entre une personne et une publication. |
| informations du contributeur | `contributor_information` | Le nom et les identifiants qu'une source donne pour un contributeur, partagés par ses contributions sources. |

## Personnes

| Texte | Code | Ce que c'est |
|---|---|---|
| personne | `persons` | Une personne du référentiel. |
| fiche RH | `hr_records` | La fiche de l'annuaire des ressources humaines rattachée à une personne. |
| identifiant de personne | `person_identifiers` | ORCID, idHAL, IdRef d'une personne, avec son statut. |
| forme de nom | `person_name_forms` | Une graphie du nom d'une personne, qui sert au rattachement. |
| contribution source confirmée | `confirmed_source_contributions` | Une contribution source que l'administration épingle sur une personne. |
| contribution rejetée | `rejected_contributions` | Une paire publication–personne que l'administration rejette. |

## Structures

| Texte | Code | Ce que c'est |
|---|---|---|
| structure | `structures` | Un laboratoire, un établissement, un organisme. |
| tutelle | `structure_parents` | Le lien d'une structure à la structure dont elle relève. |
| adresse | `addresses` | La chaîne d'affiliation d'une contribution source, aussi appelée signature. |
| périmètre | `perimeters` | Un ensemble de structures racines et leurs descendants. |

## Pipeline

| Texte | Code |
|---|---|
| moissonnage | *harvest* (`harvest`, `harvest_by_person`, `Harvester`) |
| phase | `Phase`, une unité du run dans les journaux et l'administration |
| tâche | `Task`, un nœud du graphe du run (`pipeline/graph.py`) |
| store | `*Store` : l'accès SQL à une entité dans le pipeline |
| repository | `Pg*Repository` : un adaptateur de `infrastructure/` |

## Identifiants

Les identifiants Python gardent les noms d'entité entiers : `publication_id`, `source_record`. Les alias de table du SQL restent courts : leur portée est la requête qui les déclare.
