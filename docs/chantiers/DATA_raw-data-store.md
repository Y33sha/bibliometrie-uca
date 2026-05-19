# Stockage des données brutes (raw store)

## Objectif

Conserver les payloads JSON bruts renvoyés par les APIs sources (HAL, OpenAlex, WoS, ScanR, theses.fr, Crossref) dans un store externe à la BDD, pour :

1. Pouvoir **re-normaliser** sans re-moissonner (bug de parsing découvert après coup, nouveau champ à extraire, changement de mapping).
2. Garder un **témoin auditable** de ce que chaque source a renvoyé à un instant T.
3. **Alléger la BDD** : à terme, supprimer le stockage des `source_authorships` hors périmètre et les re-matérialiser à la demande depuis le raw.

## Principe architectural

Deux rôles distincts, pas une duplication :

- **BDD** = données actives, normalisées, indexables, source de vérité métier.
- **Raw store** = snapshot write-once, rarement lu, pour debug / reproduction / re-extraction.

Abstraction côté code via un Protocol `RawStore` avec deux implémentations :

- `LocalFileRawStore` — pour dev local.
- `B2RawStore` — production, API S3-compatible de Backblaze B2 via `boto3`.

Sélection par variable d'env `BIBLIO_RAW_STORE_URL` (`file:///...` ou `s3://bucket/prefix`).

## Conventions

- **Clé** : `{source}/{source_id_url_encoded}.json.gz`. `source_id` est URL-encodé pour gérer les caractères filesystem-unsafe (`/` dans les IDs ScanR du type `doi10.1002/...`, `:` dans les IDs WoS du type `WOS:000...`).
- **Politique de mise à jour** : écraser. Pas de versionnage multi-dates.
- **Granularité** : un objet par publication (pas de batchs).
- **Contenu** : strictement le payload fournisseur, sans métadonnées locales ajoutées. Les métadonnées éventuelles (date de fetch, version de schéma) vont en *object metadata* côté S3, pas dans le JSON.

## Phases

### Phase 0 — Snapshot d'urgence des `raw_data` actuels

Sauvegarde locale du contenu de `staging.raw_data` issu d'un extract récent, avant que la normalisation ne vide ces colonnes.

- [x] Script `interfaces/cli/oneshot/dump_staging_raw_to_local.py` : lit les rows `staging` avec `processed = FALSE` (= raw_data plein) et écrit chaque payload dans `data/raw_store/{source}/{source_id_encoded}.json.gz`. Écrase si existant.
- [x] `data/raw_store/` ajouté à `.gitignore`.

### Phase 1 — Abstraction `RawStore` + implémentation locale

- [ ] `infrastructure/raw_store/base.py` — Protocol `RawStore` :
  - `put(source, source_id, payload_bytes) -> None`
  - `get(source, source_id) -> bytes`
  - `exists(source, source_id) -> bool`
  - `iter_keys(source) -> Iterator[str]`
- [ ] `infrastructure/raw_store/local.py` — `LocalFileRawStore(root_dir)`. URL-encoding des `source_id`, gzip à l'écriture, gunzip à la lecture.
- [ ] `infrastructure/raw_store/factory.py` — sélection par variable d'env. Au démarrage, seule l'impl locale (`file://`) est supportée ; `s3://` reste un placeholder.
- [ ] Config ajoutée dans `infrastructure/settings.py`.
- [ ] Tests unit avec `tmp_path` pytest.

### Phase 2 — Intégration dans les extracteurs

- [ ] Au point d'insert dans `staging` (dans chaque `infrastructure/sources/{source}/extract_*.py`), appel `raw_store.put(...)` en parallèle.
- [ ] Re-fetch : écrase l'objet raw existant, cohérent avec la convention de mise à jour.
- [ ] Validation : après un run de pipeline, comparer les hashs (`staging.raw_hash` vs hash du contenu raw store) sur un échantillon, pour confirmer la fidélité de l'écriture.

## Plus tard

- **Setup Backblaze B2.** Bucket dédié `bibliometrie-uca-raw` (privé), clé applicative scopée à ce seul bucket (pas la master key), credentials dans `.env`. Permet de basculer `BIBLIO_RAW_STORE_URL` du `file://` local vers `s3://` en prod sans toucher au code.

- **Script de re-normalisation** (`interfaces/cli/renormalize_from_raw.py`). Détail technique : lit le raw store et ré-exécute la même fonction de normalisation que le pipeline standard. Juste un changement de source d'entrée (JSON files au lieu de `staging.raw_data`), pas de logique métier nouvelle.

- **Suppression du stockage des `source_authorships` hors périmètre.** Payoff principal du chantier. Une fois le raw store éprouvé en prod, on peut supprimer les rows hors-périmètre de `source_authorships` (HAL, OA, WoS) et les re-matérialiser à la demande depuis le raw via le script de re-normalisation.

- **Documentation de transmission DSI.** Section dans le README ou doc d'archi : rôle du raw store, schéma de clé, convention de mise à jour, variables d'env, politique de rétention (a priori pas de suppression).

## Hors scope

- Pas de versionnage multi-dates des objets raw (on écrase).
- Pas de chiffrement côté client (données publiques).
- Pas de stratégie de backup dédiée au-dessus de B2 — Backblaze gère la durabilité, on n'ajoute pas une couche de redondance par-dessus.
- Pas d'interface d'exploration du raw store — accès en ligne de commande uniquement.
