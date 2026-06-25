# Chantier — Observabilité du pipeline

Commencé le 2026-05-16. Réorienté vers une observabilité **par phase**.

## Contexte

Le pipeline se lance rarement d'un bloc : extract sur une plage custom, cross_imports interrompu s'il est trop long, puis reprise en `--from normalize`. L'observabilité doit suivre cet usage — or le système livré ne produit un snapshot que pour un **run complet** (gardé par `not args.only and not args.from_phase`), agrégeant l'état global de la base et les métriques de toutes les phases dans un seul payload. Les runs partiels — le cas courant — ne produisent rien.

Deux besoins, donc :

1. **Des snapshots par phase**, consultables isolément, produits même quand une seule phase tourne.
2. **Une page admin lisible** : la page actuelle (onglets Snapshots / Rapports, composant monolithique) est désagréable et inadaptée à l'usage. On veut une **frise chronologique** : chaque run est un segment horizontal portant les phases qui ont tourné (parfois toutes, parfois une), avec drill-down par phase.

## Modèle

**Le pipeline est un DAG de phases.** Les dépendances input → output sont statiques et connues : `extract → cross_imports → refresh_stale → refetch_truncated → normalize`, puis `normalize` alimente `affiliations`, `publishers_journals`, `metadata_correction`, `publications` (← metadata_correction), `relations`, `persons`, `authorships` (← publications + persons), `countries`, `subjects`, `oa_status`. Ce qui varie d'un run à l'autre, c'est **quelles** phases tournent et **quand**, pas le graphe.

**Unité de persistance = une exécution de phase**, pas un run. Chaque fois qu'une phase tourne (même seule), un enregistrement : phase, `run_id`, début/fin, mode, sources, métriques (`PhaseMetrics`), et les **observables de sortie** (volumes/distributions des tables qu'elle produit). Plus de gating « run complet ».

**Pas de table `pipeline_runs`.** Un `run_id` (entier de séquence, généré au lancement) est une colonne de la table des exécutions de phase. Tout ce qui est « par run » est dérivable par agrégation (`début = min`, `fin = max`, mode/sources communs) ; une table parente ne répèterait que du dérivable.

**Lignage par inférence, pas matérialisé.** On ne stocke pas « ce normalize a consommé tel extract » : on l'infère à la lecture (dernière exécution amont avant le début de la phase, via le DAG codé). Suffisant pour un pipeline lancé séquentiellement ; pas de table d'arêtes de lignage.

**Détection d'anomalie par rendement, pas par volume absolu.** Comparer l'absolu d'une phase à son exécution précédente produit des faux positifs en cascade : doubler les années extraites double mécaniquement la production de toutes les phases aval, sans que rien soit cassé. On compare donc le **rendement** d'une phase = sa sortie rapportée à son entrée (les observables de sortie des phases amont via le DAG) :

- `extract` est le cas particulier — son entrée est externe (API + plage d'années). On compare l'absolu, et un écart est **noté comme « périmètre changé »** (un fait à afficher, origine légitime du surcroît aval), pas une anomalie.
- Les phases aval comparent leur **rendement** (ex. `normalize` : source_publications produites / staging consommé ≈ 1 ; `publications` : facteur de dédup publications / source_publications ; `persons` : persons / source_authorships). Le rendement est invariant à l'échelle : doubler l'entrée ne déclenche rien ; une **dérive du rendement** (normalize sort soudain moitié moins par ligne staging) déclenche.
- Comparaison vs la dernière exécution de la **même phase**. `mode` et `sources` restent des métadonnées de comparabilité secondaire (un normalize daily HAL-only n'a pas le même rendement qu'un full multi-sources), le rendement fait l'essentiel.

## État de l'existant

**Acquis, réutilisé tel quel :**
- Le sweep `subprocess → import` (ex-Phase 1) et le dataclass `application/pipeline/metrics.py:PhaseMetrics` : toutes les phases remontent des métriques typées à l'orchestrateur. C'est le socle de la capture par phase.
- L'harmonisation des logs d'extraction (new/updated, cadence, préfixe source, bilans) : livrée.

**Remplacé par le modèle par phase :**
- La table `pipeline_run_snapshots` (un blob par run complet), son payload `RunSnapshotPayload`, le hook gardé par run-complet dans `run_pipeline.py`, les endpoints `pipeline-runs`, et la page admin à onglets. Les snapshots existants sont par-run-complet, non rétro-convertibles ; on repart d'une table propre.

**Abandonné :**
- `statement_timeout` sur les connexions pipeline : plus un besoin.
- Visibilité dans les UPDATE longs : le pipeline a été optimisé entre-temps, plus d'UPDATE qui reste longtemps muet.

## Phasage

### Phase A — Modèle de données + DAG

- [ ] DAG des phases en code : pour chaque phase, ses phases amont et la définition de ses **observables de sortie** (les tables qu'elle produit) et de l'**observable d'entrée** servant au rendement. Source de vérité unique, consommée par la capture et par l'UI.
- [ ] Migration Alembic : suppression de `pipeline_run_snapshots` ; création de la table des exécutions de phase (`run_id`, phase, `started_at`, `ended_at`, mode, sources, `metrics jsonb`, `observables jsonb`) + index utiles (par phase, par `run_id`, par date).
- [ ] Value objects de payload (zone neutre `application/ports/pipeline/`) : métriques + observables par phase, sérialisation JSON.

### Phase B — Capture par phase dans `run_pipeline.py`

- [ ] `run_id` généré au lancement (séquence) ; chaque phase, à sa fin, persiste son exécution (métriques + observables de sortie). Fonctionne pour `--only` / `--from` (plus de gating run-complet).
- [ ] Résumé console par phase (et récap de run en fin d'invocation) ; pas d'email.

### Phase C — Détection d'anomalie par rendement

- [ ] Calcul du rendement d'une phase à la lecture : sortie / entrée (entrée résolue via le DAG = observables de sortie de la dernière exécution amont avant cette phase).
- [ ] Comparaison vs dernière exécution de la même phase ; drapeau « dérive » sur seuil de rendement. `extract` : comparaison absolue + libellé « périmètre changé ». Seuils hardcodés en v1.
- [ ] Tests unit sur la logique rendement + comparaison (sans BDD).

### Phase D — API

- [ ] Endpoints de lecture : liste des runs (agrégation `GROUP BY run_id`), détail d'un run (ses phases), détail d'une exécution de phase (métriques + observables + rendement + dérive recalculés à la lecture).
- [ ] Ports typés + adapters queries.

### Phase E — UI frise

- [ ] Refonte de `/admin/pipeline` en frise chronologique : runs en segments horizontaux, blocs de phases, drill-down par phase. Suppression du système d'onglets et du composant monolithique ; découpage en sous-composants.
- [ ] Le statut live (run en cours) et les rapports markdown : reconduits dans la nouvelle structure (à intégrer sans onglet clunky).

### Phase F — Clôture

- [ ] Retrait du code mort de l'ancien système (payload par-run, hook gardé, anciens endpoints/queries/UI).
- [ ] Toilettage final des logs si besoin (audit complétude/cohérence inter-phases) — point de clôture, non bloquant.

## Questions ouvertes

- **Observables pertinents par phase** : la liste exacte (volumes + distributions) par phase se précisera en implémentant le DAG (Phase A). Les familles actuelles (volumes, orphelins, distributions, qualité matching) restent valables comme point de départ.
- **Doublons probables via conflits d'identifiant** : pendant `persons`, un `CannotAttributeConflict` (un identifiant d'une authorship rattachée à P appartient déjà à Q en pending/confirmed) est un signal fort que P et Q sont la même personne. Aujourd'hui loggé en warning, l'info est perdue. À capturer comme observable de la phase `persons` (famille qualité matching) une fois le modèle par phase en place.
- **Page admin vs observabilité DSI** : si la DSI met en place sa propre stack (logs centralisés, Grafana) à la transmission, la page admin peut devenir secondaire — le JSON en base reste exploitable par tout outil externe. À reconsidérer à ce moment.
