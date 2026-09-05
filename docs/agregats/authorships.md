# Authorships — cycle de vie

*À jour le 2026-09-04.*

Une `authorship` relie une personne à une publication : une ligne par couple `(publication_id, person_id)`. Elle est entièrement dérivée des signatures relevées dans chaque source (`source_authorships`) — jamais saisie, jamais modifiée à la main. La phase `persons` attribue une personne à chaque signature ; la phase `authorships` promeut ensuite les couples attestés et recompose leurs attributs.

Aucun objet de domaine ne lui correspond. Son vocabulaire de rôles et la correspondance des rôles propres à chaque source vivent dans `domain/publications/authorship_roles.py`.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `authorships` | Lien personne ↔ publication | `(publication_id, person_id)` unique, `author_position`, `roles`, `is_corresponding`, `in_perimeter` |
| `source_authorships` | Signature relevée dans une source | `authorship_id`, `person_id`, `resolution_mode` |
| `confirmed_authorships` | Signature épinglée par une décision humaine | `(source_authorship_id, person_id)` |
| `rejected_authorships` | Paire écartée durablement | `(publication_id, person_id)` |
| `authorship_structures` | Vue matérialisée : authorship ↔ structure | `(authorship_id, structure_id)` |
| `publication_structures` | Vue matérialisée : publication ↔ structure | `(publication_id, structure_id)` |

Les signatures elles-mêmes relèvent de la fiche [source_publications](source_publications.md), qui les décrit comme amont de cette table.

## Écriture par le pipeline

La table n'est écrite que par la phase `authorships` (`application/pipeline/authorships/phase.py`), qui enchaîne la construction proprement dite, la suppression par lots des publications restées sans aucune authorship, puis le rafraîchissement des compteurs de publications des revues et des éditeurs, qui dépendent du périmètre.

La construction (`build_authorships.py`) se rejoue sans dommage et converge vers le même état. Cinq étapes :

1. **Insertion et suppression.** Insère les couples attestés par au moins une signature portant une personne, en écartant ceux qu'une ligne de `rejected_authorships` interdit. Supprime les authorships qu'aucune source n'atteste plus.
2. **Liaison.** Renseigne `source_authorships.authorship_id`, en une seule instruction valable pour toutes les sources.
3. **Recomposition des attributs.** `author_position` vient de la source la mieux classée ; `is_corresponding` et `in_perimeter` sont vrais dès qu'une source l'affirme ; `roles` est l'union triée des rôles relevés. La comparaison porte sur la différence, sans garde d'absence : un attribut qu'aucune source n'atteste plus **retombe** — un rôle disparu est retiré, un périmètre perdu repasse à faux.
4. **Report sur la publication.** `publications.in_perimeter` devient vrai si la publication porte au moins une authorship dans le périmètre, rattachée à une personne non écartée. C'est exactement le prédicat qu'emploie le filtre de périmètre.
5. **Rafraîchissement** des deux vues matérialisées, sans bloquer les lectures.

`run_pipeline --rebuild-authorships` vide d'abord la table : c'est la reconstruction de récupération, pas le mode courant.

Des `ANALYZE` sont intercalés entre les étapes, à l'intérieur de la transaction. Sans statistiques fraîches sur des colonnes tout juste peuplées, l'étape 3 part sur un plan d'exécution catastrophique — plusieurs heures là où il en faut quelques minutes.

## Écriture par l'API — édition manuelle

L'API n'écrit jamais `authorships`. L'édition manuelle agit sur les tables en amont, décrites côté [personnes](persons.md), et la construction suivante en tire les conséquences.

**Détacher une personne d'une publication** (`POST /api/persons/{id}/detach-authorships`) inscrit la paire dans `rejected_authorships`, détache les signatures concernées et supprime l'authorship devenue orpheline. La paire ne sera plus jamais recréée.

**Épingler une signature** l'inscrit dans `confirmed_authorships`. La phase `persons` applique ces décisions avant tout nouveau rapprochement, si bien que la personne portée par la signature — et donc l'authorship promue — respecte le choix humain.

**Fusionner** deux personnes ou deux publications déduplique les authorships et les repointe vers la cible.

## Lecture par le pipeline

- `publications.in_perimeter`, posé à l'étape 4, est le drapeau que lit le filtre de périmètre dans tout le pipeline comme dans l'API.
- La vue `publication_structures` sert la ventilation par laboratoire, qui compte par structure sans jointure ni dédoublonnage.

## Lecture par l'API

| Usage | Ce qui est joint |
|---|---|
| Détail d'une publication | `authorships`, `persons` et `authorship_structures` : les auteurs, leurs structures et l'auteur de correspondance |
| Fiche et tableau de bord d'une personne | `authorships` et `publications` |
| Listes, facettes et statistiques | `publication_structures` pour la facette laboratoire ; les décomptes se limitent au périmètre |

## Points d'attention

**Un attribut ne survit pas à la disparition de sa source.** L'étape 3 recompose sans garde d'absence : c'est ce qui rend la construction convergente, et c'est aussi ce qui fait qu'un rôle ou un périmètre cesse d'exister dès que plus aucune source ne l'atteste.

**Les `ANALYZE` intra-transaction sont nécessaires**, et documentés comme tels dans l'adaptateur. Les retirer fait s'effondrer le plan d'exécution de l'étape 3.

## Invariants métier

**Identité.** Le couple `(publication_id, person_id)` est unique, et `publication_id` ne peut être nul : l'authorship n'existe pas sans sa publication.

**Rejet durable.** Une paire inscrite dans `rejected_authorships` n'est jamais recréée par la construction.

**Périmètre.** `publications.in_perimeter` vaut « au moins une authorship dans le périmètre, portée par une personne non écartée ». Ce prédicat est recalculé à chaque construction.

**Convergence.** Insertion, suppression et recomposition se rejouent sans dommage : une exécution répétée aboutit au même état, sans reconstruction complète.
