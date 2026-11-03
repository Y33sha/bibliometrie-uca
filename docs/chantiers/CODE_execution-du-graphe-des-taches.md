# Exécution du graphe des tâches

## Contexte

L'orchestration du pipeline mêle deux modèles. Le graphe (`pipeline/graph.py`) décrit les tâches, leurs lectures et leurs écritures. Les phases exécutent leurs tâches elles-mêmes, une classe par phase, par `run_tasks`. D'où :

- Une tâche est déclarée deux fois, reliées par son nom : lectures, écritures et API dans le graphe (`Task`), fonction et affichage dans sa phase (`TaskStep`). `run_tasks` vérifie à l'exécution la concordance des deux.
- Une phase est déclarée à six endroits : `TASKS`, `PHASE_LABELS`, `EXTRA_PHASES`, `HARVESTING_PHASES`, `_PHASE_BUILDERS`, `_LABEL_FIELDS`. Trois vérifications au chargement les gardent cohérents.
- Chaque phase a sa classe et sa fonction `build()`, qui appellent `run_tasks` et injectent des fonctions à implémentation unique.
- Les lectures et écritures déclarées servent seulement à un test d'ordre ; l'ordre d'exécution est celui de la liste.

Durées médianes des runs `full` sur huit semaines :

- acquisition : 8,7 minutes ;
- `harvest` : ScanR 150 s, OpenAlex 89 s, HAL 68 s ;
- `harvest_by_person` : 4,2 minutes ;
- `fetch_missing` : une dizaine de secondes par source ;
- `fetch_stale` : quelques secondes, 2 à 3,5 minutes au 9e décile pour OpenAlex, Crossref et DataCite ;
- `fetch_truncated` (OpenAlex) : 1,3 minute ;
- normalisation : 4,7 minutes, 23 minutes au 9e décile.

Constats sur la normalisation :

- La normalisation vide `raw_data` sans vérifier que la ligne est inchangée depuis sa lecture. Une réécriture concurrente serait effacée.
- La normalisation traite aussi les documents marqués tronqués. Seul l'ordre des phases garantit leur complément avant la normalisation.
- Des rattachements de la normalisation dépendent des entités déjà présentes : monographie choisie par titre parmi les candidates, éditeur trouvé par forme de nom ou créé. L'ordre de normalisation des sources (`SOURCE_PRIORITY`) peut donc changer le résultat.

## Décisions

- **Une déclaration par tâche, dans le graphe.** Elle contient les lectures, les écritures, l'API, la fonction et l'affichage de la tâche.
- **L'orchestrateur exécute le graphe**, dans l'ordre de la liste des tâches. Les lectures et écritures déclarées vérifient cet ordre. Les classes de phase, leurs `build()` et la vérification de concordance disparaissent.
- **Une phase est un groupe de tâches**, déclaré une fois : nom, libellé, enrichissement ou non, bilan. Elle sert à `--only`, `--from`, au journal et à l'enregistrement des exécutions.
- **Orchestrateur maison.**
- **File de normalisation sur le modèle des files `*_queue`** (`infrastructure/db/queues.py`) : relevé des couples `(id, seq)` au début, suppression de ces seuls couples à la fin. Elle remplace `staging.processed`.
- `raw_data` se vide seulement si `raw_hash` égale l'empreinte lue.
- Un document tronqué entre dans la file une fois complété.
- **Normalisation indépendante de l'ordre.** Une entité garde la forme de sa création. Le rattachement des enregistrements sources suivants est juste quel que soit l'ordre. L'ordre d'autorité des sources vaut pour les métadonnées de publication.
- **Exécution simultanée par API reportée.** Gain mesuré sur l'acquisition : environ 90 s.

## Phasage

### Phase 1 — Mesures

- [x] Durée de chaque tâche enregistrée dans `pipeline_phase_executions.metrics` (`task_durations_s`).
- [x] Durée des files par API. Premier run `full` mesuré : acquisition de 500 s phase après phase ; file la plus longue DataCite, 411 s, dont 375 s de `harvest_by_person` ; Crossref 387 s, dont 381 s de `harvest_by_person` ; OpenAlex 166 s. Gain de l'exécution simultanée par API sur l'acquisition : environ 90 s. Normalisation des documents de ce run : 14 s.

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

### Phase 4 — Graphe exécuté par l'orchestrateur

- [ ] Conception : déclaration d'une tâche et d'une phase, points d'extension des phases (conditions, bilans), journal.
- [ ] Une déclaration par tâche, dans le graphe ; suppression de `TaskStep` et de la vérification de concordance.
- [ ] Une déclaration par phase : libellé, enrichissement, bilan ; suppression de `PHASE_LABELS`, `EXTRA_PHASES`, `HARVESTING_PHASES`, `_PHASE_BUILDERS`, `_LABEL_FIELDS`.
- [ ] Exécution du graphe par l'orchestrateur ; suppression des classes de phase et de leurs `build()`.
- [ ] `--only`, `--from` et enregistrement des exécutions par phase.

### Phase 5 — Documentation

- [ ] Mise à jour de `docs/pipeline/` et de la liste des phases du `CLAUDE.md`.
