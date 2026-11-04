# Adaptateurs de source

## Contexte

Chaque source moissonnée (HAL, OpenAlex, WoS, ScanR, theses.fr, DataCite, Crossref) expose un adaptateur (`pipeline/ingestion/adapters.py`) : moissonneur, recherche par personne, recherche par DOI, relecture par identifiant natif, normaliseur. Une relecture du code relève :

- 13 classes `*StaleRefetch` et `*DoiSearch`, qui contiennent surtout deux constantes. `source_key` répète la source de l'adaptateur. `max_concurrent` est déclaré deux à trois fois par source, avec la même valeur.
- Trois recherches par identifiant recodent les combinateurs de `common/lookup.py` (`one_at_a_time`, `by_native_id`).
- Les `__init__.py` des sources contiennent des fabriques d'import différé, imposées par un cycle d'import entre `common/` et les sources. Les clients reçoivent l'URL de l'API au constructeur, toujours la même.
- `SourceHarvester` a un paramètre de type pour la configuration de la source : cinq `load_config` identiques, des dataclasses à un champ, un crochet `setup_logging` à implémentation unique.
- Le décodage d'une page et la fin de pagination sont écrits deux ou trois fois par source pour HAL, OpenAlex et ScanR. DataCite et Crossref ont deux types de page identiques.
- Le normaliseur appelle `minimal_metadata` avant `parse` : WoS et DataCite lisent le payload deux fois.
- ScanR et DataCite déclarent un `NotFound` jamais produit : les appelants le testent quand même.
- `StagingStore.stage` contient une branche propre à HAL pour effacer les échecs de recherche par identifiant natif.

## Décisions

- **Concurrence par source dans `api_params.py`**, à côté du débit (`MAX_PER_SECOND`), lue par la recherche par identifiant.
- **L'adaptateur expose des fonctions**, sans classe intermédiaire : relecture par identifiant natif, recherche par DOI avec sa taille de lot.
- **Une boucle de pagination commune**, sur un type de page unique. WoS et theses.fr gardent leur pagination par décalage.
- **Un document écrit dans `staging` efface l'échec de la recherche de son identifiant natif**, pour toute source qui attribue ses identifiants : hal-id pour HAL, NNT pour theses.fr.

## Phasage

### Phase 1 — Recherche par identifiant

- [ ] Table de concurrence par source dans `api_params.py` ; suppression des constantes recopiées.
- [ ] Relecture par identifiant natif et recherche par DOI exposées par l'adaptateur ; suppression des classes `*StaleRefetch` et `*DoiSearch`, de `source_key` et du test de concordance avec l'adaptateur.
- [ ] HAL, OpenAlex et Crossref passent par les combinateurs de `common/lookup.py`.
- [ ] Fonctions d'API de ScanR et DataCite typées sans `NotFound`.

### Phase 2 — Moissonneur

- [ ] `load_config` commun ; suppression du paramètre de type de configuration, des dataclasses de configuration et de `setup_logging`.
- [ ] Type de page unique et boucle de pagination commune à HAL, OpenAlex, ScanR, DataCite et Crossref.

### Phase 3 — Import des sources

- [ ] Cycle d'import entre `common/` et les sources supprimé ; suppression des fabriques d'import différé des `__init__.py`.
- [ ] Clients des sources sans URL ni identifiants au constructeur.

### Phase 4 — Normalisation et staging

- [ ] `parse` avant `minimal_metadata` ; une seule lecture du payload par ligne.
- [ ] Effacement des échecs de recherche par identifiant natif déclaré par l'adaptateur, sans branche par source dans `staging.py`.

### Phase 5 — Documentation

- [ ] Mise à jour de `docs/architecture/06-pipeline.md` et des pages du moissonnage dans `docs/pipeline/`.
