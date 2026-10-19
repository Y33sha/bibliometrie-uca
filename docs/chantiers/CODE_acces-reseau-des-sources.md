# Chantier — Accès réseau des sources

## Contexte

La boucle « chercher un identifiant, écrire le résultat dans `staging` » existe en cinq copies : `common/fetch_missing.py`, `common/fetch_stale.py`, `hal/fetch_missing.py`, `theses/fetch_missing.py`, `openalex/fetch_truncated.py`. Chacune range elle-même les trois issues : trouvé, introuvable, indisponible. `oa_status.py` (Unpaywall) et `enrich_journals_from_openalex.py` ont leur propre boucle réseau.

Trois mécanismes règlent le débit d'une source :

- une pause par worker après chaque requête : `request_delay_s` des `DoiSearch`, `HAL_DELAY`, `THESES_DELAY` ;
- le `Throttle` synchrone de WoS ;
- `RequestPace`, un rythme commun à tous les workers, employé par le Sudoc seulement.

Avec une pause par worker, le débit dépend du temps de réponse. Les réglages de WoS sont répétés dans `wos/fetch_missing.py` et `wos/fetch_stale.py`.

Le circuit-breaker circule par deux canaux. `access_source` le pose dans une ContextVar, que lisent les clients HTTP et `run_fetch_pool`. L'exécuteur des nœuds le passe aussi en argument, jusqu'aux callbacks `breaker_tripped=` des moissonneurs.

`http_retry.py` contient deux copies de la boucle de réessai, synchrone et asynchrone. À l'épuisement des réessais, la synchrone lève `SourceUnavailableError`, l'asynchrone l'erreur d'origine.

## Décisions

- Une boucle de recherche commune range les trois issues. Les cinq canaux la paramètrent.
- Le débit de chaque source est un budget en requêtes par seconde, appliqué par `RequestPace` dans la boucle commune.
- La ContextVar est le seul canal du circuit-breaker.
- Une machine à états sans I/O décide des réessais. Deux enveloppes, synchrone et asynchrone, l'exécutent.

## Phasage

### Phase 1 — Boucle de recherche commune

- [ ] Boucle commune et écriture des trois issues, pour les cinq canaux.

### Phase 2 — Débit

- [ ] Budget de débit par source, dans la configuration des sources.
- [ ] `RequestPace` à la place des pauses par worker et du `Throttle`.
- [ ] Débit réel de chaque source mesuré sur un run, avant et après.

### Phase 3 — Circuit-breaker

- [ ] Paramètre `breaker` retiré des nœuds et des callbacks des moissonneurs.

### Phase 4 — Réessais

- [ ] Machine à états des réessais et ses deux enveloppes, avec une seule issue à l'épuisement.

### Phase 5 — Documentation

- [ ] Mise à jour de `docs/pipeline`.

## Questions ouvertes

- Budget de débit des sources sans seuil publié : HAL, theses.fr, ScanR.
