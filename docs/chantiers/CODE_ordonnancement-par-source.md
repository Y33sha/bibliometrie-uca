# Ordonnancement par source et normalisation au fil de l'eau

## Contexte

Le pipeline exécute ses phases l'une après l'autre. Dans une phase d'acquisition, les sources s'exécutent en parallèle, et la phase attend la plus lente. La source la plus lente change d'une phase à l'autre : ScanR pour `harvest`, Crossref pour `harvest_by_person`. La normalisation attend la fin de toute l'acquisition.

Durées médianes des runs `full` sur huit semaines :

- acquisition : 8,7 minutes ;
- `harvest` : ScanR 150 s, OpenAlex 89 s, HAL 68 s ;
- `harvest_by_person` : 4,2 minutes ;
- `fetch_missing` : une dizaine de secondes par source ;
- `fetch_stale` : quelques secondes, 2 à 3,5 minutes au 9e décile pour OpenAlex, Crossref et DataCite ;
- `fetch_truncated` (OpenAlex) : 1,3 minute ;
- normalisation : 4,7 minutes, 23 minutes au 9e décile.

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

- [x] Inventaire des écritures au résultat dépendant de l'ordre.
  - **Monographies : rattachement dépendant de l'ordre.** Un enregistrement source avec ISBN rejoint la seule monographie de son titre sans ISBN. Un enregistrement source sans ISBN reste sans monographie entre plusieurs volumes de son titre. Exemple, un titre à deux volumes d'ISBN I1 et I2, et un enregistrement source B sans ISBN. Ordre I1, I2, B : deux monographies, B sans monographie. Ordre B, I1, I2 : B et I1 dans la même monographie, I2 dans une autre. La fusion des monographies en double (`publishing`) laisse cet écart.
  - **Éditeurs : rattachement dépendant de l'ordre dans un cas.** Un éditeur trouvé par son identifiant OpenAlex reçoit la forme de nom de l'enregistrement source, si elle est libre. Un enregistrement source d'une autre source normalisé avant crée un éditeur distinct avec cette forme. La fusion des autres noms des éditeurs (`publishing`) en rattrape une partie.
  - **Rattachement indépendant de l'ordre**, seule la forme stockée varie : adresses (`raw_text` de la première), plateformes (nom et type de la dernière écriture), sujets (libellé et parent de la dernière écriture), informations du contributeur (clé sur tout le contenu), nom et identifiant OpenAlex d'un éditeur.
- [x] La normalisation écrit dans `biblio` l'éditeur et le volume décrits par la source : `publisher` (nom), `publisher_openalex_id`, `monograph` (titre, ISBN, eISBN, actes, année).
- [x] Oneshot `fill_biblio_publisher_and_monograph` : `publisher_openalex_id` et `monograph` du stock extraits du raw store, à défaut déduits des rattachements existants.
- [x] Exécution du oneshot sur la base.
- [x] Rattachement des éditeurs en lot (`publishing.attach_publishers`), après la résolution des préfixes DOI. Chaque identifiant OpenAlex rejoint son éditeur, à défaut celui d'une de ses formes de nom, à défaut un éditeur créé. Les enregistrements sources sans identifiant OpenAlex rejoignent l'éditeur de leur forme de nom. Chaque forme restée libre crée un éditeur. Une forme attribuée garde son éditeur. Normalisation sans recherche ni création d'éditeur.
- [x] Règle de l'éditeur nommé par DataCite appliquée dans `attach_publishers`, d'après le type de document d'avant correction et la série ou le volume décrits.
- [x] Rattachement des monographies en lot (`publishing.attach_monographs`), après la fusion des autres noms des éditeurs. Les enregistrements sources partageant un ISBN forment un volume. Un enregistrement source sans ISBN rejoint le seul volume à ISBN de son titre et d'éditeur compatible : un volume est compatible avec les éditeurs de ses enregistrements sources et de ses monographies existantes. Le volume du même éditeur passe avant celui sans éditeur. Sans volume à ISBN, les enregistrements sources sans ISBN forment un volume par titre et éditeur. Chaque volume reprend ses monographies existantes. Normalisation sans recherche ni création de monographie.
- [x] Fusion des monographies en double supprimée : après le rattachement en lot, elle ne trouve plus rien sur le stock.
- [x] Indépendance à l'ordre : la normalisation écrit seulement les lignes de sa source, et les tests du domaine vérifient chaque rattachement en lot dans tous les ordres.

### Phase 3 — File de normalisation

- [x] Migration : file `queues.staging_normalization_queue`, garnie des lignes à traiter ; suppression de `staging.processed` et de son index.
- [x] Application de la migration, snapshot du schéma.
- [x] Mise en file à chaque écriture de `staging` : document nouveau ou modifié et complet, complément des auteurs d'un document tronqué, levée de la marque de troncature, `rehydrate_staging_from_raw_store`.
- [x] Normalisation de chaque source d'après la file : relevé des couples `(id, seq)` au départ, suppression des couples de chaque lot validé. Une ligne en erreur reste en file.
- [x] Vidage de `raw_data` conditionné à l'empreinte lue.
- [x] Mise à jour du hook `renormalisation_guard`.

### Phase 4 — Ordonnancement par API

- [ ] Ordonnanceur topologique sur les dépendances du graphe, une tâche à la fois par API.
- [ ] Normalisation par lots, toutes sources confondues, pendant l'acquisition. Suppression des documents disparus, des orphelins et `VACUUM` après la fin de l'acquisition.
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
