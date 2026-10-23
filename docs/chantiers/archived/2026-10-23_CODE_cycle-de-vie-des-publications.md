# Chantier — Cycle de vie des publications et des référentiels

## Contexte

Trois modules, dans deux phases, suppriment des publications :

- `lifecycle.refresh` supprime, après recalcul, une publication sans enregistrement source ou de type non admissible ;
- la tâche `publications.delete_without_sources` supprime les publications sans enregistrement source ;
- la tâche `contributions.purge_orphan_publications` supprime les publications sans contribution.

La phase `contributions` supprime aussi les monographies, revues et éditeurs vides, et recalcule les `publication_count`. Ces tâches la suivent, après la dernière suppression de publications. Dans `pipeline/graph.py`, cinq tâches déclarent une lecture du run précédent de `publications.id`, à cause de `purge_orphan_publications`.

La dissolution d'une publication, dans `reconcile_components.py`, dépend de l'ordre des requêtes :

- les paiements APC passent au successeur avant la suppression, car la clé étrangère d'`apc_payments` est `ON DELETE SET NULL` ;
- les dissolutions précèdent les survivants, pour libérer le DOI qu'un survivant reprend ;
- `refresh_from_sources` supprime la publication vidée sans le signaler à l'appelant.

## Décisions

- Un module détient le cycle de vie d'une publication. `refresh_from_sources` rend un verdict, et ce module supprime.
- Une publication existe si elle a au moins un enregistrement source, un type admissible et au moins une contribution. Le module du cycle de vie définit ces conditions. Une tâche les applique toutes après la phase `contributions`. `refresh_from_sources` vérifie l'enregistrement source et le type, et le module supprime immédiatement une publication qui y manque.
- La suppression des référentiels vides et le recalcul des `publication_count` relèvent de `publishing/`.
- Une opération `dissolve(publication, successeur)` du module du cycle de vie fait le report des dépendances, la redirection et la suppression.

## Phasage

### Phase 1 — Suppression d'une publication

- [x] Module du cycle de vie : seul module qui supprime une publication. fe1734afc
- [x] `dissolve(publication, successeur)` : report des paiements APC, redirection de l'identifiant, suppression. Appelée par `reconcile_components.py`. 2b6f11f1d
- [x] Verdict rendu par `refresh_from_sources`, suppression par le module du cycle de vie. 2b6f11f1d
- [x] Tâche de suppression après `contributions`, à la place de `delete_without_sources` et de `purge_orphan_publications`. fe1734afc

### Phase 2 — Référentiels vides et compteurs

- [x] Suppression des référentiels vides et recalcul des `publication_count` sous `publishing/`.
- [x] Recalcul de `addresses.publication_count` sous `structures/`. fe1734afc

### Phase 3 — Documentation

- [x] Mise à jour de `docs/pipeline`. fe1734afc
