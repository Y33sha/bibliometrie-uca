# Cycle de vie des rows `staging` : machine à états, backoff, fraîcheur

## Contexte

Le cycle de vie d'une row dans `staging` (et des entités dérivées qu'elle alimente, `source_publications` + `source_authorships`) est aujourd'hui implicite : plusieurs mécanismes ad-hoc, sans doctrine unifiée. Trois préoccupations connectées sont apparues dans l'audit de modélisation :

**1. Machine à états mal documentée.** Aujourd'hui le cycle de vie est codé par 3 colonnes booléennes + 1 JSONB (`processed`, `not_found`, `raw_data` plein ou `{}`). Combinatoire théorique = 8, sémantique réelle = 3 états :

| État | `processed` | `not_found` | `raw_data` |
|---|---|---|---|
| À traiter | FALSE | FALSE | plein |
| Normalisée | TRUE | FALSE | `{}` |
| Non trouvée | TRUE | TRUE | `{}` |

Aucune colonne ne désigne directement l'état — il faut inférer la combinaison. Aucun CHECK SQL n'empêche les combinaisons invalides (ex. `not_found=TRUE` avec `processed=FALSE`, qui rétrograderait silencieusement un row terminal en "à re-traiter").

**2. Backoff sur les `not_found` pour les cross-imports DOI.** Aujourd'hui `not_found=TRUE` est écrit à deux endroits :
- [`hal/fetch_missing_hal_id.py`](../../infrastructure/sources/hal/fetch_missing_hal_id.py) — hal-id 404 dans HAL (source native) → **définitif** (HAL dédoublonne, le doc n'existe plus). `source_id` = le vrai hal-id.
- [`crossref/fetch_missing_doi.py`](../../infrastructure/sources/crossref/fetch_missing_doi.py) — DOI 404 chez Crossref (source native pour les DOI Crossref) → **définitif** (DOI erroné ou non Crossref). `source_id` = le DOI, qui *est* l'id natif Crossref.

Les 4 autres sources qui font du `fetch_missing_doi` (HAL, OpenAlex, WoS, ScanR) n'écrivent **rien** quand un DOI n'est pas trouvé (l'adapter retourne `[]`, `insert` n'est jamais appelé). Conséquence : ces DOI sont retentés à chaque run (croissance non bornée du pool, coût API qui monte avec le temps).

La sémantique correcte : un identifiant cherché sur sa **source native** + 404 = définitif ; un DOI cherché sur une **autre source** + 404 = à retenter après un délai (la source peut indexer plus tard).

**3. Fraîcheur des données / publications disparues.** Item TODO existant : *"Mettre en place le process pour détecter les publications disparues et les nettoyer de la base (ou les archiver ?). + publis du cross-import : re-fetch régulier pour tenir les données à jour."*

Aujourd'hui :
- `staging.last_seen_at` est mis à jour à chaque ré-extraction d'un même doc → permet de détecter les disparus mais aucune action n'est branchée.
- Les publications obtenues via cross-import DOI ne sont jamais re-fetchées : leurs métadonnées vieillissent silencieusement.

## Décisions

### Deux sémantiques de `not_found`, deux emplacements

Le point structurant : ce qu'on appelle aujourd'hui `not_found` recouvre deux faits de nature différente, qu'il faut séparer.

| Fait | Clé | Verdict | Collision possible ? | Emplacement |
|---|---|---|---|---|
| Miss **natif** : un id natif ne résout pas (hal-id 404 dans `fetch_missing_hal_id` ; DOI 404 chez Crossref) | id natif (`source_id`) | définitif | Non — `source_id` natif, un vrai row futur fusionne via `ON CONFLICT (source, source_id)` | `staging.not_found_at` |
| Miss **cross-import** : un DOI cherché sur HAL/OpenAlex/WoS/ScanR est absent | DOI (≠ id natif) | temporaire (backoff) | Oui si stocké dans `staging` (il faudrait un `source_id` synthétique qui cohabiterait avec le vrai row indexé plus tard) | table dédiée `doi_lookups` |

La collision que cette séparation évite : si un miss cross-import était stocké dans `staging` avec un `source_id` synthétique (`'doi:10.x/y'`), et que la source indexe ensuite le doc sous son id natif, on aurait **deux rows `staging`** pour le même `(source, doi)` — un stub fantôme (`raw_data = {}`, jamais normalisé, jamais nettoyé, faussant les comptages) et le vrai. En sortant ces miss vers `doi_lookups` (clé `(source, doi)`), le vrai doc arrive comme row `staging` normal et les deux ne coexistent jamais.

### `staging` : `not_found` BOOL → `not_found_at TIMESTAMPTZ`

Le seul `not_found` qui reste dans `staging` est le miss natif, **toujours définitif**. Donc une seule colonne suffit, pas de `next_retry` côté `staging` :

| Colonne | Sémantique |
|---|---|
| `not_found_at TIMESTAMPTZ NULL` | Date du miss natif définitif ; `IS NOT NULL` remplace fonctionnellement l'ancien `not_found = TRUE` |

États observables de `staging` :

| État | `processed` | `not_found_at` | `raw_data` |
|---|---|---|---|
| À traiter | FALSE | NULL | plein |
| Normalisée | TRUE | NULL | `{}` |
| Non trouvée (natif, définitif) | TRUE | timestamp | `{}` |

CHECK consolidé, minimal :

```sql
CHECK (not_found_at IS NULL OR processed)
-- un miss natif est terminal : ne peut pas coexister avec processed = FALSE
```

### Nouvelle table `doi_lookups` (backoff cross-import)

```sql
CREATE TABLE doi_lookups (
    source        source_type  NOT NULL,
    doi           text         NOT NULL,
    not_found_at  timestamptz  NOT NULL,  -- date de la dernière tentative négative
    next_retry    timestamptz  NOT NULL,  -- date minimum de re-tentative
    PRIMARY KEY (source, doi)
);
```

Ces rows ne sont pas des stagings (pas de payload, pas de cycle de normalisation) : c'est un cache de tentatives négatives. Tous les miss cross-import sont temporaires (la source peut indexer plus tard), donc `next_retry` est toujours peuplé — pas de cas définitif ici. Lecture :
- `next_retry > NOW()` → en attente
- `next_retry <= NOW()` → à retenter au prochain run

Sur chaque nouveau miss du même `(source, doi)`, la row est ré-armée (`not_found_at = NOW()`, `next_retry = NOW() + délai`) via `ON CONFLICT (source, doi) DO UPDATE`.

### `get_cross_import_dois` adaptée

Le pool exclut les DOI déjà présents dans `staging` côté cible **et** ceux en backoff dans `doi_lookups` :

```sql
SELECT DISTINCT s.doi
FROM staging s
WHERE s.source != :target AND s.doi IS NOT NULL          -- [+ filtre processed et préfixe RA inchangés]
  AND NOT EXISTS (
      SELECT 1 FROM staging t WHERE t.source = :target AND t.doi = s.doi
  )
  AND NOT EXISTS (
      SELECT 1 FROM doi_lookups l
      WHERE l.source = :target AND l.doi = s.doi AND l.next_retry > NOW()
  )
ORDER BY s.doi
```

Le filtre RA sur `doi_prefixes` (cible Crossref) et le filtre `processed` restent inchangés.

### Disparition par refetch ciblé (fusion des ex-phases 3 et 4)

La détection des publications disparues et le re-fetch périodique des métadonnées ne sont **pas** deux mécanismes : c'est le même. L'inférence par périmètre (« un doc qui aurait dû réapparaître dans une moisson native n'est pas revenu → disparu ») ne peut structurellement pas couvrir les cross-imports : un cross-import est hors périmètre natif de la source, donc une moisson native ne rebumpe jamais son `last_seen_at` — il serait flaggé disparu à tort.

Le seul signal correct, valable pour les natifs **comme** pour les cross-imports : un **refetch ciblé par id** des rows à `last_seen_at` ancien. Succès → on rafraîchit `raw_data` (les UPSERT existants remettent `processed = FALSE` si le hash change) et on bumpe `last_seen_at`. 404 / absent → signal de disparition → action à décider. Une seule phase, double emploi (fraîcheur + disparition).

### Conséquence sur la scope policy `cross_imports`

Aujourd'hui l'étape 2 (DOI) a une scope policy `unprocessed` vs `all` parce que son pool n'est pas borné (les 404 chez HAL/OpenAlex/WoS/ScanR ne sont pas tracés → retentés à chaque run). Avec le backoff `doi_lookups`, le pool devient auto-borné et convergent : 1er pass tente tout, les 404 reçoivent `next_retry`, les passes suivantes ne retentent que ceux dont `next_retry <= NOW()`. L'asymétrie avec l'étape 1 (hal-id, déjà auto-bornée) disparaît, et la scope policy perd sa raison d'être.

À traiter en Phase 2 : retirer le champ `fetch_missing_doi_scope` de `ModePolicy` et le flag `--all` du CLI [`interfaces/cli/pipeline/fetch_missing_doi.py`](../../interfaces/cli/pipeline/fetch_missing_doi.py), simplifier `phase_cross_imports`. La distinction sources (`fetch_missing_doi_sources`, qui exclut WoS hors `full` pour son quota API) reste pertinente — critère orthogonal au backoff.

## Phasage

### Phase 1 — Machine à états documentée + CHECK minimal ✓

- [x] Migration `staging_not_found_implies_processed CHECK (NOT not_found OR processed)` — migration 0015.
- [x] `donnees` : section "Cycle de vie d'une row `staging`" (cf. [donnees/05-authorships-et-sources.md](../donnees/05-authorships-et-sources.md)).

### Phase 2 — Backoff `not_found_at` (staging) + `doi_lookups` ✓

- [x] Migration `d4e8a1f6c3b7` : `staging.not_found` → `not_found_at` (CHECK consolidé `not_found_at IS NULL OR processed`, retrait de l'index partiel `idx_staging_not_found`) ; création de `doi_lookups (source, doi, not_found_at, next_retry)`.
- [x] Adapters natifs (`hal/fetch_missing_hal_id`, `crossref/fetch_missing_doi`) : `not_found_at` à la place de `not_found` (miss natif définitif, reste sur `staging`).
- [x] Adapters non natifs (hal/openalex/wos/scanr `fetch_missing_doi`) : sur miss confirmé, écriture `doi_lookups` via la sentinelle partagée `not_found_marker` (port `fetch_missing_doi`) routée par `insert()` → `record_doi_not_found`. WoS ne marque que sur lot complet (pas de faux miss sur erreur transitoire ou pagination interrompue).
- [x] `get_cross_import_dois` : exclusion `doi_lookups` (`next_retry > now()`) + retrait du filtre `processed` (pool désormais borné par le backoff, plus par `processed`).
- [x] Retrait de `fetch_missing_doi_scope` (`ModePolicy`) et `--all` (CLI) ; simplification de `phase_cross_imports`. `tables.py` synchronisé (cible autogenerate).
- [x] Délai = 30 j, constante `DOI_LOOKUP_RETRY_DAYS` dans `infrastructure/sources/common.py`.
- [x] Docs : `donnees/05-authorships-et-sources.md` (états + `doi_lookups`), `pipeline/02-extract.md` (backoff).

### Phase 3 — Fraîcheur & disparition par refetch ciblé ✓

**Critère unique : `last_seen_at` ancien — pas de filtre par type.** Le gap de `last_seen_at` après un `full` est un *signal* de disparition, pas une *confirmation* : un natif peut manquer à un batch de façon transitoire (hoquet API, requête d'affiliation qui ne le matche pas ce jour-là, déindexation temporaire). Le refetch individuel est l'étape de confirmation — trouvé = faux gap, on bumpe ; 404 = mort confirmée. Il tourne donc sur **toute** row stale, native comme cross-import.

**Prérequis acté : `full` à fenêtre fixe (rétention cumulative).** Le mode `full` re-moissonne tout l'historique depuis une ancre absolue (`pipeline_start_year_full` = 2017). Son rôle ici : le bulk **bumpe le `last_seen_at` de la plupart des natifs** encore présents à chaque `full`, donc le lot stale reste petit (natifs réellement non réapparus + cross-imports, que rien dans le bulk ne bumpe).

- [x] Phase `refresh_stale` (`run_pipeline.py`), **à chaque run**, placée après `cross_imports` / avant `normalize`. Le seuil étale la charge (chaque passe ne ramasse que ce qui vient de franchir le délai) — pas de `LIMIT`/oldest-N.
- [x] Sélection : `last_seen_at < now() - STALE_REFRESH_AFTER_DAYS` (90 j, `common.py`), `not_found_at`/`disappeared_at` NULL.
- [x] Refetch **par DOI** via réutilisation des adapters `fetch_missing_doi` (`run_async` + `marker_handler`) : trouvé → bump `last_seen_at` + refresh `raw_data` ; 404 confirmé → `disappeared_at` ; erreur transitoire → laissé (retenté plus tard). Rows stale **sans DOI** → `disappeared_at` direct (`mark_undiscoverable_stale_disappeared`).
- [x] **Pas de filtre par source** : sous cadence normale theses (permanent) et wos (re-vu en full) ne sont jamais stale ; wos désabonné → erreur (pas 404) → non marqué.
- [x] Colonne `staging.disappeared_at` (migration `a7e3f1c9b5d2`). On **marque seulement** — aucune propagation/exclusion/suppression en aval tant que des cas concrets n'ont pas été observés (décision empirique bottom-up).
- [x] Pré-requis corrigé : ScanR/theses bumpent `last_seen_at` sur re-vu inchangé (commit séparé `614db8f5`).

## Questions ouvertes

**Cohabitation avec Unpaywall — décision : laisser tel quel.** `enrich_oa_status` interroge Unpaywall pour **tous** les DOI (`WHERE doi IS NOT NULL`, pas seulement « sans statut »), gated par `run_oa_status` (full). C'est une **API différente** (Unpaywall) de celles de `refresh_stale` (HAL/OpenAlex/ScanR/Crossref) → pas de conflit. On ne coordonne pas les deux. Note : comme le refetch périodique, ce balayage Unpaywall croît avec la rétention cumulative — même angle YAGNI que les quotas (cf. quota tokens OpenAlex), à surveiller sans agir.
