# Unpaywall

https://unpaywall.org/

Documentation API : https://unpaywall.org/products/api

Unpaywall n'est pas une source de publications : elle ne moissonne pas, elle n'alimente pas `staging`. C'est une **source d'enrichissement** consultée par DOI pour affiner `publications.oa_status` après l'agrégation multi-sources.

## API utilisée

**v2** (`https://api.unpaywall.org/v2/{doi}`) — interrogation unitaire par DOI.

- Polite pool obtenu via le paramètre `?email=...` (lu via `polite_pool_email`)
- Limites Unpaywall : 100 000 requêtes/jour, ~10 req/s recommandé. L'adapter limite à 5 requêtes concurrentes (`asyncio.Semaphore(5)`).
- Implémentation async (`httpx.AsyncClient`), comme tous les extracteurs unitaires par DOI (HAL/OpenAlex/WoS/ScanR/CrossRef `fetch_missing_doi`, `refetch_truncated`).

## Données récupérées

Une seule donnée consommée : le `oa_status` du payload Unpaywall, mappé sur l'enum canonique : `gold`, `hybrid`, `bronze`, `green`, `closed`.

## Particularités

### Pas de table source dédiée

Unpaywall n'a pas de `source_publications.source='unpaywall'` ; aucune trace en `staging`. L'enrichissement met à jour directement `publications.oa_status` via le repository, et n'archive pas le payload brut.

### Préservation du `diamond`

Unpaywall ne distingue pas le diamond OA du gold. [`enrich_oa_status`](https://github.com/Y33sha/bibliometrie-uca/blob/master/application/pipeline/enrich/enrich_oa_status.py) ne remplace **jamais** un statut `diamond` par un `gold` retourné par Unpaywall.

<!--TODO: possibilité d'utiliser pour le dédoublonnage publis? + récupérer un lien OA pour chaque publi?-->
