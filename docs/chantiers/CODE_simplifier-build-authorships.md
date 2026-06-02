# Chantier — Authorships : build source-agnostique en une passe convergente

Commencé le 2026-06-02

## Contexte

`build_authorships` consolide `source_authorships` → `authorships` (table de vérité). Le build est aujourd'hui **partiellement source-dépendant et non-convergent en incrémental**, ce qui contredit un principe d'architecture : seules les phases amont (`extract`, `cross-import`, `refresh-stale`, `normalize`) sont légitimement source-dépendantes ; en aval, le pipeline doit traiter l'**ensemble complet** des `source_authorships` sans considération des sources couvertes par le run courant. Trois symptômes :

- **Boucles per-source** : le linking (étape 2, `link_source_authorships_to_authorship_for(source)`) et la propagation périmètre (étape 4, `propagate_perimeter_from(source)`) itèrent sur `active_sources`. Un run partiel ne re-traite pas les sources absentes.
- **Reset périmètre gardé par `full_run`** : `reset_authorships_perimeter` ne tourne que si le run couvre *toutes* les sources — la correction du périmètre dépend des sources du pipeline, pas de l'état des données. Pourri.
- **Garde `IS NULL` (fill-once)** : `propagate_author_position` et `propagate_is_corresponding` n'écrivent que `WHERE a.x IS NULL` → une valeur déjà posée n'est **jamais révisée**. Une source qui corrige une position / un corresponding sur une authorship existante est ignorée jusqu'au purge mensuel. `propagate_roles` n'a pas ce garde (`IS DISTINCT FROM`) et converge déjà.

Le pruning des orphelines (commit `556b0819`) a fermé le gap sur *l'ensemble des paires* (add/delete). Ce chantier ferme le gap sur *les attributs et le périmètre*, et supprime la source-dépendance.

### Audit empirique (base prod, 2026-06-02)

- `is_corresponding` est un booléen **non-nullable, défaut FALSE** : le FALSE est une **absence de signal**, pas une non-correspondance explicite. scanr / theses / crossref ne le peuplent jamais (0 true) ; seules openalex / wos / hal le portent (hal très peu : 743 true).
- **Crossref ne contient pas l'info** dans le payload brut (`raw_store`), vérifié sans présupposé sur le nom du champ : sur 392 cas où le corresponding est connu (via WoS/OpenAlex) et où l'auteur est retrouvé par son nom dans le payload Crossref, 315 n'ont **aucune** clé que les co-auteurs n'ont pas (le reste = un ORCID incident) ; `sequence` est first/additional ≈ 56/44 % (n'indique donc pas le corresponding). Le marqueur vit dans le full-text JATS, hors métadonnées de dépôt Crossref. Pas une omission de notre côté.
- La **priorité perd du signal** : 2013 authorships sont FALSE là où `bool_or` serait TRUE (une source moins prioritaire atteste corresponding, écrasée par une source plus prioritaire à FALSE-par-défaut).
- **1371 authorships portent un TRUE périmé** qu'aucune source actuelle n'atteste — preuve directe de la non-convergence (le garde `IS NULL` n'a jamais corrigé après un réimport).
- Bascule vers `bool_or` + convergence : ~3384 / 108176 authorships changent (3,1 %).

## Décisions

1. **Une seule passe ensembliste, source-agnostique.** Remplacer les passes séquentielles per-source (position, is_corresponding, roles, in_perimeter) par un unique `UPDATE authorships … FROM (SELECT authorship_id, <agrégats> FROM source_authorships WHERE authorship_id IS NOT NULL GROUP BY authorship_id) sub`, convergent (`WHERE … IS DISTINCT FROM`), sans garde `IS NULL`.
2. **Linking (étape 2) ensembliste** : un seul `UPDATE` sur toutes les sources, plus de boucle per-source.
3. **Drop `SOURCE_PRIORITY_IS_CORRESPONDING`** : `is_corresponding = bool_or` (vrai si au moins une source l'atteste). Validé empiriquement — aucun FALSE explicite à écraser, donc aucun risque de « true indu » ; supprime le piédestal WoS (désabonnement probable à court/moyen terme).
4. **`in_perimeter = bool_or`** dans la même passe → supprime le reset *et* le gating `full_run`. Plus de dépendance aux sources couvertes.
5. **`author_position`** : garder le pick par priorité `SOURCE_PRIORITY` — c'est le seul attribut qui exige vraiment de choisir un ordinal entre sources. Gratuit dans la passe groupée (`(array_agg(… ORDER BY priorité))[1]`).
6. **`build()` ne prend plus de paramètre `sources`** ni de branche `full_run`. Le `rebuild_full` (purge complète) reste comme filet anti-divergence, mais devient **purement précautionnel** côté attributs une fois la convergence acquise.

## Phasage

- [x] Passe ensembliste unique côté queries : `propagate_authorship_attributes` fusionne position / is_corresponding / roles / in_perimeter en un agrégat convergent ; linking étape 2 en un `UPDATE` global (`link_source_authorships_to_authorships`).
- [x] Drop `SOURCE_PRIORITY_IS_CORRESPONDING` (`domain/sources/__init__.py`) + test associé.
- [x] Simplifier `build()` : signature `sources` et gating `full_run` retirés ; purge conservée sous `rebuild_full`. CLI `--sources` supprimée.
- [x] Harmoniser le chemin admin sur le modèle `bool_or` : `assign_orphans` (`recompute_authorship_author_position_and_corresponding` → bool_or, plus de param priorité) + renommage `link_source_authorships_to_authorship_for_pair` → `…_to_authorship`. L'autre chemin (`propagate_uca_for_addresses` → `propagate_in_perimeter_to_authorships`) était déjà convergent (`in_perimeter = EXISTS(...)`, gère la démotion).
- [x] `JOIN v_active_publications` de la propagation périmètre vérifié redondant (0 SA `in_perimeter=TRUE` sur publi inactive) — retiré.
- [x] Tests : idempotence (inchangée) + convergence (`is_corresponding` bool_or ; TRUE / rôle / périmètre périmés retombent). Caractérisation position par priorité couverte par l'idempotence.
- [x] Pas de one-shot prod nécessaire : la passe convergente recompute *tous* les authorships liés à chaque build (le `IS DISTINCT FROM` n'évite que les écritures inutiles), donc la prochaine exécution de la phase `authorships` — même incrémentale — corrige les ~3384 divergences, prune les orphelines et nettoie les rôles périmés automatiquement.
- [ ] **Remplacer le `full` par l'incrémental** : l'incrémental est désormais content-équivalent au full (mêmes paires, mêmes attributs) ; le full ne fait en plus que renuméroter les `id` (indésirable — handle externe durable) et re-linker de zéro (ne rattrape que des corruptions hors flux normaux). Retirer `rebuild_authorships_full` des modes pipeline (plus de purge routinière) ; conserver `rebuild_full` en option CLI de récupération manuelle. Test d'équivalence : muter les sources → build incrémental → snapshot, build full → snapshot, assert égalité (modulo `id`).

## Questions ouvertes

- `author_position` : garder le pick par priorité, ou un `min()` suffirait-il comme approximation ? (la priorité est gratuite dans la passe, on la garde sauf objection.)
