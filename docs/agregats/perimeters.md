# Périmètres — cycle de vie

*À jour le 2026-09-06.*

Un périmètre nomme un ensemble de structures en ne désignant que ses **racines** : tout ce qui descend d'une racine par une relation de tutelle en fait partie. C'est ce qui permet de dire « l'UCA » sans énumérer ses laboratoires, et de suivre automatiquement une réorganisation. L'ensemble ainsi obtenu détermine ce que le pipeline interroge aux sources, quelles adresses il considère comme internes, et pour quelles contributions sources il crée des personnes.

`domain/perimeters/perimeter.py` garantit qu'un périmètre a un code et un nom non vides. La descente récursive, elle, vit dans le SQL.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `perimeters` | Le périmètre et ses racines | `code` (unique), `name`, `root_structure_ids` (tableau d'identifiants de structures) |
| `perimeter_structures` | L'ensemble complet, calculé d'avance | `perimeter_id`, `structure_id` — les racines et tous leurs descendants |

`perimeter_structures` est le résultat de la descente récursive dans `structure_parents`. Deux clés de la table `config` désignent les périmètres en service : `perimeter_extraction`, qui cadre l'extraction et les affiliations, et `perimeter_persons`, qui cadre la création des personnes.

## Écriture par l'API — édition manuelle

Routeur `interfaces/api/routers/perimeters.py`, services dans `application/services/perimeters/`, adaptateur `PgPerimeterRepository`.

`create_perimeter` impose un code unique. `update_perimeter` remplace le nom et les racines — celles-ci en bloc, jamais élément par élément. `delete_perimeter` refuse de supprimer un périmètre que la configuration du pipeline référence.

Toute édition qui peut déplacer la frontière rejoue `refresh_perimeter_structures` : celles qui touchent aux racines, mais aussi celles qui touchent aux structures ou à leurs relations de tutelle, du côté des services de structures.

## Écriture par le pipeline

Le pipeline ne modifie jamais un périmètre. Il recalcule `perimeter_structures` au démarrage, avant la première phase.

## Lecture par le pipeline

- **Extraction** : `get_extraction_api_ids` fournit aux extracteurs les structures du périmètre d'extraction, qui déterminent ce qu'il faut demander à chaque source.
- **Appartenance au périmètre** : la phase `affiliations` tient pour internes les structures présentes dans `perimeter_structures` pour le périmètre d'extraction.
- **Création des personnes** : `get_persons_structure_ids` lit l'ensemble du périmètre `perimeter_persons`.

## Lecture par l'API

Lecture `infrastructure/read_models/perimeters/`, classe `PerimetersQueries`. La clôture des périmètres appartient au pipeline (`PerimeterQueries`, dans `pipeline/transformation/structures/perimeter.py`) ; l'API l'appelle par le port `PerimeterStructuresQueries`.

`list_perimeters_with_structures` rend chaque périmètre avec ses structures racines et le nombre de structures atteintes après descente. Le routeur des structures expose par ailleurs l'appartenance d'une structure à un périmètre.

## Points d'attention

**Les racines sont un tableau d'identifiants sans clé étrangère.** Rien en base n'empêche `root_structure_ids` de désigner une structure supprimée. La cohérence tient aux points d'écriture — édition d'un périmètre, suppression d'une structure, ajout ou retrait d'une tutelle — qui nettoient les racines et recalculent l'ensemble.
