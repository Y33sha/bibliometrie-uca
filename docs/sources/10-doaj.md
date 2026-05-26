# DOAJ

https://doaj.org/ — Directory of Open Access Journals

Documentation API : https://doaj.org/api/v3/docs

DOAJ n'est pas une source de publications : il ne moissonne pas, il n'alimente pas `staging`. C'est une **source d'enrichissement** pour les revues, consultée par ISSN. Sa donnée canonique : « cette revue est-elle un journal open access certifié DOAJ, et à quelles conditions ? ».

## API utilisée

`GET https://doaj.org/api/search/journals/issn:{issn}` — interrogation unitaire par ISSN. Retourne un wrapper `{total, results[]}` ; `total == 0` = revue absente de DOAJ.

- Polite pool via `User-Agent: bibliometrie-uca/1.0 (mailto:...)` (lu via `polite_pool_email`).
- Pas de quota documenté ; throttle `DOAJ_DELAY = 0.15s` (~6 req/s).
- Implémentation sync (requests), comme les autres sub-steps publishers/journals.
- Pas de retry élaboré : sur erreur réseau, on skip la revue (elle sera retentée à la prochaine fenêtre de stale).

## Données récupérées

Stockage : `journals.doaj_payload` (JSONB) + `journals.doaj_imported_at` (timestamptz) + `journals.is_in_doaj` (bool).

### Format du payload (choix non orthodoxe)

Le payload stocké en base **n'est pas la réponse API brute**, mais un dict aux **mêmes clés que le dump CSV DOAJ** historiquement importé par `interfaces/cli/imports/import_doaj_csv.py`. Le mapping API→CSV est fait à l'extraction (`infrastructure/sources/doaj/__init__.py:to_csv_shape`).

Pourquoi ce choix :
- Le frontend `interfaces/frontend/src/routes/journals/[id]/+page.svelte` hardcode les clés CSV dans `READABLE_DOAJ_FIELDS` (`"Journal title"`, `"APC amount"`, etc.).
- L'audit APC prévu (audit OpenAlex vs DOAJ) requête `doaj_payload->>'APC amount'`.
- L'import CSV reste utilisable pour un bootstrap rapide (`import_doaj_csv.py`), sans bascule de format.

Inconvénient assumé : on perd l'accès à certains champs API riches (taxonomie `subject` complète avec `scheme`/`code`, détails `license` au-delà du `type`, etc.) que personne ne consomme aujourd'hui.

Divergences API/CSV conservées telles quelles dans le mapper (pas d'effort de normalisation supplémentaire vers le format CSV historique) :

| Champ | CSV historique | API DOAJ (stocké tel quel) |
|---|---|---|
| `Country of publisher` | Nom long anglais (`United States`) | ISO-2 (`US`) |
| `Languages…` | Noms longs joints (`English\|French`) | Codes ISO-639-1 joints (`EN\|FR`) |

Une seule clé est ajoutée par rapport au CSV : `"DOAJ id"` (= `id` racine de la réponse API), nécessaire pour reconstruire l'URL fiche DOAJ côté front (`https://doaj.org/toc/{id}`).

### Stratégie de fetch

Pour chaque revue candidate, essai successif `issn` → `eissn` → `issnl` (doublons et NULL skippés), arrêt au premier hit. 1 à 3 requêtes / revue.

## Particularités

### Pas de table source dédiée

DOAJ n'a pas de `source_publications.source='doaj'` ; aucune trace en `staging`. L'enrichissement met à jour directement `journals.doaj_payload` via le repository.

### Stale-based refresh

Le sub-step `enrich_journals_from_doaj` ne refetche que les revues dont `doaj_imported_at` est `NULL` ou plus vieux que `stale_days` (30 j par défaut). Sur 404, le timestamp est mis à jour quand même (`doaj_payload = NULL`, `is_in_doaj = FALSE`) — la revue sort de la file pour 30 j et n'est pas re-interrogée à chaque run.

Conséquence : un journal qui sort de DOAJ ne sera détecté qu'à son prochain refetch (≤ 30 j). Acceptable vu la rareté de l'événement.

### Pas de reset global

Contrairement à l'import CSV bootstrap (qui reset `is_in_doaj=FALSE` partout avant de re-marquer), le sub-step API est purement incrémental.

### Bootstrap CSV

Le script `interfaces/cli/imports/import_doaj_csv.py` reste utilisable pour seeder rapidement depuis un dump complet téléchargé sur https://doaj.org/csv (~21 k revues, plus rapide qu'un fetch unitaire). Même format de stockage → pas de conflit avec le sub-step API.
