# Périmètres — cycle de vie

*À jour le 2026-09-04.*

Un périmètre nomme un ensemble de structures en ne désignant que ses **racines** : tout ce qui descend d'une racine par une relation de tutelle en fait partie. C'est ce qui permet de dire « l'UCA » sans énumérer ses laboratoires, et de suivre automatiquement une réorganisation. L'ensemble ainsi obtenu détermine ce que le pipeline interroge aux sources, quelles adresses il considère comme internes, et pour quelles signatures il crée des personnes.

`domain/perimeters/perimeter.py` garantit qu'un périmètre a un code et un nom non vides. La descente récursive, elle, vit dans le SQL.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `perimeters` | Le périmètre et ses racines | `code` (unique), `name`, `root_structure_ids` (tableau d'identifiants de structures) |
| `perimeter_structures` | L'ensemble complet, calculé d'avance | `perimeter_id`, `structure_id` — les racines et tous leurs descendants |

`perimeter_structures` est le résultat de la descente récursive dans `structure_relations`, en suivant la relation `est_tutelle_de`. Deux clés de la table `config` désignent les périmètres en service : `perimeter_extraction`, qui cadre l'extraction et les affiliations, et `perimeter_persons`, qui cadre la création des personnes.

## Écriture par l'API — édition manuelle

Routeur `interfaces/api/routers/perimeters.py`, services dans `application/services/perimeters/`, adaptateur `PgPerimeterRepository`.

`create_perimeter` impose un code unique. `update_perimeter` remplace le nom et les racines — celles-ci en bloc, jamais élément par élément. `delete_perimeter` refuse de supprimer un périmètre que la configuration du pipeline référence.

Toute édition qui peut déplacer la frontière rejoue `refresh_perimeter_structures` : celles qui touchent aux racines, mais aussi celles qui touchent aux structures ou à leurs relations de tutelle, du côté des services de structures.

## Écriture par le pipeline

Le pipeline ne modifie jamais un périmètre. Il recalcule `perimeter_structures` à deux moments : au démarrage, avant que l'extraction ne lise le périmètre, puis au début de la phase `affiliations`. L'ensemble est ainsi à jour chaque fois qu'il sert à décider.

## Lecture par le pipeline

- **Extraction** : `get_extraction_api_ids` fournit aux extracteurs les structures du périmètre d'extraction, qui déterminent ce qu'il faut demander à chaque source.
- **Appartenance au périmètre** : la phase `affiliations` tient pour internes les structures présentes dans `perimeter_structures` pour le périmètre d'extraction.
- **Création des personnes** : `get_persons_structure_ids` lit l'ensemble du périmètre `perimeter_persons`.

## Lecture par l'API

Port `application/ports/read_models/perimeters_queries.py`, adaptateur `PgPerimetersQueries` dans `infrastructure/read_models/perimeters.py`. L'adaptateur du pipeline, `PgPerimeterStructuresQueries`, vit à part dans `infrastructure/pipeline/perimeter.py`.

`list_perimeters_with_structures` rend chaque périmètre avec ses structures racines et le nombre de structures atteintes après descente. Le routeur des structures expose par ailleurs l'appartenance d'une structure à un périmètre.

## Points d'attention

**Les racines sont un tableau d'identifiants sans clé étrangère.** Rien en base n'empêche `root_structure_ids` de désigner une structure supprimée. La cohérence tient aux points d'écriture — édition d'un périmètre, suppression d'une structure, ajout ou retrait d'une tutelle — qui nettoient les racines et recalculent l'ensemble.

## Invariants métier

**Composition d'un périmètre.** `perimeter_structures` contient les racines déclarées dans `perimeters.root_structure_ids` et tous leurs descendants par `structure_relations.est_tutelle_de`. Cette règle est écrite une seule fois, dans la requête de `refresh_perimeter_structures` ; `get_perimeter_structure_ids` se contente de lire la table. L'objet de domaine ne la porte pas.
