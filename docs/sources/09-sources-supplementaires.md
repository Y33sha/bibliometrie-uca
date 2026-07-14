# Sources supplémentaires

Sources externes interrogées pour **enrichir** les entités du référentiel (publications, revues, éditeurs). Différence avec les sources principales : elles ne moissonnent pas, n'alimentent pas la table `staging`, et n'ont pas de `source_publications.source=...` dédié. Les données récupérées sont écrites directement sur les tables canoniques via le repository concerné.

## Unpaywall

https://unpaywall.org/

Documentation API : https://unpaywall.org/products/api

Source d'enrichissement consultée par DOI pour affiner `publications.oa_status` après l'agrégation multi-sources.

### API utilisée

**v2** (`https://api.unpaywall.org/v2/{doi}`) — interrogation unitaire par DOI.

- Polite pool obtenu via le paramètre `?email=...` (lu via `polite_pool_email`).
- Limites Unpaywall : 100 000 requêtes/jour, ~10 req/s recommandé. L'adapter limite à 5 requêtes concurrentes (`asyncio.Semaphore(5)`).
- Implémentation async (`httpx.AsyncClient`), comme tous les extracteurs unitaires par DOI (HAL/OpenAlex/WoS/ScanR/CrossRef `fetch_missing_doi`, `refetch_truncated`).

### Données récupérées

Une seule donnée consommée : le `oa_status` du payload Unpaywall, mappé sur l'enum canonique : `gold`, `hybrid`, `bronze`, `green`, `closed`.

Consommée par la phase pipeline [`oa_status`](../pipeline/11-enrichissements.md#statut-open-access).

### Particularités

**Préservation du `diamond`** — Unpaywall ne distingue pas le diamond OA du gold. L'enrichissement ne remplace **jamais** un statut `diamond` par un `gold` retourné par Unpaywall.

<!--TODO: possibilité d'utiliser pour le dédoublonnage publis? + récupérer un lien OA pour chaque publi?-->

## DOAJ

https://doaj.org/ — Directory of Open Access Journals

Documentation API : https://doaj.org/api/v3/docs

Source d'enrichissement pour les revues, consultée par ISSN. Sa donnée canonique : « cette revue est-elle un journal open access certifié DOAJ, et à quelles conditions ? ». Consommée par le sub-step `enrich_journals_from_doaj` de la phase [`publishers_journals`](../pipeline/05-publishers-journals.md).

### API utilisée

`GET https://doaj.org/api/search/journals/issn:{issn}` — interrogation unitaire par ISSN. Retourne un wrapper `{total, results[]}` ; `total == 0` = revue absente de DOAJ.

- Polite pool via `User-Agent: bibliometrie-uca/1.0 (mailto:...)` (lu via `polite_pool_email`).
- Pas de quota documenté ; throttle `DOAJ_DELAY = 0.15s` (~6 req/s).
- Implémentation sync (requests), comme les autres sub-steps publishers/journals.
- Pas de retry élaboré : sur erreur réseau, on skip la revue (elle sera retentée à la prochaine fenêtre de stale).

### Données récupérées

Stockage : `journals.doaj_payload` (JSONB) + `journals.doaj_imported_at` (timestamptz) + `journals.is_in_doaj` (bool).

#### Format du payload (choix non orthodoxe)

Le payload stocké en base **n'est pas la réponse API brute**, mais un dict aux **mêmes clés que le dump CSV DOAJ** historiquement importé par `interfaces/cli/imports/import_doaj_csv.py`. Le mapping API→CSV est fait à l'extraction (`infrastructure/sources/doaj/__init__.py:to_csv_shape`).

Pourquoi ce choix :

- Le frontend `interfaces/frontend/src/routes/journals/[id]/+page.svelte` hardcode les clés CSV dans `READABLE_DOAJ_FIELDS` (`"Journal title"`, `"APC amount"`, etc.).
- L'audit APC OpenAlex vs DOAJ requête `doaj_payload->>'APC amount'`.
- L'import CSV reste utilisable pour un bootstrap rapide (`import_doaj_csv.py`), sans bascule de format.

Inconvénient assumé : on perd l'accès à certains champs API riches (taxonomie `subject` complète avec `scheme`/`code`, détails `license` au-delà du `type`, etc.) que personne ne consomme aujourd'hui.

Divergences API/CSV conservées telles quelles dans le mapper :

| Champ | CSV historique | API DOAJ (stocké tel quel) |
|---|---|---|
| `Country of publisher` | Nom long anglais (`United States`) | ISO-2 (`US`) |
| `Languages…` | Noms longs joints (`English\|French`) | Codes ISO-639-1 joints (`EN\|FR`) |

Une seule clé est ajoutée par rapport au CSV : `"DOAJ id"` (= `id` racine de la réponse API), utilisée pour reconstruire l'URL fiche DOAJ côté front (`https://doaj.org/toc/{id}`).

#### Stratégie de fetch

Pour chaque revue candidate, essai successif `issn` → `eissn` → `issnl` (doublons et NULL skippés), arrêt au premier hit. 1 à 3 requêtes / revue.

### Particularités

**Stale-based refresh** — Le sub-step ne refetche que les revues dont `doaj_imported_at` est `NULL` ou plus vieux que `stale_days` (30 j par défaut). Sur 404, le timestamp est mis à jour quand même (`doaj_payload = NULL`, `is_in_doaj = FALSE`) — la revue sort de la file pour 30 j et n'est pas re-interrogée à chaque run. Conséquence : un journal qui sort de DOAJ ne sera détecté qu'à son prochain refetch (≤ 30 j).

**Pas de reset global** — Contrairement à l'import CSV bootstrap (qui reset `is_in_doaj=FALSE` partout avant de re-marquer), le sub-step API est purement incrémental.

**Bootstrap CSV** — Le script `interfaces/cli/imports/import_doaj_csv.py` reste utilisable pour seeder rapidement depuis un dump complet téléchargé sur https://doaj.org/csv (~21 k revues, plus rapide qu'un fetch unitaire). Même format de stockage → pas de conflit avec le sub-step API.