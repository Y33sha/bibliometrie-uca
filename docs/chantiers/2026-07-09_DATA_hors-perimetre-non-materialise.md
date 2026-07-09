# Chantier — Hors périmètre : ne pas matérialiser plutôt que masquer

Les types de documents hors périmètre (`OUT_OF_SCOPE_DOC_TYPES` : `peer_review`, `memoir`) sont matérialisés en `publications` puis masqués en aval — pas d'authorship canonique, absents des listings, facettes et stats via des filtres `doc_type` disséminés. Ce chantier remplace « matérialiser puis masquer » par « ne pas matérialiser » : une œuvre hors périmètre n'a jamais de publication, et cette règle s'applique en un seul endroit — la phase publications, qui crée et rattache les publications à partir des `source_publications` (module `reconcile_components`).

## Contexte

### Le masquage est fragile

L'exclusion repose sur `doc_type NOT IN OUT_OF_SCOPE_DOC_TYPES` répété à cinq endroits (`fetch_unlinked_authorships`, `_OOP_COMMON_WHERE`, `authorships_build`, `list.py`, `facets.py`). La publication existe pourtant en base ; seule une couche de filtres la rend invisible. Toute évolution de la liste doit toucher tous ces sites de façon cohérente sous peine de divergence.

### La bascule tardive du type échappe au masquage

Le `doc_type` canonique est résolu en `metadata_correction` (`map_doc_type`), et il peut changer d'un run à l'autre : une œuvre matérialisée sous un type in-scope bascule hors périmètre quand une source la retype. La phase publications ne dé-matérialise jamais sur changement de type — elle ne dissout une publication que lorsqu'un rapprochement de doublons la vide de ses `source_publications`. Une publication ainsi devenue hors périmètre reste donc matérialisée, avec des artefacts construits avant la correction : authorships canoniques (une publication `peer_review` peut porter des authorships), et attaches de personnes et formes de nom dérivées d'une `source_authorship` hors périmètre.

### La phase personnes est déjà correcte

La création (`fetch_unlinked_authorships`) comme l'attache hors-périmètre (`_OOP_COMMON_WHERE`) exigent déjà `publication_id IS NOT NULL` et une publication in-scope. Une `source_authorship` sur une SP sans publication ne crée ni n'attache aucune personne. Rien n'est à changer côté personnes.

## Décisions

- **Invariant : hors périmètre = jamais matérialisé.** `OUT_OF_SCOPE_DOC_TYPES` reste la source unique de la politique ; retirer un type de la liste (`memoir`) suffit à le réintégrer à la matérialisation.
- **La phase publications est le point d'application unique.** Une œuvre hors périmètre ne crée pas de publication et détache ses `source_publications` (`publication_id → NULL`) d'une publication existante ; vidée, celle-ci tombe dans la dissolution déjà câblée (`refresh_from_sources` supprime une publication sans SP).
- **Les filtres `doc_type` aval sont retirés une fois la dé-matérialisation en place.** L'absence de publication les rend morts ; les conserver ferait croire à tort que des publications hors périmètre existent.
- **La phase personnes reste inchangée.** Le GC `delete_empty_persons` (suppression des personnes sans `source_authorship`, hors RH) garde son critère : il désambiguïse les formes de nom, il ne vise pas les personnes sans authorship canonique — cas rendu sans objet par l'exclusion à la création.
- **Le stock existant est nettoyé par un passage dédié**, distinct du chemin forward.

## Phasage

### Phase 1 — Dé-matérialisation dans `refresh_from_sources`

Le `doc_type` canonique est arbitré par priorité de source dans `refresh_from_sources` ; le gate hors périmètre y vit donc, en frère du cas orphelin, plutôt que dans le planificateur pur `plan_reconciliation` qui devrait sinon dupliquer l'arbitrage de type. Les FK portent le reste : `source_publications.publication_id` (ON DELETE SET NULL) détache les SP, `authorships.publication_id` (ON DELETE CASCADE) emporte les authorships.

- [x] `refresh_from_sources` : après arbitrage du `doc_type`, si le type résolu est dans `OUT_OF_SCOPE_DOC_TYPES`, supprimer la publication (`repo.delete` + event `publication.deleted_out_of_scope`). Couvre la création (publication neuve raffinée puis supprimée) comme la bascule cross-run (survivant retypé).
- [ ] Tests : création d'une œuvre hors périmètre → aucune publication subsistante, SP orphelines ; bascule d'un type in-scope vers hors périmètre → publication supprimée, SP re-orphelinées, authorships purgées.

### Phase 2 — Retrait des filtres devenus morts

- [ ] Retirer `doc_type NOT IN OUT_OF_SCOPE_DOC_TYPES` de `fetch_unlinked_authorships`, `_OOP_COMMON_WHERE`, `authorships_build`.
- [ ] Retirer le filtre de `list.py` et `facets.py`.
- [ ] Statuer sur `OUT_OF_SCOPE_DOC_TYPES_SQL`, les familles `doc_type` et les libellés frontend : ce qui reste utile après suppression de la matérialisation.

### Phase 3 — Nettoyage du stock

- [ ] Oneshot : supprimer les publications hors périmètre existantes et leurs authorships, détacher leurs `source_publications` (`publication_id → NULL`) et re-orpheliner leurs `source_authorships` (`person_id → NULL`). Le re-orphelinage retire aussi leur contribution aux formes de nom des personnes.

## Questions ouvertes

- **Dépendants curatés d'une publication hors périmètre.** Une publication hors périmètre ne devrait porter ni `distinct_publications`, ni `apc_payments`, ni épinglage ; le stock peut en avoir. À la suppression, les FK décident en silence : `distinct_publications` part en cascade, `apc_payments` est détaché (SET NULL). Acceptable, ou faut-il un garde qui signale une suppression hors périmètre portant de la curation, avant de l'appliquer au stock ?
- **Garde-fou transitoire.** Le temps de valider la dé-matérialisation, une assertion ou un log en fin de phase publications (« aucune publication hors périmètre ne subsiste ») sécuriserait le retrait des filtres aval.
- **`memoir`.** La décision garde la liste telle quelle ; `memoir` suit donc `peer_review` et cesse d'être matérialisé, sauf retrait explicite de la liste.
