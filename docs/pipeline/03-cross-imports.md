# `cross_imports` : Rattrapage cross-source

Deux étapes enchaînées, chacune adressant un cas distinct de "doc visible dans une source mais absent d'une autre".

**Étape 1 — `fetch_missing_hal_id` : HAL ids manquants.**
Télécharge depuis HAL les documents référencés (par hal-id ou NNT) dans d'autres sources mais absents de notre staging HAL. Code dans `infrastructure/sources/hal/fetch_missing_hal_id.py`. Auto-borné, tourne dans tous les modes : les hal-ids/NNT introuvables sont marqués `not_found=TRUE` dans staging et ne sont jamais re-interrogés (HAL = source native pour les hal-ids, un 404 est définitif).

**Étape 2 — `fetch_missing_doi` : DOI manquants par source.**
Pour chaque source cible (OpenAlex, HAL, WoS, ScanR, Crossref), recherche par DOI les records trouvés dans les autres sources mais absents de celle-ci. La plupart sont effectivement absents ; certains sont repêchés (cause : affiliations différentes selon source). Dispatcher dans `interfaces/cli/pipeline/fetch_missing_doi.py`, adapter par source dans `infrastructure/sources/<source>/fetch_missing_doi.py`. Sources cibles et scope (`unprocessed` vs `all`) déterminés par la policy du mode (cf. `domain/pipeline_modes.py`).

**Pourquoi les deux étapes ont des règles de scope différentes** : le pool de hal-ids/NNT à re-tenter est *fini par construction* (un hal-id non trouvé sort définitivement du pool via `not_found=TRUE`). À l'inverse, le pool de DOI à cross-importer est potentiellement non borné dans le modèle actuel — les DOI 404 chez HAL/OpenAlex/WoS/ScanR ne sont pas tracés, donc retentés à chaque run. D'où la scope policy : daily/weekly se limite aux DOI jamais tentés (`unprocessed`), full ré-essaie aussi les anciens (`all`), et WoS est exclu hors `full` à cause de son quota API contractuel.

Cette asymétrie disparaîtra avec le chantier `DATA_cycle-vie-staging.md` : un backoff temporel (`not_found_at` + `next_retry`) sur les sources non natives rendra le pool DOI également auto-borné et convergent.
