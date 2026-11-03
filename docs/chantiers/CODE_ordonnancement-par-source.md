# Ordonnancement par source et normalisation au fil de l'eau

## Contexte

Le pipeline exécute ses phases l'une après l'autre. Dans une phase d'acquisition, les sources s'exécutent en parallèle, et la phase attend la plus lente. La source la plus lente change d'une phase à l'autre : Crossref pour `harvest_by_person`, OpenAlex et theses.fr pour `fetch_stale`. La normalisation attend la fin de toute l'acquisition.

Mesures d'un run `full` de 36 minutes, sur une année :

- acquisition : 10 minutes ;
- file OpenAlex : 88 s de moissonnage, 160 s de relecture des documents non revus, 63 s de relecture des documents tronqués, plus sa part de `harvest_by_person` ;
- file Crossref : 4,7 minutes, presque toutes en `harvest_by_person` ;
- normalisation : 7 minutes, dont 6,5 de normalisation des documents moissonnés.

Les dépendances du graphe relient seulement les tâches d'acquisition d'une même source, par `staging`. Chaque tâche réseau déclare son API (`network`). `staging` sert de file d'attente : une ligne à l'empreinte modifiée repasse à `processed = FALSE`.

Constats :

- La normalisation vide `raw_data` sans vérifier que la ligne est inchangée depuis sa lecture. Une réécriture concurrente serait effacée.
- La normalisation traite aussi les documents marqués tronqués. Seul l'ordre des phases garantit leur complément avant la normalisation.
- Des rattachements de la normalisation dépendent des entités déjà présentes : monographie choisie par titre parmi les candidates, éditeur trouvé par forme de nom ou créé. L'ordre de normalisation des sources (`SOURCE_PRIORITY`) peut donc changer le résultat.

## Décisions

- **Orchestrateur maison.** Un ordonnanceur topologique (`graphlib`) et la contrainte « une tâche à la fois par API » suffisent.
- **Une file par API.** Une tâche démarre dès que ses dépendances sont satisfaites et que son API est libre.
- **Normalisation au fil de l'eau.** Elle consomme `staging` par lots, toutes sources confondues, pendant l'acquisition.
- **File de normalisation sur le modèle des files `*_queue`** (`infrastructure/db/queues.py`) : relevé des couples `(id, seq)` au début, suppression de ces seuls couples à la fin. Elle remplace `staging.processed`.
- `raw_data` se vide seulement si `raw_hash` égale l'empreinte lue.
- Un document tronqué entre dans la file une fois complété.
- **Normalisation indépendante de l'ordre.** Une entité garde la forme de sa création. Le rattachement des enregistrements sources suivants est juste quel que soit l'ordre. L'ordre d'autorité des sources vaut pour les métadonnées de publication.
- **Le journal s'adapte au pipeline.** Les barres d'avancement de chaque file restent en direct. Le bilan de chaque tâche s'écrit d'un bloc à sa fin.
- **Les phases d'acquisition restent des noms de groupes de tâches**, pour `--only`, `--from` et le journal. L'ordonnancement les ignore.

## Phasage

### Phase 1 — Mesures

- [x] Durée de chaque tâche enregistrée dans `pipeline_phase_executions.metrics` (`task_durations_s`).
- [ ] Durée des files par API sur plusieurs runs `full`, et part de la normalisation exécutable pendant l'acquisition.

### Phase 2 — Normalisation indépendante de l'ordre

- [ ] Inventaire des écritures au résultat dépendant de l'ordre : monographies, éditeurs, adresses, plateformes, sujets.
- [ ] Rattachement juste quel que soit l'ordre, pour chaque cas retenu.
- [ ] Test : deux ordres de normalisation des sources donnent les mêmes rattachements.

### Phase 3 — File de normalisation

- [ ] Table de file (migration), alimentée par toutes les écritures de `staging` : moissonnage, relectures, complément des documents tronqués, `rehydrate_staging_from_raw_store`.
- [ ] Documents tronqués exclus de la file jusqu'à leur complément.
- [ ] Vidage de `raw_data` conditionné à l'empreinte lue.
- [ ] Suppression de `staging.processed`, mise à jour du hook `renormalisation_guard`.
- [ ] Normalisation par lots, toutes sources confondues.

### Phase 4 — Ordonnancement par API

- [ ] Ordonnanceur topologique sur les dépendances du graphe, une tâche à la fois par API.
- [ ] Normalisation pendant l'acquisition. Suppression des documents disparus, des orphelins et `VACUUM` après la fin de l'acquisition.
- [ ] `--only` et `--from` sur les groupes de tâches.
- [ ] Enregistrement des exécutions de phases chevauchantes, page des runs comprise.

### Phase 5 — Journal

- [ ] Barres d'avancement par file, bilan de chaque tâche écrit à sa fin.

### Phase 6 — Documentation

- [ ] Mise à jour de `docs/pipeline/` et de la liste des phases du `CLAUDE.md`.

## Questions ouvertes

- `fetch_missing` lit des enregistrements sources en partie mis à jour par le run en cours. Un document est trouvé dès ce run ou au suivant, selon le moment d'exécution de chaque tâche.
- Effet de la normalisation concurrente sur la durée de l'acquisition : charge de la base, processeur.
- Une tâche est déclarée en deux moitiés reliées par son nom : lectures, écritures et API dans le graphe (`Task`), fonction et affichage dans sa phase (`TaskStep`).
