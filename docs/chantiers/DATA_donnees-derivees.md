# Chantier — Données dérivées : audit + cadre de décision (matérialisation vs vue)

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

### Phase 1 — Inventaire classifié (le livrable principal)

Lister **tout** le dérivé (tables et colonnes), et pour chacun remplir : source (dérivé de quoi), pur ou +natif, coût on-read, chaleur, verdict provisoire, à-benchmarker (oui/non).

Inventaire (balayage des 36 tables du schéma à jour), en trois catégories. Verdicts **provisoires** ; les « nature » sont déduites du schéma + de la connaissance du pipeline, quelques-unes restent à confirmer dans le code populateur.

**A. Dérivé interne — candidats vue / vue matérialisée** (purement dérivé de nos propres données) :

| Artefact | Dérivé de | Dérivation | Verdict provisoire |
|---|---|---|---|
| `subject_cooccurrences` (table entière) | paires de sujets co-présents sur une publi | agrégat, recalculé chaque run | **matview** — table 100 % dérivée |
| `subjects.usage_count` | `count(publication_subjects)` par sujet | agrégat | matview / colonne recalculée |
| `addresses.pub_count` | nb d'authorships liées à l'adresse | agrégat | matview / colonne |
| `publications.sources[]` | union des sources contributrices | trivial (union) | view / colonne triviale |
| `authorship_structures` | union des `source_authorship_structures` de l'authorship | union JOIN | candidat view, **mais chemin chaud périmètre → benchmark** |

**B. Dérivé interne — garder matérialisé** (raison explicite : état natif mêlé, dérivation coûteuse, ou chemin chaud) :

| Artefact | Pourquoi garder |
|---|---|
| `publications` (table) | arbitrage multi-source coûteux + **état natif** (`meta` corrections) + chemin ultra-chaud |
| `authorships` (table) | rebuild consolidé + **état natif** (`excluded`, `source_manual`) |
| `persons` (table) | matching identités + **état natif** (`rejected`, fusions via `distinct_persons`) |
| `source_authorship_structures` | dérivation = **matching adresse→structure** (coûteux), pas un JOIN |
| `*.in_perimeter` (`authorships`, `source_authorships`) | chemin chaud (filtrage listings/facettes/stats) → **sous-chantier perimeter** |
| `source_authorships.{person_id, authorship_id}` | colonnes bolt-on (résultats de matching) sur une table source |
| colonnes `*_normalized` (`publications.title`, `persons.*`, `journals.title`, `publishers.name`, `source_authorships.author_name`, `addresses.normalized_text`) | peuplées par `normalize_text` (**Python**). `GENERATED` possible **seulement** si `normalize_text` est réductible à du SQL immutable (`unaccent`+`lower`+trim) — à vérifier ; sinon reste impératif |

**C. Hors scope** (pas du dérivé interne dupliquant nos données) :

- **Caches externes** : `doi_prefixes` (Crossref/DataCite) ; enrichissements `journals` (`apc_amount`, `oa_model`, `doaj_payload`, `is_in_doaj`, `doi_prefix`) et `publishers` (`openalex_id`, `country`, `ror`, `publisher_type`). Dérivés d'**APIs externes** — aucune source interne, donc pas « vue-ables ».
- **Config de matching** : `structure_name_forms` (`is_excluding`, `requires_context_of` = règles admin), `journal_name_forms` / `publisher_name_forms` (formes observées, semi-dérivées), `country_name_forms` (seed).
- **État natif / décisions manuelles** (jamais dérivé — ce sont des **inputs**) : `distinct_persons`, `distinct_publications`, `*.excluded`, `*.rejected`, `person_identifiers.status`, `address_structures.is_confirmed`, `persons_rh`, `apc_payments`, `config`, `perimeters`, `staging`, `source_publications`/`source_authorships` (trace source inviolable).

**Conclusion de l'inventaire** : l'opportunité « vue/matview » est **étroite**, concentrée sur les **agrégats purs** (catégorie A — surtout `subject_cooccurrences` et les `count`). Le gros du dérivé doit rester matérialisé pour de bonnes raisons (état natif inséparable, dérivation = matching coûteux, ou chemin chaud). Ça **confirme qu'il ne faut pas présupposer « vue = mieux »**. Conversions à vrai gain net à instruire en priorité : (1) `subject_cooccurrences` + `subjects.usage_count` en matview (retire du code de recalcul, agrégats peu coûteux à rafraîchir) ; (2) le cas périmètre (sous-chantier dédié, conditionné au benchmark). Le reste : statu quo assumé.

### Phase 2 — Conversions ciblées (sous-chantiers)

Seulement là où le gain est net. Chaque conversion = un sous-chantier dédié (migration + adaptation des call-sites + tests + éventuel hook de refresh). Les cas perf-sensibles passent par un **benchmark sur la vraie base** d'abord.

- [`DATA_perimeter-materialise`](DATA_perimeter-materialise.md) en **standby** : réactivable comme sous-chantier si l'audit valide la matérialisation de `perimeter_structures` et/ou la suppression de `in_perimeter`.

## Questions ouvertes

- **Orchestration du refresh des matviews** : où dans le pipeline (une phase dédiée en fin ? après chaque phase productrice ?) + hooks admin pour les artefacts dépendant d'inputs éditables (périmètres, exclusions).
- **Granularité du refresh** : `REFRESH MATERIALIZED VIEW` est full ; `CONCURRENTLY` évite le lock mais exige un index unique. Acceptable selon la taille / fréquence.
- **Seuil de décision** : à partir de quel surcoût lecture (p95) on renonce à une vue au profit du statu quo ? À fixer sur mesures réelles.
