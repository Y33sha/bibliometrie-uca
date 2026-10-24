# Contributions — cycle de vie

*À jour le 2026-10-24.*

Une contribution réunit les contributions sources d'un même auteur dans une publication, une par enregistrement source au plus. Elle désigne la personne de cet auteur, ou aucune : une contribution sans personne est orpheline. Une personne a au plus une contribution par publication.

Le vocabulaire des rôles et la correspondance des rôles propres à chaque source sont dans `domain/publications/contribution_roles.py`. La décision de la personne d'une contribution est dans `domain/persons/group_matching.py`.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `contributions` | Contribution d'un auteur à une publication | `publication_id`, `person_id`, `resolution_mode`, `reference_position`, `roles`, `is_corresponding`, `perimeter_evidence`, `in_perimeter` |
| `aligned_source_contributions` | Contribution source alignée dans une contribution | `source_contribution_id`, `contribution_id`, `source_record_id`, `method`, `score`, `margin` |
| `confirmed_source_contributions` | Contribution source épinglée à une personne par une décision humaine | `(source_contribution_id, person_id)` |
| `rejected_contributions` | Paire (enregistrement source, personne) écartée durablement | `(source_record_id, person_id)` |
| `contribution_structures` | Vue matérialisée : contribution ↔ structure | `(contribution_id, structure_id)` |
| `publication_structures` | Vue matérialisée : publication ↔ structure | `(publication_id, structure_id)` |

`resolution_mode` dit comment la personne a été trouvée : épinglage, ORCID, compte HAL, IdRef, nom sans homonymie, initiales compatibles. Il est renseigné si et seulement si `person_id` l'est.

Les contributions sources relèvent de la fiche [source_contributions](source_contributions.md).

## Écriture par le pipeline

**`author_grouping` — alignement.** La phase aligne les contributions sources des enregistrements sources d'une publication : chaque auteur donne une contribution, et ses contributions sources entrent dans `aligned_source_contributions`, avec l'origine du lien (`method`). `reference_position` est la position de l'auteur dans la liste la plus longue. Une contribution garde son identifiant d'un run à l'autre : elle reprend celui de la contribution en base avec laquelle elle partage le plus de contributions sources. Les attributs (`roles`, `is_corresponding`, `perimeter_evidence`) sont l'union de ceux des contributions sources alignées, recomposés pour les contributions de la file `contribution_attributes_queue`. Une contribution rattachée dont les contributions sources changent entre dans la file `contribution_resolution_queue`.

**`persons` — personne.** La phase décide la personne des contributions orphelines et des contributions de `contribution_resolution_queue`, et crée les personnes des contributions du périmètre au nom inconnu ([phase persons](../pipeline/09-persons.md)). Elle retire leur personne aux contributions que la décision ne rattache plus. La purge retire leur personne aux contributions des personnes qu'elle supprime.

**`finalize` — données dérivées.** La phase reporte le périmètre sur les publications, rafraîchit les deux vues matérialisées et supprime les publications sans contribution rattachée ([phase finalize](../pipeline/10-finalize.md)).

## Écriture par l'API — décisions humaines

**Rejeter une contribution** (depuis la fiche d'une personne ou d'une publication) inscrit la paire dans `rejected_contributions`, retire la personne à sa contribution dans la publication, et retire les épinglages des contributions sources de la publication à cette personne. La décision de la personne écarte ensuite toute paire rejetée.

**Attribuer une contribution orpheline** épingle toutes ses contributions sources à la personne, ce qui rattache la contribution, puis recalcule le périmètre de la publication. Une personne peut être créée pour l'occasion.

**Épingler une contribution source** l'inscrit dans `confirmed_source_contributions`. La phase `persons` applique les épinglages avant toute décision : la contribution prend la personne épinglée.

**Rejeter un identifiant ou une forme de nom** met en file de redécision les contributions que cet identifiant ou cette forme rattachait.

**Fusionner deux personnes** reporte les contributions de l'absorbée sur la conservée. Une contribution de l'absorbée dans une publication où la conservée en a déjà une perd sa personne.

## Lecture

- `publications.in_perimeter`, posé par la phase `finalize`, est le drapeau que lit le filtre de périmètre, dans le pipeline comme dans l'API.
- La vue `publication_structures` sert la ventilation par laboratoire, qui compte par structure sans jointure ni dédoublonnage.

| Usage de l'API | Ce qui est joint |
|---|---|
| Détail d'une publication | `contributions`, `persons` et `contribution_structures` : les auteurs, leurs structures et l'auteur de correspondance |
| Fiche et tableau de bord d'une personne | `contributions` et `publications` |
| Contributions orphelines | `contributions` sans personne, du périmètre, sous un rôle d'auteur |
| Listes, facettes et statistiques | `publication_structures` pour la facette laboratoire ; les décomptes se limitent au périmètre |
