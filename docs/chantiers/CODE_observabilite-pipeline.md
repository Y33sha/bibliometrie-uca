# Chantier — Observabilité du pipeline

Commencé le 2026-05-16.

## Contexte

Le pipeline se lance rarement d'un bloc : extraction sur une plage d'années custom, `cross_imports` interrompu s'il est trop long, reprise en `--from normalize`. L'observabilité doit suivre cet usage. Le système en place ne produit un instantané que pour un **run complet** (gardé par `not args.only and not args.from_phase` dans `run_pipeline.py`), agrégeant l'état global de la base et les métriques de toutes les phases dans un seul payload `pipeline_run_snapshots`. Les runs partiels — le cas courant — ne produisent rien. La page admin associée (onglets Snapshots / Rapports, composant monolithique) est inadaptée à cet usage.

Besoin primaire : **savoir d'un coup d'œil si un run s'est bien passé**, phase par phase, y compris pour un run partiel ou automatisé — vert quand il n'y a rien à regarder, rouge quand une phase échoue sur exception, ambre quand quelque chose est à signaler (interruption contrôlée par l'utilisateur, source indisponible, arrêt après une série de 429). Avoir aussi une idée du temps pris et repérer une phase anormalement lente. Besoin secondaire : suivre l'évolution des volumes dans la durée.

## Décisions

### Modèle de données

**Unité de persistance = une exécution de phase**, pas un run. Chaque fois qu'une phase tourne (même seule), un enregistrement : phase, `run_id`, `started_at`/`ended_at`, mode, sources, `status` (ok / error / warning), signaux structurés, observable d'entrée (capturé au début de la phase), observable de sortie et métriques (`PhaseMetrics`, capturés à la fin). Aucune condition « run complet ».

**Pas de table de runs.** Un `run_id` (entier de séquence, généré au lancement) est une colonne de la table des exécutions de phase. Tout ce qui est « par run » est dérivable par agrégation (`début = min`, `fin = max`, mode et sources communs, statut global = le pire des statuts de phase) ; une table parente ne répèterait que du dérivable.

**Statut et signaux.** `status = error` est décidé par l'orchestrateur lorsqu'une phase remonte une exception. Une interruption par l'utilisateur est un `status = warning` (action contrôlée — écourter un import n'est pas un échec), pas une erreur. `status = warning` et les signaux (source indisponible, arrêt après une série de 429, `CannotAttributeConflict` pendant `persons`…) sont aussi **remontés par la phase elle-même** : ils enrichissent sa valeur de retour, là où ils ne partent aujourd'hui qu'en log et sont perdus. C'est la part de plumbing la plus lourde du chantier, concentrée dans `extract` et `persons`.

### Observables et durée : affichés, non jugés

Chaque phase relève le volume des tables qu'elle touche au début et à la fin de son exécution (avant / après) ; le drill-down les montre tels quels. Pour une phase de transformation, c'est l'entrée consommée et la sortie produite (`normalize` : staging → source_publications) ; pour une phase qui enrichit ou accumule en place, c'est l'avant / après d'une même table (`resolve_ra` : doi_prefixes au début et à la fin, dont le delta donne les nouveaux préfixes). On n'en dérive **pas** de ratio de rendement : un tel ratio (sortie / entrée) n'est pas comparable d'une phase à l'autre — facteur de dédup pour `publications`, quasi-1 pour les enrichissements en place — et serait plus trompeur qu'utile. Ce qui parle, ce sont les volumes avant / après, les compteurs `PhaseMetrics` (new / updated…) et l'écart de durée. Le rendu du drill-down est **sur-mesure par phase** : chaque phase remonte ses indicateurs propres dans un `details` libre, et l'interface les affiche selon leur forme — les phases multi-sources (`extract`…) présentent une table par source (trouvés / nouveaux / màj / inchangés / durée), les autres l'avant / après de leurs tables.

**Aucune détection automatique de dérive.** Le drill-down affiche la durée totale d'une phase et sa durée rapportée au volume traité (secondes par élément). La comparaison au médian historique est calculée à la lecture mais **pas surfacée pour l'instant** (peu pertinente quand les durées sont courtes ; à réintroduire si le besoin se confirme), sans seuil ni drapeau dans tous les cas. Poser un critère objectif de dérive sur un corpus de quelques milliers de publications, aux runs hétérogènes (daily mono-source vs full multi-sources), produirait surtout du bruit.

### Une seule surface : l'interface graphique

La page `/admin/pipeline` est l'unique surface d'observabilité. Les rapports markdown (`generate_report`) sont retirés : ils font double emploi avec les enregistrements consultables. La page ne surface pas les logs (le `cron.log` n'apportait rien) ; une consultation des logs par phase, si elle est mise en place, sera un mécanisme distinct.

**Présentation en ruban de phases.** La page liste les runs en ordre anté-chronologique. Chaque run porte son verdict global, sa date, sa durée et un **ruban** : les phases dans l'ordre du graphe (gauche → droite), en cases de largeur fixe dont la **couleur** porte le statut. Le ruban n'est pas proportionnel au temps — les durées de phase sont trop hétérogènes (secondes à heures) pour un axe-temps lisible. Le graphe de dépendances ne sert qu'à ordonner les phases et à marquer l'éventail post-`normalize` d'un séparateur ; aucune arête n'est dessinée. Le drill-down sur une phase affiche les volumes d'entrée/sortie (avant / après), les métriques, la durée et son médian historique, et les signaux.

```
● 142   25/06 14:30   full · 5 sources    18 min 04s   ✓
   ext  cro  rfs  rft  nrm │ aff  pbj  mdc  pub  rel  per  aut  cty  sub  oa
    ✓    ✓    ✓    ✓    ✓  │  ✓    ✓    ✓    ✓    ✓    ⚠    ✓    ✓    ✓   ✓
```

Légende des cases : vert = ok, rouge = exception (run interrompu là), ambre = warning, gris = phase non jouée ce run-là.

### Modèle de dépendances des phases

Les dépendances input → output sont statiques et connues. La colonne vertébrale est `extract → resolve_ra → cross_imports → refresh_stale → refetch_truncated → normalize` (`cross_imports` dépend aussi de `resolve_ra` pour les agences d'enregistrement). En aval, `normalize` alimente `affiliations`, `metadata_correction` et `publishers_journals` (← `resolve_ra` également) ; `metadata_correction` alimente `publications` ; `publications` alimente `relations` (← normalize aussi), `subjects`, `oa_status` et `countries` (← affiliations aussi) ; `affiliations` alimente `persons` ; `publications` et `persons` alimentent `authorships`. Ce flux est documenté ici à titre informatif ; ce que le code déclare (`application/pipeline/graph.py`), phase par phase, ce sont ses tables consommées et produites — relevées au début et à la fin pour donner les volumes avant / après. Les liaisons amont ne sont pas matérialisées. L'ordre de déclaration est l'ordre d'exécution, qui ordonne le ruban. Ce qui varie d'un run à l'autre, c'est quelles phases tournent et quand, pas le flux.

### Existant : réutilisé, remplacé, retiré

- **Réutilisé tel quel** : le sweep `subprocess → import` et le dataclass `application/pipeline/metrics.py:PhaseMetrics` (toutes les phases remontent des métriques typées à l'orchestrateur — socle de la capture par phase) ; l'harmonisation des logs d'extraction (new/updated, cadence, préfixe source, bilans).
- **Remplacé** : la table `pipeline_run_snapshots` et son payload par run, le hook gardé par run complet dans `run_pipeline.py`, les endpoints `pipeline-runs`, la page admin à onglets, les value objects `application/ports/pipeline/runs.py`. Les snapshots existants, par run complet, ne sont pas rétro-convertibles ; on repart d'une table propre. Ce retrait se fait en fin de chantier (Phase F), une fois la lecture migrée, pour ne pas casser la page admin entre-temps.
- **Retiré** : `generate_report` et les rapports markdown ; `statement_timeout` sur les connexions pipeline (plus un besoin) ; la visibilité dans les UPDATE longs (le pipeline a été optimisé, plus d'UPDATE durablement muet).

## Phasage

### Phase A — Modèle de données et graphe des phases

- [x] Graphe des phases en code (`application/pipeline/graph.py`) : pour chaque phase, ses tables consommées et produites (définition des observables d'entrée et de sortie), dans l'ordre d'exécution. Source de vérité unique, consommée par la capture et par l'interface.
- [x] Migration Alembic (`c4e9a1b7f2d8`) : création de la table des exécutions de phase (`run_id`, phase, `started_at`, `ended_at`, mode, sources, `status`, `signals jsonb`, `metrics jsonb`, `details jsonb`) + séquence `pipeline_run_id_seq` + index par phase, par `run_id`, par date. La table a d'abord porté `input`/`output`, consolidés en une colonne libre `details` par la migration `d7f2a4c9e1b6`. Le drop de `pipeline_run_snapshots` est reporté en Phase F.
- [x] Value objects de payload (`application/ports/pipeline/phase_executions.py`) : métriques, signaux, statut, `details` (indicateurs sur-mesure) ; sérialisation JSON.

### Phase B — Capture par phase dans `run_pipeline.py`

- [x] `run_id` (séquence) généré au lancement ; chaque phase relève les volumes avant/après de ses tables (`details["tables"]`) et persiste métriques, statut, signaux et indicateurs sur-mesure (`infrastructure/observability/phase_executions.py`). Statut `error` sur exception, `warning` sur interruption utilisateur (action contrôlée) ou si la phase remonte des signaux. Capture best-effort : une défaillance d'observabilité (migration non appliquée, etc.) est loggée sans interrompre le run. Fonctionne pour `--only` et `--from`. L'orchestrateur fait dériver son ordre d'exécution de `PHASE_ORDER` (graphe), supprimant la duplication de l'ordre.
- [x] Indicateurs sur-mesure : `PhaseMetrics` gagne `details` et `signals`. `details` ne porte que des **données neutres** (clés techniques, chiffres, valeurs métier comme les noms de Registration Agency ou les statuts OA) ; les **libellés et la mise en forme** vivent dans une config par phase côté frontend (`interfaces/frontend/src/routes/admin/pipeline/phase-views.ts`), donc modifiables sans relancer le pipeline (rétroactifs sur les anciens runs). Conventions de `details` : `summary` (dict clé → nombre), `table` (lignes à `key` métier + champs numériques, rendues en colonnes configurables avec % / signe / durée / ligne TOTAL), `tables` (avant/après, posé automatiquement). Le « par source » passe par la convention `table` (colonnes propres à chaque phase). `extract` remonte une table par source (trouvés / nouveaux / màj / inchangés / durée) et `normalize` de même (traités / ignorés / erreurs / durée) ; `resolve_ra` une table par Registration Agency (DOI et préfixes distincts, préfixes ajoutés par le run ; la part `unknown` inclut les préfixes malformés `doi:`) ; `oa_status` une synthèse (backlog stale, vérifiées, ventilation) et une table par statut OA avec le delta du run ; `metadata_correction` une synthèse (SP examinées/corrigées par sous-étape unaire et cluster) et une ventilation des corrections par règle (le mapping de vocabulaire `DOC_TYPE_MAP` n'y compte pas, ce n'est pas une correction) ; `publications` une synthèse de réconciliation (SP traitées, publications créées dont par scission, existantes conservées, doublons fusionnés) en tête du facteur de dédup global (source_publications in-périmètre / publications).
- [x] Récapitulatif par phase (durées) en fin d'invocation, en plus du résumé par phase existant ; pas d'email.

### Phase C — Lecture : écart de durée

- [x] Calcul à la lecture de l'écart de durée au médian historique de la même phase (`application/observability/read.py`). Disponible côté lecture ; non surfacé dans l'UI pour l'instant (cf. Phase E). Pas de ratio de rendement (peu comparable d'une phase à l'autre) : les volumes avant / après et les métriques suffisent.
- [x] Tests unit sur le médian et l'écart de durée (sans base).

### Phase D — API

- [x] Endpoints de lecture (`/api/admin/pipeline/runs`, `/api/admin/pipeline/runs/{run_id}`) : liste des runs (agrégation par `run_id`, statut global) ; détail d'un run = ses exécutions de phase, chacune portant métriques, `details` (avant / après + indicateurs par source), durée, médian historique et écart, signaux (recalculés à la lecture). Le détail d'une exécution de phase est embarqué dans le détail du run, pas d'endpoint séparé.
- [x] Port typé (`application/ports/api/pipeline_phase_executions_queries.py`) et adapter queries (`infrastructure/queries/api/pipeline_phase_executions.py`).

### Phase E — Interface en ruban

- [x] Refonte de `/admin/pipeline` : liste anté-chronologique de runs (chaque run portant son ruban), ruban de phases coloré par statut (vert/ambre/rouge, gris pour les phases non jouées), drill-down par phase au rendu sur-mesure (table par source quand la phase fournit `by_source`, avant/après des tables sinon, plus métriques, durée vs médian, signaux). Onglets et composant monolithique supprimés ; découpage en `PhaseRibbon`, `RunList`, `RunDetail` + helpers. L'ordre des phases du ruban vient d'un endpoint `/api/admin/pipeline/phases` (graphe) ; les statuts par phase sont portés par la liste des runs.
- [x] Drill-down : durée totale + durée par élément (secondes/élément). La comparaison au médian historique (calculée côté lecture) n'est pas surfacée pour l'instant — peu pertinente quand les durées sont courtes ; à réintroduire si besoin.
- [x] Statut live (run en cours) reconduit. La page ne surface pas les logs (le `cron.log` était toujours vide) ; une consultation des logs par phase, si elle est mise en place, sera un mécanisme distinct.

## Travaux restants (réordonnés)

Phases A à E livrées (capture par phase, lecture, API, interface en ruban). Le reste s'ordonne en quatre étapes.

### 1. Clôture — retrait de l'ancien système (par run)

- [x] Suppression du système par run : writer `infrastructure/observability/pipeline_runs.py` (build / persist / render snapshot), queries `infrastructure/queries/api/pipeline_runs.py` et port `application/ports/api/pipeline_runs_queries.py`, value objects `application/ports/pipeline/runs.py`, router `interfaces/api/routers/admin/pipeline_runs.py` et son wiring (`app.py`, `deps.py`), tests associés.
- [x] `generate_report` et les rapports markdown retirés — tout `infrastructure/observability/pipeline_report.py` part (la capture de logs par phase ne servait qu'au rapport, format offset-fichier inadapté à une consultation par phase). Hook snapshot run-complet et machinerie de rapport retirés de `run_pipeline.py` (le récapitulatif des durées par phase en fin de run reste).
- [x] Migration de drop de la table `pipeline_run_snapshots` (`4477146f78cf` ; la séquence `pipeline_run_id_seq` reste : la table des exécutions de phase s'en sert). À appliquer sur dev/prod, puis régénérer `infrastructure/db/schema.sql`.
- [x] Régénération de `schema.ts` après retrait des endpoints (les `/api/admin/pipeline-runs` à tiret disparaissent ; l'UI utilise les `/api/admin/pipeline/runs` à slash).

### 2. Audit et harmonisation du logging

Revue phase par phase, dans l'ordre du pipeline. Helper transverse : `scoped_logger` (base class `SourceExtractor`) → préfixe `[source · scope]`, ou `[source]` sans scope ; indispensable quand les sources tournent en parallèle.

- [x] `extract` : préfixe `[source · scope]` mutualisé sur toutes les lignes intermédiaires. En-têtes et progression alignés entre les 5 sources ; theses gagne son bilan par PPN.
- [x] `resolve_ra` : déjà sain (début/fin, ligne par préfixe, mono-source) ; allégé du préfixe redondant et de l'indentation.
- [x] `cross_imports` : fetch DOI parallèle scopé `[source]` (`run_async`, partagé avec `refresh_stale`) — les deux lignes sans source réglées ; sous-étapes hal-id/NNT et DOI déjà annoncées (`▶`) ; `fetch_missing_hal_id` déjà bien logué. Logs 429/erreurs vérifiés : la source est préfixée via le circuit-breaker (helpers retry sync et async).
- [ ] `refresh_stale` (le fetch DOI hérite du scope de `run_async` ; reste le marquage des disparues sans DOI).
- [ ] `refetch_truncated`.
- [ ] `normalize` (+ annonce du VACUUM en fin de phase — silence actuel).
- [ ] Phases aval (`affiliations`, `publications`, `persons`…) : audit de complétude.

### 3. Métriques et signaux

- [ ] Indicateurs sur-mesure des phases restantes, du plus simple au plus complexe (cross_imports / refresh_stale par source…).
- [ ] Émission des signaux dans les phases : le canal est en place (remontés via `PhaseMetrics.signals`, affichés en ambre) ; reste à détecter et remonter `extract` (source indisponible, série de 429) et `persons` (`CannotAttributeConflict`).

### 4. Peaufinage UI

- [ ] Pagination de la liste des runs.
- [ ] Liens vers les logs par phase — mécanisme distinct de l'ancienne capture couplée au rapport, à concevoir.

## Questions ouvertes

- **Observables pertinents par phase** : la liste exacte (volumes et distributions) par phase se précise en codant le graphe (Phase A). Les familles actuelles (volumes, orphelins, distributions, qualité matching) restent un point de départ.
- **`CannotAttributeConflict` comme signal** : pendant `persons`, un identifiant d'une authorship rattachée à P déjà porté par Q (en pending ou confirmed) est un indice fort que P et Q sont la même personne. Aujourd'hui en warning perdu ; à capturer comme signal de la phase `persons`.
- **Page admin et observabilité DSI** : si la DSI met en place sa propre stack (logs centralisés, Grafana) à la transmission, la page admin peut devenir secondaire — le JSON en base reste exploitable par tout outil externe.
