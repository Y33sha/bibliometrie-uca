# Chantier — Observabilité et robustesse du pipeline

## Contexte

Deux manques persistants sur la production du pipeline, identifiés de
longue date mais jamais instruits comme chantier dédié :

1. **Aucun check automatique sur les données produites.** À l'issue
   d'un run pipeline, rien ne valide que les comptages sont
   plausibles, qu'on n'a pas explosé les orphelins (publications
   sans authorships, persons sans publications, etc.), ou qu'aucune
   anomalie statistique n'apparaît dans les distributions
   (years, doc_types, sources, OA status…). Un run silencieusement
   cassé peut passer en prod sans alerte. Cf. l'esprit des « tests de
   caractérisation » : on capture la forme attendue des données et on
   alerte sur la dérive.

2. **Dashboard métriques partiel.** Des éléments existent
   (`/admin/pipeline` lit des rapports, certaines métriques de pool DB
   sont remontées) mais c'est éparpillé et fragile. Pas de vue
   consolidée temps de réponse / pool DB / taux d'erreur / durée des
   phases.

## Dépendance — audit-cto

Le volet « dashboard métriques » a un pré-requis dans
[CODE_audit-cto.md](CODE_audit-cto.md) Phase 1 option A' : chaque phase
écrit un `logs/metrics/<phase>.json` en fin de run, l'orchestrateur lit
ces JSON au lieu de parser les logs. Tant que ce pré-requis n'est pas
fait, tout dashboard construit ici reposera sur du parsing de logs
fragile. **Ne pas démarrer le volet dashboard avant que A' soit
tranché et appliqué.**

**Sous-chantier inclus dans A' : sweep `subprocess → import direct`.**
Aujourd'hui `run_pipeline.py` invoque 10 scripts via `subprocess.run(...)`
(les 5 extracteurs + `refetch_truncated`, `fetch_missing_hal_id`, le
dispatcher `fetch_missing_doi`, `detect_address_countries`,
`suggest_address_countries`). Ces invocations ne peuvent pas retourner
de métriques typées — la seule récupération possible est du parsing de
stdout/stderr, fragile. Pour que l'option A' fonctionne proprement,
chaque script doit exposer sa logique de `main()` en fonction
réutilisable (`extract_hal(...) -> ExtractStats`, etc.) que
l'orchestrateur appelle en import direct, reçoit la struct typée, et
sérialise en JSON métrique. Coût estimé : ~3-5 h pour le sweep
complet (extraction de `main()` en fonction + thin wrapper CLI +
adaptation `run_pipeline.py`). Pas de perte d'isolation processus en
pratique : le `try/except` actuel dans la boucle de phases capture
déjà les exceptions au niveau orchestrateur.

Le volet « checks post-pipeline » est indépendant : il consomme l'état
final de la base, pas les métriques de phases.

## Décisions

1. **Deux volets séparés** (checks data / dashboard), pilotables
   indépendamment. Le volet checks peut démarrer immédiatement ; le
   volet dashboard attend A'.
2. **Checks = tests de caractérisation, pas tests fonctionnels.** Le
   but est de capturer la forme attendue (ranges, ratios, comptages)
   et d'alerter quand la sortie dérive — pas de figer une vérité.
3. **Sortie des checks = rapport lisible + exit code.** Format à
   trancher (JSON pour intégration future, markdown pour lecture).
   Pas de notification email à ce stade — Laura lit les runs à la
   main.
4. **Pas d'outil externe pour le dashboard.** Pas de Grafana, pas de
   Prometheus tant que l'app est mono-utilisateur. Page admin
   FastAPI/Svelte qui lit les JSON métriques et la base, c'est
   suffisant pour le périmètre actuel.

## Phasage

### Volet A — Checks automatiques post-pipeline

- [ ] **Inventorier les invariants attendus** sur les données
  produites. Au minimum :
  - Comptages : publications actives, persons, authorships,
    structures, addresses (deltas vs run précédent)
  - Orphelins : publications sans authorships, persons sans
    publications, authorships sans person, source_authorships
    sans authorship_id
  - Distributions : years (queue/médiane/mode), doc_types,
    sources, OA status
  - Cohérence : `truth_authorships` ⊆ `authorships`, totaux
    `source_authorships` par source cohérents avec les staging
- [ ] **Implémenter un module `application/pipeline/checks.py`**
  exposant `run_checks(conn) -> CheckReport` (queries SQL, calcul
  des deltas, comparaison à un snapshot du run précédent stocké en
  base).
- [ ] **Hook en fin de `run_pipeline.py`** : exécution
  automatique, exit code non-zéro si seuil critique dépassé.
- [ ] **Page admin** affichant le dernier rapport (réutilise
  l'infrastructure de `/admin/pipeline`).

### Volet B — Dashboard métriques

**Bloqué tant que audit-cto Phase 1 (option A') n'est pas appliquée.**

- [ ] **Modèle de données métriques** : qu'est-ce qu'on stocke,
  comment (table dédiée ? `logs/metrics/*.json` parsés à la
  demande ?).
- [ ] **Page `/admin/metrics`** : agrégation des
  `logs/metrics/<phase>.json` (option A') + métriques pool DB
  (déjà remontées) + taux d'erreur HTTP par source (à exposer
  depuis les adapters async).
- [ ] **Vue historique** : N derniers runs en série temporelle
  (durée par phase, volumes, taux d'erreur).

## Questions ouvertes

- **Format de stockage du snapshot** pour la comparaison
  inter-runs (volet A) : table dédiée, fichier JSON sur disque,
  ou colonne sur `audit_log` ? Trancher avant d'implémenter.
- **Seuils d'alerte** : on les hardcode ou on les rend
  configurables ? Probablement hardcodés au début, configurables
  plus tard si besoin.
- **Volet B vs Grafana DSI** : si la DSI met en place sa propre
  observabilité (logs centralisés, Grafana…) une fois la
  transmission faite, le volet B peut devenir inutile. À
  reconsidérer au moment de la transmission. En attendant, une
  page admin minimaliste suffit.
