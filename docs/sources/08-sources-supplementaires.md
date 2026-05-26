# Sources supplémentaires

Sources externes interrogées pour **enrichir** les entités du référentiel (publications, revues, éditeurs). Différence avec les sources principales : elles ne moissonnent pas, n'alimentent pas la table `staging`, et n'ont pas de `source_publications.source=...` dédié. Les données récupérées sont écrites directement sur les tables canoniques via le repository concerné.

## <span id="unpaywall"></span>Unpaywall

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

Consommée par la phase pipeline [`oa_status`](../pipeline/09-enrichissements.md#oa_status).

### Particularités

**Préservation du `diamond`** — Unpaywall ne distingue pas le diamond OA du gold. L'enrichissement ne remplace **jamais** un statut `diamond` par un `gold` retourné par Unpaywall.

<!--TODO: possibilité d'utiliser pour le dédoublonnage publis? + récupérer un lien OA pour chaque publi?-->

## <span id="doaj"></span>DOAJ

https://doaj.org/ — Directory of Open Access Journals

Documentation API : https://doaj.org/api/v3/docs

Source d'enrichissement pour les revues, consultée par ISSN. Sa donnée canonique : « cette revue est-elle un journal open access certifié DOAJ, et à quelles conditions ? ». Consommée par le sub-step `enrich_journals_from_doaj` de la phase [`publishers_journals`](../pipeline/04-publishers-journals.md).

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

## <span id="ror"></span>ROR

https://ror.org/ — Research Organization Registry

Documentation API : https://ror.readme.io/

Source de typage canonique pour les organismes éditeurs. Consommée par le sub-step `enrich_publishers_from_ror` de la phase [`publishers_journals`](../pipeline/04-publishers-journals.md) pour déduire `publishers.publisher_type` à partir du champ `types` ROR.

### API utilisée

`GET https://api.ror.org/v2/organizations/{ror}` — interrogation unitaire par ROR (pas de bulk dispo).

- Polite pool via `User-Agent: bibliometrie-uca/1.0 (mailto:...)`.
- Limites : 2 000 requêtes / 5 min sustained (≈ 6.66 req/s), 100 req / 10 s en burst. Throttle `ROR_DELAY = 0.15s` (sous le seuil sustained).
- Pas de retry élaboré : skip sur 404 / erreur réseau.

### Données récupérées

Champ `types` du record ROR (`Company`, `Education`, `Government`, `Nonprofit`, `Archive`, etc.), mappé sur l'enum applicatif `publisher_type` :

| ROR `types` | `publisher_type` |
|---|---|
| `education[+funder]` | `academic_institution` |
| `nonprofit` seul, `funder+nonprofit` | `learned_society` |
| `company[+funder]` | `commercial` |
| `archive[+facility]` | `repository` |
| autres (`government`, `facility`, `other`, `healthcare`) | NULL (laisse `publisher_type='unknown'` pour arbitrage manuel) |

Mapping figé dans `domain.publishers.publisher.map_ror_types`.

### Particularités

Le `publishers.ror` lui-même est posé en amont par le sub-step `enrich_publishers_from_openalex` (depuis `ids.ror` d'OpenAlex Publishers). Pas de matching ROR par nom : trop fragile. Les publishers sans `openalex_id` restent à `ror=NULL` et `publisher_type='unknown'` (arbitrage admin).
