# Phase personnes — lisibilité et refonte

## Contexte

La phase `persons` (`application/pipeline/persons/`) enchaîne enforce → reset → match → create → populate → purge sur une transaction unique. Une relecture à froid en outsider fait ressortir plusieurs points qui feraient tiquer un nouveau venu, dont certains lourds concentrés dans `cascade.py`. Cette fiche les regroupe pour un traitement dédié, distinct de la passe de lisibilité générale (`CODE_lisibilite.md`).

## Décisions

À trancher au fil du chantier ; le Phasage ci-dessous liste les pistes, pas des choix arrêtés.

## Phasage

### cascade.py — désengorger

- [x] Data-loading (`EnrichedAuthorship`, `_enrich`, les `get_*`, `load_linked_authorships_by_pub`) sorti dans `loading.py` ; `CascadeResult` + `build_metrics` dans `metrics.py`. `cascade.py` ne garde que `_Cascade` et les passes (`c68dc4eb`).
- [x] `match`/`create` factorisés dans `_run_pass`, paramétré par `decide` et `on_create` ; le double `_Cascade` (double-fetch voulu) est conservé (`fd01fec4`).
- [x] `_max_authors_per_pub` : le gate méga-paper est **supprimé**. Mesure faite (run persons complet, seuil relevé à 10000) : la durée reste dans la norme — le cross-source ne compare qu'à la position exacte, pas tout-contre-tout, donc le gate ne servait pas la perf. Constante `MAX_AUTHORS_CROSS_SOURCE`, paramètre `total_author_count` et agrégat Python retirés (`0a1e927e`). Le rework par-SP envisagé devient sans objet.
- [x] Logs de phase dé-jargonnés (plus de nom de fonction Python, table temporaire, « GC » ni « SQL ») ; chaque étape annonce son départ (fin des longs silences) ; bilan par méthode de rattachement re-logué en fin de phase (`31dc69ce`).

### Boundary services

- [x] Moitié `link` levée : la cascade appelle le singulier typé `link_authorship(person_id, source, authorship_id, …)` ; le batch `link_authorships`, dont elle était l'unique appelant, est supprimé (`9b89934a`). `add_identifiers_from_authorships` reste en API batch dict, assumée : partagée avec les CLI de maintenance, et `BareUnlinkedAuthorship` n'a pas de champ `idhal` (la typer brasserait le futur matching idhal).

### Docstrings

- [x] `phase.py` : pourquoi du mono-transaction énoncé, ordre-indépendance découplée (`afe969ec`). Docstrings-fleuves : le volume venait surtout de la taille du fichier d'avant-découpe ; une fois `cascade.py` scindé, sa docstring mappe exactement son contenu (les cinq signaux, les deux populations, la corroboration) au bon niveau, et `reset`/`purge`/`populate`/`resolve` portent du rationale substantiel. Pas de resserrage imposé — la matière relue est jugée à sa place.

### Optimisation du matching cross-source

Le `reset` détache en bloc toutes les signatures résolues en cross-source (~75 000 par run) pour les recalculer, alors que le cross-source est une **fonction pure des ancres fermes** : un résultat cross-source n'ancre jamais un autre (seuls identifiant / nom / création entrent dans l'index d'ancrage, cf. `apply_match`). L'écrasante majorité se ré-attache à l'identique — du churn à vide. Cible : recompute **incrémental** contre les ancres fermes, sans passer par la destruction. Inchangé → no-op ; ancre déplacée → update ; ancre disparue → détaché. Résultat identique à la reconstruction actuelle, churn réduit à ce qui change réellement.

Livré : plumbing `current_person_id` (`2fcbb896`), logique incrémentale (`c8f387fd`).

#### Ancrage sur les liens fermes

- [x] `fetch_linked_authorships` ne charge que les liens fermes (`resolution_mode IS DISTINCT FROM 'cross_source'`), explicitement.

#### Reset

- [x] `reset` ne détache plus le cross-source ; il ne fait que l'arbitrage des conflits d'identifiant. `reset_cross_source` (le wipe) est remplacé par `detach_authorships(ids)` (détachement ciblé).

#### Ré-évaluation incrémentale

- [x] La cascade fetche aussi les signatures **déjà liées en cross-source** (`get_cross_source_candidates`, avec `current_person_id`) et les re-juge dans le pool, aux deux passes.
- [x] `apply_match` : même personne en cross-source → no-op (pas d'écriture, pas d'ancrage) ; sinon écriture. Les candidates re-résolues sont mémorisées (`resolved_cross_source_ids`) ; le complément (candidates − résolues) est détaché en fin de phase par `detach_authorships`.

#### Métriques et observabilité

- [x] `cross_source_detached` (signatures sans appui) remplace `reset_cross_source` dans le résumé de phase et est surfacé dans l'UI admin. Le bilan par méthode compte les résolutions nouvelles ou changées, pas les ré-affirmations.

#### Tests

- [x] Ordre-indépendance et idempotence restent verts (le résultat est identique à la reconstruction). Le test du wipe est remplacé par un test de `detach_authorships` (par id, protège les épinglés).

#### Conception arrêtée

- Deux passes `match`/`create` **conservées** : orthogonales au cross-source (elles ordonnent match ferme puis création, qui ancre le cross-source de ses co-signatures). Un éventuel collapse en une passe serait un chantier séparé.
- Toutes les signatures cross-source sont re-jugées chaque run (pool de candidats) — le ripple de l'arbitrage d'identifiant est ainsi couvert. Pas de `link_authorship` conditionnel finalement : la cascade saute elle-même l'écriture d'une ré-affirmation à l'identique. Le détachement des sans-appui est un SQL final ciblé par ids (pas dans la passe `create`).
