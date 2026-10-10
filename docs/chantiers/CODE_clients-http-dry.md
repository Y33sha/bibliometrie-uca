# Chantier — Clients HTTP des sources : gestion d'erreur commune

## Contexte

Plusieurs phases interrogent une source élément par élément : un DOI, un préfixe, un identifiant. Une requête a trois issues :

- l'élément est trouvé ;
- l'élément est absent de la source : la source répond correctement, sans résultat ;
- la source est indisponible : erreur réseau, 429 ou 5xx après les nouvelles tentatives, réponse illisible, source coupée par le disjoncteur.

Seule une absence confirmée autorise à enregistrer l'élément comme vérifié. Une source indisponible laisse l'élément en attente du run suivant.

Les nouvelles tentatives, le disjoncteur et le pool de workers sont communs (`infrastructure/sources/http_retry.py`, `infrastructure/sources/circuit_breaker.py`, `application/pipeline/_fetch_pool.py`). Le classement des issues est propre à chaque client, avec des conventions différentes. Deux clients rendent la même valeur pour l'absence et pour l'indisponibilité :

- Unpaywall : une panne pose `unpaywall_checked_at`, donc la vérification est reportée du délai de revérification ;
- préfixes DOI Crossref et DataCite : une panne pose `publisher_checked_at`, et le préfixe n'est jamais retenté.

## Décisions

- **Un type commun à trois issues** dans `application/ports/pipeline/lookup.py` : la valeur trouvée, `NOT_FOUND`, `UNAVAILABLE`.
- **Une fonction commune classe les exceptions d'une requête** : un statut d'absence donne `NOT_FOUND`, toute autre erreur donne `UNAVAILABLE`. Le statut d'absence vaut 404 par défaut ; chaque client fixe le sien (aucun pour un endpoint de recherche, 400 pour WoS).

## Phasage

### Phase 1 — Type commun

- [x] Créer le type commun. `fetch_stale` l'adopte et rend `UNAVAILABLE` au lieu de `None`.

### Phase 2 — Unpaywall

- [x] Fonction de classement des exceptions dans `http_retry.py` : `lookup_json_async`.
- [x] Le client Unpaywall rend le type commun. La phase `oa_status` pose `unpaywall_checked_at` seulement sur un élément trouvé ou absent.
- [x] La phase `oa_status` tourne sous disjoncteur.

### Phase 3 — Préfixes DOI

- [x] Les clients de préfixes Crossref et DataCite passent en asynchrone et rendent le type commun. `resolve_publishers` les interroge en concurrence par `run_fetch_pool`. `publisher_checked_at` est posé seulement sur un préfixe trouvé ou absent.

### Phase 4 — Autres clients

- [x] `fetch_stale` : les adapters utilisent `lookup_json_async`. Les endpoints de recherche (HAL, theses.fr, ScanR) ne lisent pas un 404 comme une absence.
- [ ] `fetch_missing` : recherche par DOI et par identifiant HAL.
- [ ] `fetch_truncated`.
