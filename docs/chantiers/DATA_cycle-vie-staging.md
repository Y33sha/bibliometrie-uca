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
- [`hal/fetch_missing_hal_id.py`](../../infrastructure/sources/hal/fetch_missing_hal_id.py) — hal-id 404 dans HAL (source native) → **définitif** (HAL dédoublonne, le doc n'existe plus).
- [`crossref/fetch_missing_doi.py`](../../infrastructure/sources/crossref/fetch_missing_doi.py) — DOI 404 chez Crossref (source native pour les DOI Crossref) → **définitif** (DOI erroné ou non Crossref).

Les 4 autres sources qui font du `fetch_missing_doi` (HAL, OpenAlex, WoS, ScanR) n'écrivent **rien** quand un DOI n'est pas trouvé. Conséquence : ces DOI sont retentés à chaque run (croissance non bornée du pool, coût API qui monte avec le temps).

La sémantique correcte : un identifiant cherché sur sa **source native** + 404 = définitif ; cherché sur une **autre source** + 404 = à retenter après un délai (la source peut indexer plus tard).

**3. Fraîcheur des données / publications disparues.** Item TODO existant : *"Mettre en place le process pour détecter les publications disparues et les nettoyer de la base (ou les archiver ?). + publis du cross-import : re-fetch régulier pour tenir les données à jour."*

Aujourd'hui :
- `staging.last_seen_at` est mis à jour à chaque ré-extraction d'un même doc → permet de détecter les disparus mais aucune action n'est branchée.
- Les publications obtenues via cross-import DOI ne sont jamais re-fetchées : leurs métadonnées vieillissent silencieusement.

## Décisions

### Modélisation `not_found` : deux colonnes lisibles

Remplacer le `not_found BOOL` par deux colonnes temporelles plus parlantes :

| Colonne | Sémantique | Quand peuplée |
|---|---|---|
| `not_found_at TIMESTAMPTZ NULL` | Date de la dernière tentative négative | Toutes les rows non trouvées (définitives ou temporaires) |
| `next_retry TIMESTAMPTZ NULL` | Date minimum de re-tentative ; NULL = définitif | Uniquement les rows temporaires (cross-imports non natifs) |

`not_found_at IS NOT NULL` remplace fonctionnellement l'ancien `not_found=TRUE`. La nature définitive vs temporaire se lit sur `next_retry` :
- `next_retry IS NULL` → définitif (source native ; jamais re-tenter)
- `next_retry > NOW()` → en attente
- `next_retry <= NOW()` → à retenter au prochain run

### États observables

| État | `processed` | `not_found_at` | `next_retry` | `raw_data` |
|---|---|---|---|---|
| À traiter | FALSE | NULL | NULL | plein |
| Normalisée | TRUE | NULL | NULL | `{}` |
| Non trouvée (définitif) | TRUE | timestamp | NULL | `{}` |
| Non trouvée (backoff) | TRUE | timestamp | timestamp | `{}` |

### CHECK SQL

Minimal, ne verrouille que les combinaisons sémantiquement absurdes :

```sql
CHECK (
    -- not_found_at terminal : ne peut pas coexister avec processed=FALSE
    (not_found_at IS NULL OR processed)
    AND
    -- next_retry n'a de sens que si not_found_at peuplé
    (next_retry IS NULL OR not_found_at IS NOT NULL)
)
```

### Politique de fraîcheur (esquisse, à affiner en Phase 3)

- **Disparition** : une publication n'a pas eu de `last_seen_at` mis à jour depuis N runs successifs du mode où elle aurait dû apparaître → marquée `disappeared_at`. À décider : N, granularité (par mode ?), action (DELETE, archive en table dédiée, ou simple flag).
- **Re-fetch périodique** : les publications anciennes (notamment celles obtenues via cross-import qui ne reviennent jamais dans une moisson native) doivent être re-fetchées régulièrement pour rafraîchir les métadonnées. Stratégie possible : re-fetch toutes les publis dont `updated_at < NOW() - X mois` en mode `full`.

## Phasage

### Phase 1 — Machine à états documentée + CHECK minimal

Avant tout le reste, formaliser l'existant.

- Migration : `ALTER TABLE staging ADD CONSTRAINT staging_state_valid CHECK (NOT not_found OR processed)` (état actuel, 3 colonnes).
- `donnees.md` : ajout d'une section "Cycle de vie d'une row `staging`" avec le tableau des 3 états + diagramme de transitions.

Petit, livrable indépendamment du reste. Sert de base pour les phases suivantes.

### Phase 2 — Backoff `not_found_at` / `next_retry`

- Migration :
  - `ADD COLUMN not_found_at TIMESTAMPTZ NULL`, `ADD COLUMN next_retry TIMESTAMPTZ NULL`
  - Backfill : `UPDATE staging SET not_found_at = imported_at WHERE not_found = TRUE` (rows existantes traitées comme définitives, ce qu'elles sont vu la sémantique actuelle Crossref + hal-id)
  - `DROP COLUMN not_found`
  - Nouveau CHECK consolidé (cf. ci-dessus)
- Code :
  - `hal/fetch_missing_hal_id.py` : `not_found_at=NOW()`, `next_retry=NULL` (définitif)
  - `crossref/fetch_missing_doi.py` : idem (Crossref = source native pour DOI Crossref, donc définitif)
  - **Nouveaux INSERTs** dans `hal/fetch_missing_doi.py`, `openalex/fetch_missing_doi.py`, `wos/fetch_missing_doi.py`, `scanr/fetch_missing_doi.py` : `not_found_at=NOW(), next_retry=NOW() + INTERVAL '30 days'` (à valider : 30 jours)
  - Adaptation de `infrastructure/sources/common.py:get_cross_import_dois` : inclure dans le pool à retenter les DOI avec `next_retry <= NOW()` (cf. requête ci-dessous)
- Doc `pipeline.md` : clarifier le comportement du cross-import DOI avec backoff.

Requête `get_cross_import_dois` adaptée :

```sql
SELECT DISTINCT s.doi FROM staging s
WHERE s.source != :target AND s.doi IS NOT NULL [AND s.processed = FALSE]
  AND NOT EXISTS (
      SELECT 1 FROM staging t
      WHERE t.source = :target AND t.doi = s.doi
        AND (t.not_found_at IS NULL OR t.next_retry IS NULL OR t.next_retry > NOW())
        -- présent ET (trouvé OU définitif OU pas encore l'heure)
  )
```

**Conséquence sur la scope policy `cross_imports`.** Aujourd'hui, l'étape 2 (DOI) a une scope policy `unprocessed` vs `all` parce que le pool de DOI à re-tenter n'est pas borné (les 404 chez HAL/OpenAlex/WoS/ScanR ne sont pas tracés → retentés à chaque run). L'étape 1 (hal-id) tourne *auto-bornée* parce que son pool est fini par construction (hal-id 404 → sort définitivement via `not_found=TRUE`).

Avec le backoff de cette phase, le pool DOI devient lui aussi auto-borné et convergent : 1er pass tente tout, les 404 reçoivent `next_retry`, les passes suivantes ne retentent que ceux dont `next_retry <= NOW()`. L'asymétrie disparaît : les deux étapes deviennent auto-bornées, et la scope policy `unprocessed` vs `all` perd sa raison d'être.

À traiter dans cette phase : retirer le champ `fetch_missing_doi_scope` de `ModePolicy` et le flag `--all` du CLI `interfaces/cli/pipeline/fetch_missing_doi.py`, simplifier `phase_cross_imports` en conséquence. Note : la distinction sources (`fetch_missing_doi_sources`, qui exclut WoS hors `full` pour son quota API) reste pertinente — c'est un critère orthogonal au backoff.

### Phase 3 — Détection des publications disparues

- Définir la politique : N runs ? N jours ? Action ?
- Mécanisme : phase pipeline qui détecte les `staging` avec `last_seen_at` ancien sur le périmètre attendu (les modes `full`/`weekly` couvrent une plage d'années connue, donc une absence est détectable).
- Action : à décider entre DELETE cascade, ARCHIVE (table dédiée), ou flag `disappeared_at` qui les exclut des requêtes API par défaut.

### Phase 4 — Re-fetch périodique

- Identifier les publications "anciennes" (cross-import non rafraîchi, métadonnées vieillissantes).
- Stratégie de re-fetch : sur quelle clé (DOI / source_id natif) ? À quelle fréquence ? En quel mode ?
- Probablement une nouvelle phase pipeline ou une option du fetch_missing_*.

## Questions ouvertes

**Phase 2 — `source_id` pour les not_found des cross-imports non natifs.**
Quand HAL/OA/WoS/ScanR `fetch_missing_doi.py` insère un stub not_found pour un DOI, il faut un `source_id` (UNIQUE `(source, source_id)`). Le DOI n'est pas l'id natif de ces sources. Trois options :
- **Préfixe convention** : `source_id = 'doi:10.1234/foo'` pour les stubs not_found. Lisible, pas de collision, à documenter.
- **Table séparée `doi_lookups (source, doi, not_found_at, next_retry)`** : sémantiquement plus propre (ce ne sont pas vraiment des stagings — pas de payload, pas de cycle de normalisation). Un objet de plus à maintenir.
- **Accepter la collision potentielle** : utiliser le DOI tel quel. Si plus tard la source indexe le doc sous un id natif différent, on aurait deux rows dans staging. `ON CONFLICT` ne déclenche pas (clés différentes). Nettoyage possible à la marge.

**Phase 2 — Délai de backoff (le `N` du `NOW() + N days`).** Le TODO original suggère 30 jours. À confirmer ou paramétrer (env var ? table `config` ?).

**Phase 3 — Critère de disparition.** N runs successifs sans mise à jour de `last_seen_at` ? Période minimum en jours ? Granularité par mode (un doc visible en `full` mais pas en `weekly` n'est pas "disparu") ?

**Phase 3 — Action sur disparition.** DELETE cascade (perte historique), table archive `staging_archived` (conservation, complexité +1), flag `disappeared_at` sur staging (la row reste mais exclue des requêtes par défaut) ? Idem côté `source_publications` et publications canoniques.

**Phase 4 — Stratégie de re-fetch.** Re-fetch tous les K mois ? Re-fetch quand `last_seen_at` est ancien ? Quel impact sur les quotas API (notamment WoS) ?

**Cohabitation avec le statut OA via Unpaywall.** Aujourd'hui `enrich_oa_status` rafraîchit le statut OA depuis Unpaywall pour les publis sans statut. Le re-fetch périodique pourrait soit le compléter (re-fetch toutes les métadonnées en plus du statut OA), soit s'aligner sur la même fréquence pour limiter les appels API.

Note extraite du chantier "couverture-tests":
- **Fonction de coût de l'aiguillage HAL `extract_collection`.** Une fois la branche choisie pinée par test (Phase 1, décision 1bis), l'heuristique actuelle (`len(orphans) < full_fetch_pages`) reste insatisfaisante : elle compte les requêtes mais ignore la taille de payload, ce qui sur les requêtes umbrella (PRES_UCA) inverse le bon choix. Pistes à arbitrer : (a) borne dure sur les orphelins (« si `orphans < N`, toujours individuel »), (b) cost function pondérée payload (poids par source via `hal_per_page_for`), (c) compteur empirique sur les derniers runs. Décision distincte de l'extraction `parsing.py`, à ouvrir une fois les tests posés.
