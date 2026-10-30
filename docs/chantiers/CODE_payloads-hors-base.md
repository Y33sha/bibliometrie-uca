# Chantier — Payloads des sources hors de la base

## Contexte

Le payload d'un document transite par la base. Le moissonnage l'écrit dans `staging.raw_data` (JSONB). `normalize` le lit, puis `mark_done` vide `raw_data`. Avec `--raw-store`, `mark_done` archive d'abord le payload dans le raw store (`infrastructure/raw_store/`). Un `VACUUM` de `staging` suit la phase, `VACUUM FULL` en mode full.

Chaque payload est donc écrit dans la table et dans le WAL, puis effacé, puis récupéré par le `VACUUM`. `VACUUM FULL` verrouille `staging` en exclusivité pendant sa réécriture.

| Mesure locale du 30 octobre 2026 | Valeur |
|---|---|
| Lignes de `staging` | 347 750, dont 85 020 en attente avec leur payload |
| Taille de `staging` | 1 381 Mo, dont 76 Mo pour la table principale |
| Raw store | 314 941 fichiers, 2,2 Gio compressés |

En production, le service `pipeline` tourne sans `--raw-store`, avec une racine en lecture seule (`docker-compose.prod.yml`). Les payloads sont perdus après la normalisation. Rejouer la normalisation d'un document demande de vider son `raw_hash`, puis de le moissonner.

## Décisions

- **Le raw store reçoit le payload à l'écriture dans `staging`.** `StagingStore.upsert` est le point d'écriture unique : moissonnages, phases `fetch_*`, imports. Il écrit le payload au store si le contenu change, ou si le payload manque au store. L'écriture précède le commit. Son échec annule la transaction.
- **Une transaction annulée après l'écriture laisse au store un payload plus récent que `raw_hash`.** Le moissonnage suivant trouve une empreinte différente et remet le document en file.
- **`staging.raw_data` est supprimée.** `staging` garde l'empreinte, l'état de traitement, les marqueurs de disparition et de troncature, la provenance.
- **`normalize` lit les payloads au store.** `StagingRow.raw_data` reste, rempli depuis le store, donc les normaliseurs restent tels quels. Un payload manquant compte en erreur et laisse la ligne en file.
- **`complete_authors` écrit le payload complet au store** et remet la ligne en file, avec le même `raw_hash`.
- **Le raw store est obligatoire.** Suppression de l'option `--raw-store`, de `NullRawStore`, de l'archivage dans `mark_done`, du `VACUUM staging` et de la politique `vacuum_full`, propre à ce `VACUUM`.
- **Rejouer la normalisation d'une source, c'est remettre ses lignes en file** (`processed = FALSE`). Un script de maintenance le fait, à la place de `rehydrate_staging_from_raw_store`.
- **Le raw store est un répertoire local** (`BIBLIO_RAW_STORE_DIR`). En production, un volume nommé est monté en écriture sur le seul service `pipeline`. La racine du conteneur reste en lecture seule. La sauvegarde du volume accompagne celle de la base.
- **Le raw store de production se remplit au fil des lectures.** Un document moissonné ou relu par `fetch_stale` est écrit au store si son payload manque.
- **La migration reste en SQL pur.** Un script oneshot exporte au store les payloads en attente et vide leur `raw_data`. La migration échoue s'il reste une ligne en attente avec un payload, puis supprime la colonne.

## Phasage

### Phase 1 — Écriture au store à l'entrée

- [ ] `StagingStore.upsert` et `complete_authors` écrivent au store : contenu changé ou payload absent. Échec bloquant.
- [ ] Raw store en mémoire pour les tests. Adapter `tests/integration/helpers/staging.py`.

### Phase 2 — Lecture par `normalize`

- [ ] `fetch_pending_staging` et `fetch_staging_by_ids` remplissent `raw_data` depuis le store. Payload manquant : erreur, ligne en file.
- [ ] `mark_done` pose seulement `processed = TRUE`.

### Phase 3 — Retrait de `raw_data`

- [ ] Oneshot d'export des payloads en attente.
- [ ] Migration : contrôle des lignes en attente, suppression de la colonne, commentaire de la table. Snapshot `infrastructure/db/schema.sql`.
- [ ] Graphe : retrait de `staging.raw_data` et du `VACUUM staging`. Retrait de `vacuum_full` (`pipeline/runtime/modes.py`, `pipeline/task_runner.py`).
- [ ] Retrait de `--raw-store`, `NullRawStore`, `normalizer_builders(archive=…)`, du script `rehydrate_staging_from_raw_store` et de leurs tests.
- [ ] Script de remise en file des lignes d'une source.
- [ ] Scripts oneshot lecteurs de `staging.raw_data` : lecture au store.

### Phase 4 — Production et documentation

- [ ] Volume nommé du raw store dans `docker-compose.prod.yml`, `BIBLIO_RAW_STORE_DIR` du service `pipeline`.
- [ ] Documentation : `docs/exploitation/02-production.md` (volume, sauvegarde), `docs/exploitation/03-pipeline.md`, `docs/exploitation/01-developpement-local.md`, `docs/pipeline/03-normalize.md`, `docs/architecture/04-infrastructure.md`, `README.md`.
- [ ] Rappel du cycle dans `.claude/hooks/renormalisation_guard.py`.
- [ ] Mesure de `normalize` et de la taille de `staging` sur un run complet.

## Questions ouvertes

- Stockage objet : il dépend de ce que fournit la DSI. Une implémentation S3 se branche derrière le `Protocol` `RawStore`.
- `fetch_stale` relit seulement les années de la fenêtre du run. En production, les documents hors fenêtre restent sans payload au store. Faut-il un remplissage dédié ?
