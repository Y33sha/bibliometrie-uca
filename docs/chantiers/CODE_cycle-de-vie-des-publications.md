# Chantier — Cycle de vie des publications et des référentiels

## Contexte

Trois modules, dans deux phases, suppriment des publications :

- `refresh_from_sources` (`reconciliation/refresh.py`) supprime une publication sans notice, ou de type non admissible ;
- le nœud `publications.delete_without_sources` supprime les publications sans notice ;
- le nœud `authorships.purge_orphan_publications` supprime les publications sans authorship.

La phase `authorships` supprime aussi les monographies, revues et éditeurs vides, et recalcule les `pub_count`. Ces nœuds la suivent, après la dernière suppression de publications. Dans `pipeline/graph.py`, cinq nœuds déclarent une lecture du run précédent de `publications.id`, à cause de `purge_orphan_publications`.

Les écrivains posent à la main les drapeaux de recalcul :

- `authorships_dirty` : `staging.py`, `signature_queries.py`, `metadata_correction_queries.py`, `reconciliation.py` et cinq scripts de `interfaces/cli/oneshot/`, chaque fois par la même requête ;
- `keys_dirty` : `source_publications.py`, `staging.py`, `perimeter_evidence.py`, `metadata_correction_queries.py`, `reconciliation.py`.

La dissolution d'une publication, dans `reconcile_components.py`, dépend de l'ordre des requêtes :

- les paiements APC passent au successeur avant la suppression, car la clé étrangère d'`apc_payments` est `ON DELETE SET NULL` ;
- les dissolutions précèdent les survivants, pour libérer le DOI qu'un survivant reprend ;
- `refresh_from_sources` supprime la publication vidée sans le signaler à l'appelant.

## Décisions

- Un module détient le cycle de vie d'une publication. `refresh_from_sources` rend un verdict, et ce module supprime.
- Une publication existe si elle a au moins une notice, un type admissible et au moins une authorship. Le module du cycle de vie définit ces conditions. Un nœud les applique toutes après la phase `authorships`. `refresh_from_sources` vérifie la notice et le type, et le module supprime immédiatement une publication qui y manque.
- La suppression des référentiels vides et le recalcul des `pub_count` relèvent de `publishing/`.
- Chaque drapeau de recalcul a une fonction de marquage, détenue par la phase qui le lit.
- Une opération `dissolve(publication, successeur)` du module du cycle de vie fait le report des dépendances, la redirection et la suppression.

## Phasage

### Phase 1 — Suppression d'une publication

- [ ] Module du cycle de vie : seul module qui supprime une publication.
- [ ] `dissolve(publication, successeur)` : report des paiements APC, redirection de l'identifiant, suppression. Appelée par `reconcile_components.py`.
- [ ] Verdict rendu par `refresh_from_sources`, suppression par le module du cycle de vie.
- [ ] Nœud de suppression après `authorships`, à la place de `delete_without_sources` et de `purge_orphan_publications`, et lectures `previous_run` de `publications.id` qui en découlent.

### Phase 2 — Référentiels vides et compteurs

- [ ] Suppression des référentiels vides et recalcul des `pub_count` sous `publishing/`, avec leurs nœuds.

### Phase 3 — Drapeaux de recalcul

- [ ] Fonction de marquage de `keys_dirty`.
- [ ] Fonction de marquage de `authorships_dirty`.

### Phase 4 — Documentation

- [ ] Mise à jour de `docs/pipeline`.

## Questions ouvertes

- Détenteur de `authorships_dirty` : la phase `author_grouping` le lit et l'efface. Le chantier d'alignement des auteurs redéfinit son rôle.
- Scripts de `interfaces/cli/oneshot/` qui posent `authorships_dirty` : appel de la fonction de marquage, ou laissés en l'état.
