# Chantier — Background jobs pour les endpoints longs

Commencé le 2026-06-05

## Contexte

Certaines actions admin en écriture peuvent franchir le timeout reverse-proxy (~60 s) ou rendre l'UI peu réactive. L'audit (Phase 1) distingue **deux causes indépendantes**, qui appellent **deux leviers différents** :

- **Refresh matview disproportionné.** Depuis le passage de `source_authorship_structures` (SAS) et `authorship_structures` (AS) en matview (cf. `2026-06-04_DATA_perimeter-materialise.md`), toute action admin touchant une affiliation déclenchait un `REFRESH` **complet** de la chaîne SAS → AS : ~3-4 s pour SAS (SELECT ~2,3 s sur 8,3 M `source_authorship_addresses`) + ~2 s pour AS = ~5-8 s par action, alors que le delta peut être minuscule. Le refresh full est massivement disproportionné — et async-ifier le même refresh gaspilleur ne le règle pas.
- **Propagation / merge dont le coût croît avec le volume.** Rejeter une adresse associée à beaucoup d'auteurs (jusqu'à 67k source_authorships), batcher des pays sur beaucoup d'adresses, fusionner deux grosses revues. Là, le travail est intrinsèquement long → vrai candidat background-job.

Le fix no-op sur `review_structure_link` (commit `9376bbd`) règle déjà le cas fréquent (confirmer une auto-détection = no-op, pas de propagation), et `batch_review` amortit le refresh à **un seul couple** par lot (un seul `propagate_in_perimeter_for_addresses` sur l'union des adresses dont la contribution change). Restaient le coût unitaire du refresh (traité Phase 2) et les vrais gros volumes.

## Audit (Phase 1) — actions en écriture UI

39 endpoints POST/PUT/PATCH/DELETE, trois classes de coût.

**A — POINT (écriture ponctuelle, sync OK, ≈25 endpoints).** Aucun refresh matview, aucune propagation : toutes les CRUD `structures` (8) et `perimeters` (4), writes personnes ponctuels (`add/update identifier`, `reject_person`, `update_person_name`, `detach_name_form`), `mark_*_distinct` (2), `exclude_authorship`, `update_publisher`, `update_config`, auth. → rien à faire.

**B — MATVIEW (refresh full ~5-8 s/action, indépendant du delta).** Traité en Phase 2.

| Endpoint | Coût |
|---|---|
| `review_address`, `batch_review` | refresh SAS (~3-4 s) + AS (~2 s) **si** la contribution périmètre change. `batch_review` = 1 couple pour tout le lot (déjà amorti) ; `review_address` = 1 couple par appel. |
| `assign_orphan_authorship`, `batch_assign_orphan_authorships` | refresh AS (~2 s), full même pour 1 SA |
| `detach_authorships` | + refresh SAS/AS si des adresses sont touchées |

**C — VOLUME (propagation/merge/bulk, coût ∝ volume).**

| Endpoint | Volume potentiel |
|---|---|
| `batch_set_country_by_filter` | jusqu'à **475k adresses** (filtre vide → `WHERE TRUE`, [countries.py:89](../../../application/addresses/countries.py#L89)) + cascade jumelles + 3 UPDATE de masse (sa/sp/publications). Déjà partiellement en BG task. |
| `review_address` (adresse populaire) | `propagate_in_perimeter_for_addresses` → jusqu'à **67k** source_authorships |
| `merge_persons` / `merge_publications` / `merge journals` / `merge publishers` | transfert FK O(N) (authorships, source_*, name_forms…). Pas de refresh matview. `merge publishers` = pire cas (cascade de merges de journaux à titre partagé). |
| `update_journal` (changement de type) | `requalify_publications_for_journal` boucle `refresh_from_sources` sur chaque publication du journal ([journals.py:213](../../../application/journals.py#L213)) |

**Réserve correctness (hors scope perf).** `update_perimeter` / `add_perimeter_structure` modifient `perimeters.structure_ids` mais ne rafraîchissent pas `perimeter_structures` → périmètre stale jusqu'au prochain run pipeline. À traiter à part.

## Phasage

### Phase 1 — Audit

- [x] Recenser les 39 endpoints en écriture, classer POINT / MATVIEW / VOLUME (ci-dessus).

### Phase 2 — Désamorcer le refresh matview (classe B) — `38418fbf`

- [x] Retirer les 4 refresh SAS/AS sur action admin (review, assign orphelin simple + batch).
- [x] Acter pipeline-only : matviews maintenues par le pipeline (`populate_affiliations` + `build_authorships`). `in_perimeter` reste recalculé en direct depuis `address_structures` (synchrone) ; seule l'agrégation `*_structures` retarde d'un run — sans risque de fausse correction (ces liens ne se corrigent pas depuis l'UI).
- [x] Mettre à jour la doc données (`05-authorships-et-sources.md`).
- *(Alternative debounce écartée — cf. Questions ouvertes.)*

### Phase 3 — Garde-fou `batch_set_country` (classe C, pire cas)

- [x] Serveur : refuser un filtre vide (→ 400 au lieu de `WHERE TRUE` sur ~475k adresses). `f74969a8`
- [x] Frontend : masquer « Ajouter à tout le filtre » sans filtre actif. `c6999139`

### Phase 4 — Décorréler les écritures longues (classe C)

- [x] Propagation `in_perimeter` des reviews d'affiliation → `BackgroundTasks` fire-and-forget (`bg_propagate_in_perimeter_sync`, connexion DB propre ; la réponse ne lit que `address_structures`, synchrone). `3b19adaf`
- [x] **Merges — analyse de volume : pas un sujet perf.** `merge_duplicate_publications` jamais lourd ; `merge_persons` rarement (quelques centaines de publis max) ; merge journaux/publishers potentiellement lourd mais hypothétique. Le fire-and-forget n'est de toute façon pas applicable (réponse + navigation UI dépendent de la fusion *déjà faite*). → restent synchrones ; option B si un timeout réel apparaît. *(Le vrai trou des merges n'était pas la perf mais la requalification `doc_type` manquante sur merge de journaux — corrigé hors de ce chantier, commits `1a9bce2c` + `15bbfc4a`.)*
- [ ] `update_journal` (changement de type → `requalify` boucle `refresh_from_sources` sur N publications) : encore synchrone, même statut (pas de besoin perf observé).

### Phase 5 — Hygiène

- [x] **Confirmé** (commit `59cd52c6`). Les 2 BG tasks (`bg_propagate_countries_sync`, `bg_propagate_in_perimeter_sync`) ouvrent leur connexion via `with engine.begin()` + `try/except` → ni escalade d'erreur, ni transaction laissée ouverte (rollback + close en sortie même sur exception). Test de non-régression (la BG task avale l'erreur **et** rend sa connexion au pool, via `pool.checkedout()`) + contrat documenté au-dessus des BG tasks dans `deps.py`.

## Questions ouvertes

- **`BackgroundTasks` vs vraie job queue** (réévaluer à la transmission DSI). On part sur `BackgroundTasks` (économique, suffisant en mono-utilisateur admin) ; limite assumée : même process, non persistant aux restarts → on relance la mutation si crash. La DSI pourra vouloir une vraie job queue (pg-boss like) ; lui signaler ce choix et sa limite.
- **Option B (seuil + 202 + feedback UI), en réserve.** Si le fire-and-forget silencieux gêne (utilisatrice sans signal « ça calcule » sur un gros volume, ou besoin de consistance immédiate sur les petites reviews), reprendre le plan : seuil `PROPAGATION_SYNC_THRESHOLD` — en dessous synchrone, au-dessus réponse 202 `{pending, count}` + UI « propagation en cours… ». **Dette potentielle** : c'est plus de code (modèle de réponse, polling/refresh frontend), à n'engager que si le besoin se manifeste.
- **Réserve correctness `perimeter_structures`** (hors scope perf). Éditer un périmètre (`update_perimeter` / `add_perimeter_structure`) modifie `perimeters.structure_ids` sans rafraîchir la matview `perimeter_structures` → l'expansion du périmètre reste stale jusqu'au prochain run pipeline. **Même logique de staleness bornée que la Phase 2** (matview maintenue par le pipeline) — acceptable par le même raisonnement. Si un besoin de périmètre temps-réel émerge côté admin, rafraîchir sur édition.
