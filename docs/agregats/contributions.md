# Contributions — cycle de vie

*À jour le 2026-09-06.*

Une `contribution` relie une personne à une publication : une ligne par couple `(publication_id, person_id)`. Elle est entièrement dérivée des contributions sources relevées dans chaque source (`source_contributions`) — jamais saisie, jamais modifiée à la main. La phase `persons` attribue une personne à chaque contribution source ; la phase `contributions` promeut ensuite les couples attestés et recompose leurs attributs.

Aucun objet de domaine ne lui correspond. Son vocabulaire de rôles et la correspondance des rôles propres à chaque source vivent dans `domain/publications/contribution_roles.py`.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `contributions` | Lien personne ↔ publication | `(publication_id, person_id)` unique, `author_position`, `roles`, `is_corresponding`, `in_perimeter` |
| `confirmed_source_contributions` | Contribution source épinglée par une décision humaine | `(source_contribution_id, person_id)` |
| `rejected_contributions` | Paire écartée durablement | `(publication_id, person_id)` |
| `contribution_structures` | Vue matérialisée : groupe de contributions sources ↔ structure | `(contribution_id, structure_id)` |
| `publication_structures` | Vue matérialisée : publication ↔ structure | `(publication_id, structure_id)` |

Les contributions sources elles-mêmes relèvent de la fiche [source_records](source_records.md), qui les décrit comme amont de cette table.

## Écriture par le pipeline

La table n'est écrite que par la phase `contributions` (`pipeline/transformation/publications/contributions/contributions.py`), qui enchaîne la construction proprement dite, la suppression par lots des publications restées sans aucune contribution, puis le rafraîchissement des compteurs de publications des revues et des éditeurs, qui dépendent du périmètre.

La construction (`build_contributions.py`) se rejoue sans dommage et converge vers le même état.

1. **Insertion et suppression.** Insère les couples attestés par au moins une contribution source portant une personne, en écartant ceux qu'une ligne de `rejected_contributions` interdit. Supprime les contributions qu'aucune source n'atteste plus.
2. **Recomposition des attributs**, depuis les contributions sources qui attestent chaque contribution : même publication par leur enregistrement source, même personne. `author_position` vient de la source la mieux classée ; `is_corresponding` et `in_perimeter` sont vrais dès qu'une source l'affirme ; `roles` est l'union triée des rôles relevés. La comparaison porte sur la différence, sans garde d'absence : un attribut qu'aucune source n'atteste plus **retombe** — un rôle disparu est retiré, un périmètre perdu repasse à faux.
3. **Report sur la publication.** `publications.in_perimeter` devient vrai si la publication porte au moins une contribution d'auteur dans le périmètre, rattachée à une personne non écartée, ou si c'est une thèse soutenue dans un établissement du périmètre. C'est exactement le prédicat qu'emploie le filtre de périmètre.
4. **Rafraîchissement** des deux vues matérialisées, sans bloquer les lectures.

## Écriture par l'API — édition manuelle

L'API n'écrit jamais `contributions`. L'édition manuelle agit sur les tables en amont, décrites côté [personnes](persons.md), et la construction suivante en tire les conséquences.

**Détacher une personne d'une publication** (`POST /api/persons/{id}/detach-contributions`) inscrit la paire dans `rejected_contributions`, détache les contributions sources concernées et supprime la contribution devenue orpheline. La paire ne sera plus jamais recréée.

**Épingler une contribution source** l'inscrit dans `confirmed_source_contributions`. La phase `persons` applique ces décisions avant toute nouvelle résolution, si bien que la personne portée par la contribution source — et donc la contribution promue — respecte le choix humain.

**Fusionner** deux personnes ou deux publications déduplique les contributions et les repointe vers la cible.

## Lecture par le pipeline

- `publications.in_perimeter`, posé à l'étape 4, est le drapeau que lit le filtre de périmètre dans tout le pipeline comme dans l'API.
- La vue `publication_structures` sert la ventilation par laboratoire, qui compte par structure sans jointure ni dédoublonnage.

## Lecture par l'API

| Usage | Ce qui est joint |
|---|---|
| Détail d'une publication | `contributions`, `persons` et `contribution_structures` : les auteurs, leurs structures et l'auteur de correspondance |
| Fiche et tableau de bord d'une personne | `contributions` et `publications` |
| Listes, facettes et statistiques | `publication_structures` pour la facette laboratoire ; les décomptes se limitent au périmètre |
