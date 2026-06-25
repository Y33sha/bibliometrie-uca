# Chantier — Observabilité du pipeline

Commencé le 2026-05-16.

## Contexte

Le pipeline se lance rarement d'un bloc : extraction sur une plage d'années custom, `cross_imports` interrompu s'il est trop long, reprise en `--from normalize`. L'observabilité doit suivre cet usage. Le système en place ne produit un instantané que pour un **run complet** (gardé par `not args.only and not args.from_phase` dans `run_pipeline.py`), agrégeant l'état global de la base et les métriques de toutes les phases dans un seul payload `pipeline_run_snapshots`. Les runs partiels — le cas courant — ne produisent rien. La page admin associée (onglets Snapshots / Rapports, composant monolithique) est inadaptée à cet usage.

Besoin primaire : **savoir d'un coup d'œil si un run s'est bien passé**, phase par phase, y compris pour un run partiel ou automatisé — vert quand il n'y a rien à regarder, rouge quand une phase est interrompue par une exception, ambre quand une anomalie est signalée (source indisponible, arrêt après une série de 429, conflits d'identité). Avoir aussi une idée du temps pris et repérer une phase anormalement lente. Besoin secondaire : suivre l'évolution des volumes et des rendements dans la durée.

## Décisions

### Modèle de données

**Unité de persistance = une exécution de phase**, pas un run. Chaque fois qu'une phase tourne (même seule), un enregistrement : phase, `run_id`, `started_at`/`ended_at`, mode, sources, `status` (ok / error / warning), signaux structurés, observable d'entrée (capturé au début de la phase), observable de sortie et métriques (`PhaseMetrics`, capturés à la fin). Aucune condition « run complet ».

**Pas de table de runs.** Un `run_id` (entier de séquence, généré au lancement) est une colonne de la table des exécutions de phase. Tout ce qui est « par run » est dérivable par agrégation (`début = min`, `fin = max`, mode et sources communs, statut global = le pire des statuts de phase) ; une table parente ne répèterait que du dérivable.

**Statut et signaux.** `status = error` est décidé par l'orchestrateur lorsqu'une phase remonte une exception. `status = warning` et les signaux (source indisponible, arrêt après une série de 429, `CannotAttributeConflict` pendant `persons`…) sont **remontés par la phase elle-même** : ils enrichissent sa valeur de retour, là où ils ne partent aujourd'hui qu'en log et sont perdus. C'est la part de plumbing la plus lourde du chantier, concentrée dans `extract` et `persons`.

### Rendement : métrique locale, affichée et non jugée

**Le rendement d'une phase = sa sortie rapportée à son entrée**, toutes deux mesurées sur la phase elle-même : l'entrée est l'observable capturé à son début, la sortie l'observable capturé à sa fin. Pas de lignage inféré entre phases — une phase connaît ce qu'elle consomme et ce qu'elle produit. Le rendement est invariant à l'échelle : doubler les années extraites double les volumes aval sans changer le rendement, donc pas de faux signal sur un simple changement de périmètre. Une dérive du rendement (une phase qui sort soudain moitié moins par unité d'entrée) reste, elle, visible.

**Aucune détection automatique de dérive.** Le rendement et la durée d'une phase sont **affichés** à côté de leur médian historique pour la même phase ; l'œil juge. Une phase anormalement lente est mise en évidence visuellement, l'écart au médian étant calculé à la lecture, sans seuil stocké ni drapeau. Poser un critère objectif de dérive sur un corpus de quelques milliers de publications, aux runs hétérogènes (daily mono-source vs full multi-sources), produirait surtout du bruit.

### Une seule surface : l'interface graphique

La page `/admin/pipeline` est l'unique surface d'observabilité. Les rapports markdown (`generate_report`) sont retirés : ils font double emploi avec les enregistrements consultables. Les logs restent accessibles en lien secondaire par run.

**Présentation en ruban de phases.** La page liste les runs en ordre anté-chronologique. Chaque run porte son verdict global, sa date, sa durée et un **ruban** : les phases dans l'ordre du graphe (gauche → droite), en cases de largeur fixe dont la **couleur** porte le statut. Le ruban n'est pas proportionnel au temps — les durées de phase sont trop hétérogènes (secondes à heures) pour un axe-temps lisible. Le graphe de dépendances ne sert qu'à ordonner les phases et à marquer l'éventail post-`normalize` d'un séparateur ; aucune arête n'est dessinée. Le drill-down sur une phase affiche entrée, sortie, métriques, rendement et durée (chacun avec son médian historique) et les signaux.

```
● 142   25/06 14:30   full · 5 sources    18 min 04s   ✓
   ext  cro  rfs  rft  nrm │ aff  pbj  mdc  pub  rel  per  aut  cty  sub  oa
    ✓    ✓    ✓    ✓    ✓  │  ✓    ✓    ✓    ✓    ✓    ⚠    ✓    ✓    ✓   ✓
```

Légende des cases : vert = ok, rouge = exception (run interrompu là), ambre = warning, gris = phase non jouée ce run-là.

### Modèle de dépendances des phases

Les dépendances input → output sont statiques et connues. La colonne vertébrale est `extract → resolve_ra → cross_imports → refresh_stale → refetch_truncated → normalize` (`cross_imports` dépend aussi de `resolve_ra` pour les agences d'enregistrement). En aval, `normalize` alimente `affiliations`, `metadata_correction` et `publishers_journals` (← `resolve_ra` également) ; `metadata_correction` alimente `publications` ; `publications` alimente `relations` (← normalize aussi), `subjects`, `oa_status` et `countries` (← affiliations aussi) ; `affiliations` alimente `persons` ; `publications` et `persons` alimentent `authorships`. Ce flux est documenté ici à titre informatif ; ce que le code déclare (`application/pipeline/graph.py`), phase par phase, ce sont ses tables consommées et produites — la définition de ses observables d'entrée et de sortie. Les liaisons amont ne sont pas matérialisées : le rendement se mesure localement sur chaque phase, sans lignage inféré. L'ordre de déclaration est l'ordre d'exécution, qui ordonne le ruban. Ce qui varie d'un run à l'autre, c'est quelles phases tournent et quand, pas le flux.

### Existant : réutilisé, remplacé, retiré

- **Réutilisé tel quel** : le sweep `subprocess → import` et le dataclass `application/pipeline/metrics.py:PhaseMetrics` (toutes les phases remontent des métriques typées à l'orchestrateur — socle de la capture par phase) ; l'harmonisation des logs d'extraction (new/updated, cadence, préfixe source, bilans).
- **Remplacé** : la table `pipeline_run_snapshots` et son payload par run, le hook gardé par run complet dans `run_pipeline.py`, les endpoints `pipeline-runs`, la page admin à onglets, les value objects `application/ports/pipeline/runs.py`. Les snapshots existants, par run complet, ne sont pas rétro-convertibles ; on repart d'une table propre. Ce retrait se fait en fin de chantier (Phase F), une fois la lecture migrée, pour ne pas casser la page admin entre-temps.
- **Retiré** : `generate_report` et les rapports markdown ; `statement_timeout` sur les connexions pipeline (plus un besoin) ; la visibilité dans les UPDATE longs (le pipeline a été optimisé, plus d'UPDATE durablement muet).

## Phasage

### Phase A — Modèle de données et graphe des phases

- [x] Graphe des phases en code (`application/pipeline/graph.py`) : pour chaque phase, ses tables consommées et produites (définition des observables d'entrée et de sortie), dans l'ordre d'exécution. Source de vérité unique, consommée par la capture et par l'interface.
- [x] Migration Alembic (`c4e9a1b7f2d8`) : création de la table des exécutions de phase (`run_id`, phase, `started_at`, `ended_at`, mode, sources, `status`, `signals jsonb`, `metrics jsonb`, `input jsonb`, `output jsonb`) + séquence `pipeline_run_id_seq` + index par phase, par `run_id`, par date. Le drop de `pipeline_run_snapshots` est reporté en Phase F.
- [x] Value objects de payload (`application/ports/pipeline/phase_executions.py`) : métriques, observables, signaux, statut ; sérialisation JSON.

### Phase B — Capture par phase dans `run_pipeline.py`

- [ ] `run_id` généré au lancement ; chaque phase capture son observable d'entrée à son début et persiste à sa fin observable de sortie, métriques, statut et signaux. Fonctionne pour `--only` et `--from`.
- [ ] Remontée structurée des signaux par les phases (source indisponible, série de 429, conflits d'identité), `extract` et `persons` en priorité.
- [ ] Résumé console par phase et récap de run en fin d'invocation ; pas d'email.

### Phase C — Lecture : rendement et durée

- [ ] Calcul à la lecture du rendement (sortie / entrée) et de l'écart de durée au médian historique de la même phase. Affichage seul, sans seuil ni drapeau.
- [ ] Tests unit sur le calcul du rendement et du médian (sans base).

### Phase D — API

- [ ] Endpoints de lecture : liste des runs (agrégation `GROUP BY run_id`, statut global), détail d'un run (ses phases), détail d'une exécution de phase (métriques, observables, rendement, durée et médians recalculés à la lecture, signaux).
- [ ] Ports typés et adapters queries.

### Phase E — Interface en ruban

- [ ] Refonte de `/admin/pipeline` : liste anté-chronologique de runs, ruban de phases coloré par statut, drill-down par phase. Suppression du système d'onglets et du composant monolithique ; découpage en sous-composants.
- [ ] Mise en évidence visuelle des phases anormalement lentes.
- [ ] Statut live (run en cours) reconduit dans la nouvelle structure ; lien vers les logs en consultation secondaire.

### Phase F — Clôture

- [ ] Retrait de l'ancien système : table `pipeline_run_snapshots` (migration de drop), value objects `application/ports/pipeline/runs.py`, hook gardé par run complet, anciens endpoints, queries et UI, `generate_report` et les rapports markdown.
- [ ] Toilettage final des logs si besoin (audit complétude et cohérence inter-phases) — point de clôture, non bloquant.

## Questions ouvertes

- **Observables pertinents par phase** : la liste exacte (volumes et distributions) par phase se précise en codant le graphe (Phase A). Les familles actuelles (volumes, orphelins, distributions, qualité matching) restent un point de départ.
- **`CannotAttributeConflict` comme signal** : pendant `persons`, un identifiant d'une authorship rattachée à P déjà porté par Q (en pending ou confirmed) est un indice fort que P et Q sont la même personne. Aujourd'hui en warning perdu ; à capturer comme signal de la phase `persons`.
- **Page admin et observabilité DSI** : si la DSI met en place sa propre stack (logs centralisés, Grafana) à la transmission, la page admin peut devenir secondaire — le JSON en base reste exploitable par tout outil externe.
