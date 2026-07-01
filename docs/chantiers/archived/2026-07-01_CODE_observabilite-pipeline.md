# Chantier — Observabilité du pipeline

Commencé le 2026-05-16 - Terminé le 2026-07-01

## Contexte

Le pipeline se lance rarement d'un bloc : extraction sur une plage d'années custom, `cross_imports` interrompu s'il est trop long, reprise en `--from normalize`. L'observabilité doit suivre cet usage. Le système en place ne produit un instantané que pour un **run complet** (gardé par `not args.only and not args.from_phase` dans `run_pipeline.py`), agrégeant l'état global de la base et les métriques de toutes les phases dans un seul payload `pipeline_run_snapshots`. Les runs partiels — le cas courant — ne produisent rien. La page admin associée (onglets Snapshots / Rapports, composant monolithique) est inadaptée à cet usage.

Besoin primaire : **savoir d'un coup d'œil si un run s'est bien passé**, phase par phase, y compris pour un run partiel ou automatisé — vert quand il n'y a rien à regarder, rouge quand une phase échoue sur exception, ambre quand quelque chose est à signaler (interruption contrôlée par l'utilisateur, source indisponible, arrêt après une série de 429). Avoir aussi une idée du temps pris et repérer une phase anormalement lente. Besoin secondaire : suivre l'évolution des volumes dans la durée.

## Décisions

### Modèle de données

**Unité de persistance = une exécution de phase**, pas un run. Chaque fois qu'une phase tourne (même seule), un enregistrement : phase, `run_id`, `started_at`/`ended_at`, mode, sources, `status` (ok / error / warning), signaux structurés, métriques (`PhaseMetrics`) et indicateurs sur-mesure de la phase (`details`, capturés à la fin). Aucune condition « run complet ».

**Pas de table de runs.** Un `run_id` (entier de séquence, généré au lancement) est une colonne de la table des exécutions de phase. Tout ce qui est « par run » est dérivable par agrégation (`début = min`, `fin = max`, mode et sources communs, statut global = le pire des statuts de phase) ; une table parente ne répèterait que du dérivable.

**Statut et motif.** `status = error` est décidé par l'orchestrateur lorsqu'une phase remonte une exception. Une interruption par l'utilisateur est un `status = warning` (action contrôlée — écourter un import n'est pas un échec), pas une erreur. Un `status = warning` est aussi **remonté par la phase elle-même** quand elle finit dégradée : un circuit-breaker source qui coupe après une série de 429/5xx attache un signal (le motif) à sa valeur de retour, là où l'événement ne partait qu'en log. La couleur du point porte l'alerte (ambre) ; le motif l'explicite en vue détaillée, sans colonne dédiée. Un fait de fonctionnement normal (une authorship dont l'identifiant est déjà porté par une autre personne, prévention de contamination pendant `persons`) n'est pas un motif : rien à signaler.

### Indicateurs sur-mesure par phase : affichés, non jugés

Le rendu du drill-down est **sur-mesure par phase** : chaque phase choisit les indicateurs qui la décrivent et les remonte dans un `details` libre via son `PhaseMetrics` ; l'interface les affiche selon leur forme, sans rien dériver ni juger. Aucun mécanisme uniforme imposé à toutes les phases — une phase ne montre que ce qui l'éclaire, pas un relevé systématique de toutes ses tables. Les entrées/sorties sont surfacées quand elles parlent (le total de la table de vérité pour `authorships`, les sujets ajoutés et le total du référentiel pour `subjects`), tues quand elles n'apprennent rien (un volume de liens, une table enrichie en place sans delta). On ne dérive **pas** de ratio de rendement : un tel ratio (sortie / entrée) n'est pas comparable d'une phase à l'autre — facteur de dédup pour `publications`, quasi-1 pour les enrichissements en place — et serait plus trompeur qu'utile. Ce qui parle, ce sont les compteurs `PhaseMetrics` (new / updated…), les indicateurs propres de chaque phase et l'écart de durée. Les phases multi-sources (`extract`…) présentent une table par source (trouvés / nouveaux / màj / inchangés / durée) ; les conventions d'affichage (`summary`, `table`, `lines`, `matrix`) et leurs libellés vivent côté interface, modifiables sans relancer le pipeline.

**Aucune détection automatique de dérive.** Le drill-down affiche la durée totale d'une phase et sa durée rapportée au volume traité (secondes par élément). La comparaison au médian historique est calculée à la lecture mais **pas surfacée pour l'instant** (peu pertinente quand les durées sont courtes ; à réintroduire si le besoin se confirme), sans seuil ni drapeau dans tous les cas. Poser un critère objectif de dérive sur un corpus de quelques milliers de publications, aux runs hétérogènes (daily mono-source vs full multi-sources), produirait surtout du bruit.

### Une seule surface : l'interface graphique

La page `/admin/pipeline` est l'unique surface d'observabilité. Les rapports markdown (`generate_report`) sont retirés : ils font double emploi avec les enregistrements consultables. La page ne surface pas les logs (le `cron.log` n'apportait rien) ; une consultation des logs par phase, si elle est mise en place, sera un mécanisme distinct.

**Présentation en ruban de phases.** La page liste les runs en ordre anté-chronologique. Chaque run porte son verdict global, sa date, sa durée et un **ruban** : les phases dans l'ordre du graphe (gauche → droite), en cases de largeur fixe dont la **couleur** porte le statut. Le ruban n'est pas proportionnel au temps — les durées de phase sont trop hétérogènes (secondes à heures) pour un axe-temps lisible. L'ordre des phases ne sert qu'à ordonner les cases et à marquer l'éventail post-`normalize` d'un séparateur ; aucune arête n'est dessinée. Le drill-down sur une phase affiche ses indicateurs sur-mesure, ses métriques, la durée et son médian historique, et les signaux.

```
● 142   25/06 14:30   full · 5 sources    18 min 04s   ✓
   ext  cro  rfs  rft  nrm │ aff  pbj  mdc  pub  rel  per  aut  cty  sub  oa
    ✓    ✓    ✓    ✓    ✓  │  ✓    ✓    ✓    ✓    ✓    ⚠    ✓    ✓    ✓   ✓
```

Légende des cases : vert = ok, rouge = exception (run interrompu là), ambre = warning, gris = phase non jouée ce run-là.

### Ordre des phases

`application/pipeline/graph.py` déclare l'ordre d'exécution du pipeline (`PHASE_ORDER`), source de vérité unique consommée par l'orchestrateur et par la trame du ruban. Il ne porte que l'ordre : ni dépendances matérialisées, ni tables consommées/produites. Le flux logique (`extract → resolve_ra → cross_imports → refresh_stale → refetch_truncated → normalize`, puis l'éventail aval à partir de `normalize` : `affiliations`, `metadata_correction`, `publishers_journals`, `publications`, `relations`, `persons`, `authorships`, `countries`, `subjects`, `oa_status`) est décrit dans `/docs/pipeline/`. Ce qui varie d'un run à l'autre, c'est quelles phases tournent et quand, pas l'ordre.

### Existant : réutilisé, remplacé, retiré

- **Réutilisé tel quel** : le sweep `subprocess → import` et le dataclass `application/pipeline/metrics.py:PhaseMetrics` (toutes les phases remontent des métriques typées à l'orchestrateur — fondation de la capture par phase) ; l'harmonisation des logs d'extraction (new/updated, cadence, préfixe source, bilans).
- **Remplacé** : la table `pipeline_run_snapshots` et son payload par run, le hook gardé par run complet dans `run_pipeline.py`, les endpoints `pipeline-runs`, la page admin à onglets, les value objects `application/ports/pipeline/runs.py`. Les snapshots existants, par run complet, ne sont pas rétro-convertibles ; on repart d'une table propre. Ce retrait se fait en fin de chantier (Phase F), une fois la lecture migrée, pour ne pas casser la page admin entre-temps.
- **Retiré** : `generate_report` et les rapports markdown ; `statement_timeout` sur les connexions pipeline (plus un besoin) ; la visibilité dans les UPDATE longs (le pipeline a été optimisé, plus d'UPDATE durablement muet) ; le relevé **automatique** des volumes avant / après de toutes les tables consommées/produites par une phase (`details["tables"]`, `watched_tables`, `snapshot_volumes`, déclarations `consumes`/`produces` du graphe). Ce baseline uniforme était plus bruyant qu'utile (lignes parasites, noms de tables bruts, redondance avec les compteurs) : chaque phase remonte à la place les seuls indicateurs qui l'éclairent, et `application/pipeline/graph.py` se réduit à l'ordre des phases.

## Phasage

### Phase A — Modèle de données et graphe des phases

- [x] Ordre des phases en code (`application/pipeline/graph.py`) : `PHASE_ORDER`, source de vérité unique de l'ordre d'exécution, consommée par l'orchestrateur et par la trame du ruban.
- [x] Migration Alembic (`c4e9a1b7f2d8`) : création de la table des exécutions de phase (`run_id`, phase, `started_at`, `ended_at`, mode, sources, `status`, `signals jsonb`, `metrics jsonb`, `details jsonb`) + séquence `pipeline_run_id_seq` + index par phase, par `run_id`, par date. La table a d'abord porté `input`/`output`, consolidés en une colonne libre `details` par la migration `d7f2a4c9e1b6`. Le drop de `pipeline_run_snapshots` est reporté en Phase F.
- [x] Value objects de payload (`application/ports/pipeline/phase_executions.py`) : métriques, signaux, statut, `details` (indicateurs sur-mesure) ; sérialisation JSON.

### Phase B — Capture par phase dans `run_pipeline.py`

- [x] `run_id` (séquence) généré au lancement ; chaque phase persiste ses métriques, statut, signaux et indicateurs sur-mesure (`infrastructure/observability/phase_executions.py`). Statut `error` sur exception, `warning` sur interruption utilisateur (action contrôlée) ou si la phase remonte des signaux. Capture best-effort : une défaillance d'observabilité (migration non appliquée, etc.) est loggée sans interrompre le run. Fonctionne pour `--only` et `--from`. L'orchestrateur fait dériver son ordre d'exécution de `PHASE_ORDER` (graphe), supprimant la duplication de l'ordre.
- [x] Indicateurs sur-mesure : `PhaseMetrics` gagne `details` et `signals`. `details` ne porte que des **données neutres** (clés techniques, chiffres, valeurs métier comme les noms de Registration Agency ou les statuts OA) ; les **libellés et la mise en forme** vivent dans une config par phase côté frontend (`interfaces/frontend/src/routes/admin/pipeline/phase-views.ts`), donc modifiables sans relancer le pipeline (rétroactifs sur les anciens runs). Conventions de `details` : `summary` (dict clé → nombre), `table` (lignes à `key` métier + champs numériques, rendues en colonnes configurables avec % / signe / durée / ligne TOTAL), `lines` (lignes de texte à templates `{clé}`), `matrix` (croisé lignes × colonnes). Le « par source » passe par la convention `table` (colonnes propres à chaque phase). `extract` remonte une table par source (trouvés / nouveaux / màj / inchangés / durée) et `normalize` de même (traités / ignorés / erreurs / durée) ; `resolve_ra` une table par Registration Agency (DOI et préfixes distincts, préfixes ajoutés par le run ; la part `unknown` inclut les préfixes malformés `doi:`) ; `oa_status` une synthèse (backlog stale, vérifiées, ventilation) et une table par statut OA avec le delta du run ; `metadata_correction` une synthèse (SP examinées/corrigées par sous-étape unaire et cluster) et une ventilation des corrections par règle (le mapping de vocabulaire `DOC_TYPE_MAP` n'y compte pas, ce n'est pas une correction) ; `publications` une synthèse de réconciliation (SP traitées, publications créées dont par scission, existantes conservées, doublons fusionnés) en tête du facteur de dédup global (source_publications in-périmètre / publications).
- [x] Récapitulatif par phase (durées) en fin d'invocation, en plus du résumé par phase existant ; pas d'email.

### Phase C — Lecture : écart de durée

- [x] Calcul à la lecture de l'écart de durée au médian historique de la même phase (`application/observability/read.py`). Disponible côté lecture ; non surfacé dans l'UI pour l'instant (cf. Phase E). Pas de ratio de rendement (peu comparable d'une phase à l'autre) : les indicateurs sur-mesure et les métriques suffisent.
- [x] Tests unit sur le médian et l'écart de durée (sans base).

### Phase D — API

- [x] Endpoints de lecture (`/api/admin/pipeline/runs`, `/api/admin/pipeline/runs/{run_id}`) : liste des runs (agrégation par `run_id`, statut global) ; détail d'un run = ses exécutions de phase, chacune portant métriques, `details` (indicateurs sur-mesure de la phase), durée, médian historique et écart, signaux (recalculés à la lecture). Le détail d'une exécution de phase est embarqué dans le détail du run, pas d'endpoint séparé.
- [x] Port typé (`application/ports/api/pipeline_phase_executions_queries.py`) et adapter queries (`infrastructure/queries/api/pipeline_phase_executions.py`).

### Phase E — Interface en ruban

- [x] Refonte de `/admin/pipeline` : liste anté-chronologique de runs (chaque run portant son ruban), ruban de phases coloré par statut (vert/ambre/rouge, gris pour les phases non jouées), drill-down par phase au rendu sur-mesure (résumé, table par source, lignes ou matrice selon la phase ; compteurs `PhaseMetrics` génériques à défaut ; plus durée vs médian et signaux). Onglets et composant monolithique supprimés ; découpage en `PhaseRibbon`, `RunList`, `RunDetail` + helpers. L'ordre des phases du ruban vient d'un endpoint `/api/admin/pipeline/phases` (graphe) ; les statuts par phase sont portés par la liste des runs.
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
- [x] `refresh_stale` : fetch DOI séquentiel par source (annoncé, scopé via `run_async`) ; le marquage des rows stale sans DOI est désormais annoncé avant l'UPDATE et logué même à 0 (plus de silence).
- [x] `refetch_truncated`.
- [x] `normalize` : VACUUM déjà annoncé au début, gagne son log de fin (timing, `▶`/`✓`) ; les normaliseurs (séquentiels, enveloppés `▶`/`✓`) nomment la source dans « rien à traiter » et « Normalisation X terminée ». `summary_stats()` inexploité → renvoyé à l'étape 3 (métriques).
- [x] Phases aval (`affiliations`, `publishers_journals`, `metadata_correction`, `publications`, `relations`, `persons`, `authorships`, `countries`, `subjects`, `oa_status`) : déjà exemplaires — chaque sous-étape est enveloppée `▶ X` / `✓ X terminé en Xs` (timing), mono-canal, sans trou ni enjeu source-dépendant. Aucun changement.

### 3. Métriques et signaux

- [x] Correction de fond : `PhaseMetrics.total` était un compteur saisi à la main, désynchronisé (OpenAlex et WoS catégorisaient sans l'incrémenter → `total < new+updated+unchanged` affiché). `total` devient une **propriété dérivée** `max(seen, new+updated+unchanged)` — toujours ≥ la ventilation, impossible à re-désynchroniser ; `seen` (dénominateur explicite : interrogés/vus) alimenté par `add(total=…)`.
- [x] Indicateurs sur-mesure par phase : chaque phase remonte les siens, ou retombe sur les compteurs `PhaseMetrics` génériques (`refetch_truncated`…).
  - [x] `affiliations` : résumé adresses (total traitées + dans le périmètre), remonté depuis `resolve_addresses` (jusque-là jeté). Tableau par source réduit à `total / in_perimeter / %` (colonne `with_structs` retirée de bout en bout). Label de log « UCA » (hardcodé) corrigé en `in_perimeter` ; `uca_count` renommé. Colonne `percent` ajoutée au rendu du ruban.
  - [x] `publishers_journals` : remontait seul `resolve_publishers` (OpenAlex et DOAJ jetés). Tableau à une ligne par sous-étape (`préfixes DOI → publishers` : traités / matchés / créés ; `revues OpenAlex` : à typer / typées) ; DOAJ en ligne de résumé à part. OpenAlex passe de `-> None` à un retour `PhaseMetrics`. Config `phase-views` ajoutée (il n'y en avait pas → rendu par défaut flou).
  - [x] `publications` : résumé reformulé en **lignes de texte** (nouveau mode de rendu `lines` à templates `{clé}`, plus lisible que les couples libellé/valeur) : SP examinées → publications d'arrivée (dont existantes), nouvelles dont scissions, doublons fusionnés, nouveau total global. Chiffres du run (`ReconcileStats`) au lieu du global mal cadré ; facteur de dédup retiré ; le résumé porte le nouveau total.
  - [x] `relations` : tableau de distribution par `relation_type` (`count_by_relation_type` ajouté au port relations).
  - [x] `persons` : ventilation par méthode de rattachement (table à clés techniques `orcid` / `hal_person_id` / `idref` / `cross_source` / `single_name`, ordonnée par fiabilité décroissante de la cascade, avec % et ligne TOTAL) et résumé (créées, ignorées pour nom ambigu, rejets par corroboration de nom). La ventilation calculée par `create_persons` remonte en `PhaseMetrics` au lieu de rester en log. `TableView` gagne `rowLabels` pour des intitulés lisibles côté frontend tout en gardant des clés neutres en base.
  - [x] `authorships` : résumé de la table de vérité — créées, orphelines supprimées, et total dans le périmètre (compté par la phase, `count_authorships_in_perimeter`, jusque-là seulement loggé). Les compteurs internes de convergence (liens posés, attributs recomposés) restent hors affichage.
  - [x] `countries` : résumé en entonnoir (mode `lines`) — total d'adresses, manque initial (sans pays, nombre et %), pays rattachés par le run, reste à résoudre dont la part portant une suggestion.
  - [x] `subjects` : la phase compte son référentiel avant/après (`count_subjects`) → sujets ajoutés (évolution nette : ingestion moins purge des orphelins), nouveau total du vocabulaire, et publications réingérées (mode `lines`). Le nombre de liens publication↔sujet, sans intérêt, n'est pas surfacé.
- [x] Statut dégradé remonté par la phase : un trip de circuit-breaker source (série de 429/5xx) attache un signal `warning` à `PhaseMetrics` (`_signal_if_tripped`) → point ambre et motif au drill-down, câblé aux cinq points de fetch (`extract`, `resolve_ra`, `publishers_journals`, `cross_imports`, `refresh_stale`). La colonne « Signaux » du tableau, redondante avec la couleur du point, est retirée ; le motif s'affiche sous « Motif » en vue détaillée. `CannotAttributeConflict` écarté (fonctionnement normal, rien à signaler).

### 4. Peaufinage UI

- [x] Pagination de la liste des runs : chargement incrémental (50 runs, bouton « charger les plus anciens » via `offset`, masqué en fin d'historique) ; colonne liste sticky à hauteur du viewport, défilement interne pendant que le détail défile avec la page.
- [x] Statut pipeline en cours dynamique : le bandeau interroge `logs/status.json` en poll adaptatif (1 s tant qu'un run tourne — phase courante et avancement `phases_done`/`phases_total` à la seconde ; 10 s à l'arrêt). À la transition fin de run (fin naturelle, exception ou interruption — `status.json` nettoyé, statut vu `null`), la liste des runs et le détail sélectionné sont rechargés, le ruban fraîchement enregistré apparaissant sans rechargement de page.
- [x] Log par phase au drill-down : un bouton « log » à droite de chaque ligne de phase déroule le log de la phase (au lieu de ses métriques). Le log est découpé à la lecture de `logs/pipeline.log` sur les marqueurs `Run pipeline #<id>` / `PHASE : <nom>` / `PIPELINE TERMINÉ` (`infrastructure/observability/phase_logs.py`), sans capture dédiée ni stockage en base ; endpoint `/api/admin/pipeline/runs/{run_id}/phases/{phase}/log`. Disponible quand `LOG_TO_FILE=true` ; sinon la vue signale le log indisponible. Le détail multi-source d'`extract` vit dans les fichiers par source (`hal.log`…), hors de ce périmètre. Les endpoints morts hérités des rapports markdown (`/reports`, `/reports/{filename}`, `/logs` sur `cron.log`) et leurs modèles sont retirés au passage.

## Questions ouvertes

- **Indicateurs pertinents par phase** : le choix exact par phase est le cœur du chantier (section 3), affiné phase par phase à partir des cas réels. Pas de mécanisme uniforme : chaque phase ne surface que ce qui l'éclaire (compteurs, distributions, totaux de ses tables quand ils parlent).
- **Page admin et observabilité DSI** : si la DSI met en place sa propre stack (logs centralisés, Grafana) à la transmission, la page admin peut devenir secondaire — le JSON en base reste exploitable par tout outil externe.
