# Performance des pages de listes (UI)

Commencé le 2026-06-12

## Contexte

Depuis que le pipeline promeut dans `publications` les `source_publications` **hors périmètre** (chantier création⇒fusion), la table contient bien plus de lignes que le seul périmètre UCA (~183 k dont ~65 k in-perimeter). Les pages de listes (publications, thèses, publishers, journals) et leurs facettes filtrent donc au périmètre à chaque requête, d'où des chargements de plusieurs secondes (page publications observée à 23 s).

Cause racine commune : **chaque agrégat dépendant du périmètre re-scanne l'ensemble in-perimeter de `publications`**, une table à lignes larges (~3,5 Ko/ligne — `abstract`, `topics`, `meta`, `biblio` stockés inline). Lire 65 k lignes larges = des centaines de Mo, répété par requête : le COUNT de la liste, **chacune** des ~11 facettes (scans indépendants du même ensemble), le filtre `with_pubs`… Le coût n'est jamais « compter », c'est lire les octets des lignes (Postgres lit le heap par pages de 8 Ko ; lignes larges = peu de lignes/page = beaucoup de pages).

### État actuel (déjà fait)

- **`publications.in_perimeter` matérialisé** (colonne) : remplace l'`EXISTS` sur `authorships` que `publication_in_perimeter` recalculait par ligne. COUNT périmètre 4 s → ~0,6 s. Maintenu en phase `authorships` (rollup `refresh_publications_in_perimeter`, étape 3bis de `build_authorships`) + à l'action de rejet de personne (`set_rejected`). Migration `e7f2a9c4b1d3` (colonne + backfill + index partiels `(pub_year DESC)` et `(journal_id)` WHERE in_perimeter).
- **`v_active_publications` supprimée**. Le scope doc_type redevient le filtre inline `doc_type NOT IN OUT_OF_SCOPE_DOC_TYPES_SQL` (`domain/publications/scope`), source unique. Migration `f4b9d2e7a1c6` (DROP VIEW) **à appliquer**.
- **Facettes publications parallélisées** : les ~11 facettes, indépendantes, tournaient en séquence sur une connexion. Lancées en parallèle (un thread + une connexion chacune, pool max = 30). Gain **modeste** (6-7 s → ~4 s) : 11 scans simultanés de la même table saturent l'I/O — réduit le wall-clock, pas le travail total.
- **Dé-bloat** : un `VACUUM FULL publications` a ramené la table de 1166 Mo → 649 Mo (gonflée par des UPDATE de masse). La page publications est passée de 23 s à ~9 s. À retenir : les UPDATE de masse (backfill, refresh pipeline) bloatent ; prévoir un VACUUM.

## Décisions (proposées, à valider)

### Matérialiser les comptes dérivés du périmètre

- **`pub_count` in-perimeter sur `publishers` + `journals`** : aujourd'hui le filtre `with_pubs` (« éditeurs/revues ayant des publications UCA ») et le tri rejouent un scan des 65 k publications in-perimeter (~0,5 s, que la sous-requête soit corrélée ou ensembliste — Postgres semi-joint déjà bien). Avec un `pub_count` matérialisé, `with_pubs` devient `WHERE pub_count > 0` (lecture de la petite table publishers, instantané), affichage et tri gratuits. Maintenu par le pipeline, même pattern que `in_perimeter`. Évite le re-scan de `publications`.

### Narrow-table — le levier de fond, scalable

- Sortir les colonnes **detail-only** (`abstract`, `topics`, `meta`, `biblio`, `keywords`) vers une table `publications_detail`, chargée seulement sur la page détail d'une publication. `publications` retombe à des lignes étroites → **tous** les scans (count, facettes, listes, with_pubs) deviennent rapides, y compris à 200 k+ in-perimeter. C'est le seul levier qui rend l'ensemble scalable sans rationner les données. Chantier : split schéma + le pipeline écrit les deux tables + la page détail joint `publications_detail`.

### Facettes en un seul passage

- Calculer plusieurs facettes en **un seul scan** (GROUPING SETS + agrégats `FILTER`) quand elles partagent le même WHERE (cas par défaut, sans filtre actif). Tue la redondance des N scans. Se complique dès qu'un filtre est actif (chaque facette exclut le sien) — applicable au moins au cas par défaut, le plus fréquent.

## Phasage

### 1. `pub_count` matérialisé (publishers + journals)

Quick-win ciblé, indépendant. Compte de publications in-perimeter **et in-scope** par revue, puis par éditeur (somme de ses revues). Résultat mesuré : page publishers `with_pubs=True` 1,14 s → 0,010 s (list) et 0,89 s → 0,006 s (facettes), backfill exact.

- [x] Colonnes `journals.pub_count` + `publishers.pub_count` (migration `a1f3c8e2d5b9`, colonnes + backfill ; pas d'index — tables petites, `> 0` et tri triviaux)
- [x] Refresh pipeline après le rollup `in_perimeter` (fin de `phase_authorships`, `pub_counts.refresh_pub_counts`)
- [x] Maintien aux **fusions admin** : fusion de revues (revue cible + éditeurs concernés), fusion d'éditeurs (somme côté cible)
- [x] Bascule `with_pubs` → `WHERE pub_count > 0` (listes + facettes) ; affichage et tri sur la colonne

### 2. Narrow-table

Le gros morceau.

- [ ] Split des colonnes detail-only vers `publications_detail`
- [ ] Le pipeline écrit les deux tables
- [ ] La page détail joint `publications_detail`

### 3. Facettes en un passage / caching

Selon ce que (2) laisse comme résidu.

- [ ] GROUPING SETS + agrégats `FILTER` pour le cas par défaut (facettes partageant le même WHERE)
- [ ] Caching applicatif (si nécessaire)

### 4. Test de non-régression

- [ ] Temps de chargement de la page publications (liste + facettes) sous un seuil à définir

## Questions ouvertes

- **Caching** : un cache applicatif des facettes/counts par signature de filtres (invalidé au run pipeline) est-il souhaitable ? Comment les sites très chargés tiennent le chargement instantané (read-models dénormalisés, précalcul, cache agressif) — à transposer ici ou non.
- **Index couvrant** (notion à expliquer puis trancher) : un index contenant toutes les colonnes lues par une requête permet un *index-only scan* — pas d'accès au heap, la largeur de ligne devient sans objet. Limites : un index par motif de requête, inapplicable aux agrégats multi-colonnes et aux colonnes tableaux (`sources`, `countries`).
- **Réutilisation des facettes entre pages** : le composant `PublicationsListView` est réutilisé sur plusieurs pages — les facettes passent-elles par un endpoint partagé paramétré (filtres) ou sont-elles redéfinies par page (duplication) ? À vérifier côté frontend.
- **Seuil** du test de non-régression (combien de secondes acceptables).
