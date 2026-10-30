# Contributions

*À jour le 2026-10-26.*

Une contribution est la participation d'une personne à une publication. Elle réunit les contributions sources de cette personne, au plus une par enregistrement source de la publication. Elle désigne la personne quand la [résolution des personnes](../pipeline/09-persons.md) l'a trouvée ; sinon, la contribution est orpheline. Une personne a au plus une contribution par publication.

Les contributions sources collectives et les doublons d'auteur restent hors de toute contribution, comme d'autres cas décrits par l'[alignement des auteurs](../pipeline/08-author-grouping.md#contributions-sources-écartées).

## Tables

Schéma PostgreSQL `publications`.

| Table | Contenu | Contrainte |
|---|---|---|
| `contributions` | Publication, personne et mode de rattachement (`resolution_mode`). `reference_position` : position de l'auteur dans la liste d'auteurs la plus longue. `roles`, `is_corresponding` et `perimeter_evidence` : union de ceux des contributions sources alignées. `in_perimeter` : vrai pour au moins un indice de périmètre | Une contribution par personne et par publication. `resolution_mode` est renseigné si et seulement si la personne l'est |
| `aligned_source_contributions` | Contribution source alignée dans une contribution, avec l'origine du lien (`method`). | Une contribution source par enregistrement source dans une contribution |

Les décisions humaines sur le rattachement sont décrites avec les [personnes](05-persons.md#décisions-humaines). Les vues matérialisées `contribution_structures` et `publication_structures` sont décrites avec les [données dérivées](09-donnees-derivees.md).

## Écriture

**Pipeline.**

- La phase [`author_grouping`](../pipeline/08-author-grouping.md) forme les contributions et recompose leurs attributs. Une contribution garde son identifiant d'une exécution à l'autre, et sa personne avec lui.
- La phase [`persons`](../pipeline/09-persons.md) décide la personne de chaque contribution.
- La phase [`finalize`](../pipeline/10-finalize.md) reporte le périmètre sur les publications et supprime les publications sans contribution rattachée.

**Administration** (`application/services/contributions.py`) :

- **Rejet**, depuis la fiche d'une personne ou d'une publication. La paire (publication, personne) entre dans `rejected_contributions`, et la personne perd sa contribution dans la publication.
- **Attribution d'une contribution orpheline** à une personne existante ou créée pour l'occasion. Les contributions sources de la contribution sont épinglées à la personne (`confirmed_source_contributions`).

Ces deux décisions recalculent aussitôt l'appartenance de la publication au périmètre. La vue `contribution_structures` est recalculée à l'exécution suivante de la phase `finalize`.
