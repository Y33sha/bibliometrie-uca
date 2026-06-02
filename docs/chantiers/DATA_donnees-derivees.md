# Chantier — Données dérivées : audit + cadre de décision (matérialisation vs vue)

Commencé le 2026-06-01


## Contexte

Beaucoup de tables et colonnes du schéma sont **dérivées** : précalculées et stockées (maintenues par du code impératif du pipeline) pour l'efficience des requêtes, au prix d'une duplication d'information. La même question revient pour chacune : faut-il **garder la matérialisation**, ou la remplacer par une **vue** (calcul à la lecture) ou une **vue matérialisée** (précalcul déclaratif + refresh) ?

La traiter au cas par cas, chantier par chantier, c'est rejouer la même analyse à chaque fois (cf. [`DATA_perimeter-materialise`](DATA_perimeter-materialise.md), qui traîne faute d'un verdict tranché). Ce chantier pose un **cadre de décision partagé** et un **inventaire classifié** du dérivé. Ce n'est **pas** un refacto « tout en vues » : le livrable est une carte avec un verdict par artefact, pas une conversion en bloc.

## Cadre de décision

### Le verdict par artefact

Pour chaque artefact dérivé, l'un de :

- **Garder table maintenue** (statu quo) — chemin chaud où le calcul à la lecture serait prohibitif.
- **`VIEW` pure** — calcul à la lecture trivial, toujours frais, zéro maintenance.
- **`MATERIALIZED VIEW`** — calcul lourd mais lectures fréquentes ; précalcul déclaratif + `REFRESH` orchestré.
- **Colonne dérivée** (reste une colonne, mais on clarifie sa source/refresh).

### Le critère de faisabilité d'abord : pur vs dérivé-avec-natif

**Avant** toute considération de perf, trancher : l'artefact est-il **purement dérivé**, ou porte-t-il un **îlot d'état natif** (saisie manuelle qui survit aux rebuilds) ?

- **Purement dérivé** → candidat vue / matview.
- **Dérivé + sidecar natif** → **ne peut pas** devenir une vue pure (l'état natif n'aurait nulle part où vivre). Il faut d'abord extraire le natif dans sa propre (petite) table, ou garder une table maintenue. Cas net : `authorships.excluded` (rejet manuel via l'admin, métier natif, survit au rebuild from scratch).

C'est un critère de **faisabilité**, pas de perf : il élimine d'office certaines conversions.

### Les axes de perf/maintenance (pour les purement dérivés)

- **Coût de calcul à la lecture** : JOIN trivial sur FK → vue viable ; CTE récursive (clôture périmètre) ou gros agrégat → matview ou garder.
- **Chaleur des requêtes** : un artefact sur le chemin chaud (listing publications, facettes, stats) ne peut pas absorber un surcoût lecture → tend vers « garder ».
- **Ratio écriture-source / lecture** : source qui change rarement, lue souvent → matview gagne. Change souvent → vue ou accepter le rebuild.
- **Tolérance à la staleness** : aujourd'hui le cache dérivé *peut* driver sans détection ; une vue est toujours fraîche ; une matview demande un refresh orchestré (= où dans le pipeline + hook admin).

### Angle DSI (pas que la perf)

Une partie de la valeur est la **maintenabilité** : aujourd'hui beaucoup de **code de rebuild impératif** (propagation `in_perimeter`, consolidation des structures, recalcul d'agrégats…). Le remplacer par du déclaratif **retire du code maison** → plus lisible à reprendre par la DSI. Mais une matview **ajoute** une orchestration de refresh : on échange une complexité contre une autre, à peser explicitement par artefact.

## Phasage

### Phase 1 — Inventaire classifié

- [x] Balayage et classification A/B/C des 36 tables du schéma
- [x] Alignement `normalize_name_form` SQL ↔ `normalize_text` Python — préalable pour instruire le verdict `GENERATED` sur les `*_normalized` (cf. migration `b2d4e7a1c8f3` + filet de non-régression [`tests/integration/test_normalize_alignment_python_sql.py`](../../tests/integration/test_normalize_alignment_python_sql.py))

Inventaire en trois catégories. Pour chaque artefact : source (dérivé de quoi), pur ou +natif, coût on-read, chaleur, verdict. Les verdicts orientent les sous-chantiers de Phase 2, ils ne sont pas figés.

**A. Dérivé interne — candidats vue / vue matérialisée** (purement dérivé de nos propres données) :

| Artefact | Dérivé de | Dérivation | Verdict provisoire |
|---|---|---|---|
| `subject_cooccurrences` (table entière) | paires de sujets co-présents sur une publi | agrégat, recalculé chaque run | **matview** — table 100 % dérivée |
| `subjects.usage_count` | `count(publication_subjects)` par sujet | agrégat | matview / colonne recalculée |
| `addresses.pub_count` | nb de publications distinctes liées à l'adresse | agrégat | **colonne maintenue** — était un cache orphelin périmé (maintainer perdu), recompute recâblé en fin de `normalize` |
| `publications.sources[]` | union des sources contributrices | trivial (union) | **garder colonne** — chemin chaud (facettes/filtres via `@>` GIN) ; une matview imposerait un JOIN au listing |
| `authorship_structures` | union des `source_authorship_structures` de l'authorship | union JOIN | **matview viable** (perf-lecture neutre) ; décision = expressibilité SQL + coût refresh full vs incrémental, pas un benchmark de lecture |

**B. Dérivé interne — garder matérialisé** (raison explicite : état natif mêlé, dérivation coûteuse, ou chemin chaud) :

| Artefact | Pourquoi garder |
|---|---|
| `publications` (table) | arbitrage multi-source coûteux + **état natif** (`meta` corrections) + chemin ultra-chaud |
| `authorships` (table) | rebuild consolidé. **Natif dissous** (migration `f3b6d9c1a8e2`) : `source_manual` (vestigial) droppé, `excluded` extrait en store `rejected_authorships(publication_id, person_id)`. La table est désormais **entièrement dérivée** → **candidat matview** (cf. Phase 2), reste chemin chaud + consolidation |
| `persons` (table) | matching identités + **état natif** (`rejected`, fusions via `distinct_persons`) |
| `source_authorship_structures` | dérivation = **matching adresse→structure** (coûteux), pas un JOIN |
| `*.in_perimeter` (`authorships`, `source_authorships`) | chemin chaud (filtrage listings/facettes/stats) → **sous-chantier perimeter** |
| `source_authorships.{person_id, authorship_id}` | colonnes bolt-on (résultats de matching) sur une table source |
| colonnes `*_normalized` (`publications.title`, `persons.*`, `journals.title`, `publishers.name`, `source_authorships.author_name`, `addresses.normalized_text`) | peuplées par `normalize_text` (**Python**) à l'INSERT/UPDATE. `normalize_name_form` SQL est alignée sur Python ; `GENERATED ALWAYS AS (normalize_name_form(...))` est techniquement possible. Tradeoff à instruire par sous-chantier : statu quo (Python = souplesse d'évolution) vs `GENERATED` (cohérence garantie, simplifie le pipeline) |

**C. Hors scope** (pas du dérivé interne dupliquant nos données) :

- **Caches externes** : `doi_prefixes` (Crossref/DataCite) ; enrichissements `journals` (`apc_amount`, `oa_model`, `doaj_payload`, `is_in_doaj`, `doi_prefix`) et `publishers` (`openalex_id`, `country`, `ror`, `publisher_type`). Dérivés d'**APIs externes** — aucune source interne, donc pas « vue-ables ».
- **Config de matching** : `structure_name_forms` (`is_excluding`, `requires_context_of` = règles admin), `journal_name_forms` / `publisher_name_forms` (formes observées, semi-dérivées), `country_name_forms` (seed).
- **État natif / décisions manuelles** (jamais dérivé — ce sont des **inputs**) : `distinct_persons`, `distinct_publications`, `*.excluded`, `*.rejected`, `person_identifiers.status`, `address_structures.is_confirmed`, `persons_rh`, `apc_payments`, `config`, `perimeters`, `staging`, `source_publications`/`source_authorships` (trace source inviolable).

**Synthèse** : l'opportunité « vue/matview » est **étroite**, concentrée sur les **agrégats purs** (catégorie A — surtout `subject_cooccurrences` et les `count`). Le gros du dérivé reste matérialisé pour de bonnes raisons (état natif inséparable, dérivation = matching coûteux, ou chemin chaud). Pas de présupposé « vue = mieux ».

### Phase 2 — Conversions ciblées (sous-chantiers)

Chaque conversion = un sous-chantier dédié (migration + adaptation des call-sites + tests + éventuel hook de refresh). Les cas perf-sensibles passent par un **benchmark sur la vraie base** d'abord.

- [x] Matview `subject_cooccurrences` — table 100% dérivée remplacée par `MATERIALIZED VIEW` (migration `c8a3f2e5b4d7`, seuil `count >= 2` figé). `subjects.usage_count` reste une colonne maintenue — verdict **assumé sur l'ergonomie/perf**, pas « hors scope » : c'est une colonne sur l'entité `subjects` (très jointe), le recompute est cheap, et la sortir en matview forcerait un JOIN partout où on lit/trie sur `usage_count`.
- [x] Verdict `GENERATED` vs Python pour les colonnes `*_normalized` — **rejeté, statu quo**. Aujourd'hui chaque colonne normalisée est mono-implémentation (valeur stockée **et** clé de matching toutes deux via Python `normalize_text`, ou toutes deux via SQL `normalize_name_form` pour `source_authorships`) → cohérente par construction. Passer en `GENERATED` rendrait la valeur stockée SQL alors que les clés de matching restent Python : ça **introduit** une surface de divergence Python↔SQL (deux implémentations distinctes d'une transfo Unicode, jamais prouvées équivalentes — le test d'alignement échantillonne) là où il n'y en a pas, et une divergence sur une seule entrée = échec de dédup silencieux. Le risque ajouté (non borné, silencieux) dépasse le risque retiré (drift brut↔normalized, étroit et auditable). Le seul `GENERATED` défendable normaliserait aussi les clés de matching en SQL (source unique), mais c'est un chantier nettement plus lourd, non justifié tant que le drift n'est pas un problème observé. Le bug de drift réel identifié (le `COALESCE` ON CONFLICT OpenAlex/WoS) a été corrigé directement.
- [x] **Retrait de `source_authorships.excluded`** (migration `e1f4b8c2a6d9`). C'était une fonctionnalité morte : une croix admin « marquer comme faux » dans la grille des sources (page publication) jamais utilisée — 0 ligne à `TRUE` en prod. Colonne + index `idx_sa_excluded` + endpoint `POST /api/source-authorships/.../exclude` + service/repo associés + filtres `NOT sa.excluded` supprimés.
- [x] **Extraire `authorships.excluded` en sidecar** → [`DATA_rejected-authorships-sidecar`](DATA_rejected-authorships-sidecar.md) (migration `f3b6d9c1a8e2`). Store `rejected_authorships(publication_id, person_id)` lu en anti-join par les sites de création ; modèle skip-at-build (la paire rejetée n'a aucune row, les filtres `NOT a.excluded` disparaissent). `source_manual` (vestigial) droppé dans la foulée. `authorships` est désormais entièrement dérivée → débloque le matview ci-dessous.
- [x] **`addresses.pub_count` : cache orphelin réparé**. La colonne (315 k rows en prod, max 28 366) n'avait plus de maintainer : le recompute avait été supprimé avec `addresses_extracted` (commit `7f3958fc`) et jamais recâblé sur `source_authorship_addresses`. Diagnostiquée stale (page admin triée dessus + filtre `detect_address_countries WHERE pub_count > 0` faussés). Recompute global (LEFT JOIN, reset des orphelines à 0, guard `IS DISTINCT FROM`) rebranché **en fin de `phase_normalize`**, là où `source_authorship_addresses` est peuplée — un run `--only normalize` le tient à jour, sans attendre une phase ultérieure. `publications.sources[]` examiné au passage → garder colonne (chemin chaud GIN).
- [ ] `authorships` en matview — **après** le point ci-dessus (natif dissous). Remplacer le rebuild impératif `build_authorships` par une `MATERIALIZED VIEW` **si la consolidation est exprimable en SQL**. **Perf-lecture neutre** (matérialisé des deux côtés) ; le vrai arbitrage est le coût de **refresh full** (matview) vs le build **incrémental** actuel en daily/weekly. Couplage périmètre faible : la matview OR-erait `source_authorships.in_perimeter` (déjà matérialisé), pas besoin de la clôture dedans.
- [ ] Benchmark `authorship_structures` en vue vs colonne maintenue — chemin chaud filtrage périmètre, à mesurer avant tranche
- [ ] [`DATA_perimeter-materialise`](DATA_perimeter-materialise.md) — réactivable comme sous-chantier si l'audit valide la matérialisation de `perimeter_structures` et/ou la suppression de `in_perimeter`

## Questions ouvertes

- **Orchestration du refresh des matviews** : où dans le pipeline (une phase dédiée en fin ? après chaque phase productrice ?) + hooks admin pour les artefacts dépendant d'inputs éditables (périmètres, exclusions).
- **Granularité du refresh** : `REFRESH MATERIALIZED VIEW` est full ; `CONCURRENTLY` évite le lock mais exige un index unique. Acceptable selon la taille / fréquence.
- **Seuil de décision** : à partir de quel surcoût lecture (p95) on renonce à une vue au profit du statu quo ? À fixer sur mesures réelles.
