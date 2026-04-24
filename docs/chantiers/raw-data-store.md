# Stockage des données brutes (raw store)

## Objectif

Conserver les payloads JSON bruts renvoyés par les APIs sources (HAL, OpenAlex, WoS, theses.fr…) dans un store externe à la BDD, pour :

1. Pouvoir **re-normaliser** sans re-moissonner (bug de parsing découvert après coup, nouveau champ à extraire).
2. Garder un **témoin auditable** de ce que chaque source a renvoyé à un instant T.
3. **Alléger la BDD** : supprimer le stockage des `source_authorships` hors périmètre une fois le raw en place (item ligne 6 du TODO).

## Principe architectural

Deux rôles distincts, pas une duplication :

- **BDD** = données actives, normalisées, indexables, source de vérité métier.
- **Raw store** = snapshot write-once, rarement lu, pour debug / reproduction / re-extraction.

Abstraction côté code via un Protocol `RawStore` avec deux implémentations :
- `LocalFileRawStore` — pour dev local (dossier hors projet, cf. phase 2).
- `B2RawStore` — production, API S3-compatible de Backblaze B2 via `boto3`.

Sélection par variable d'env (`BIBLIO_RAW_STORE_URL` = `file:///...` ou `s3://bucket/prefix`).

## Décisions à prendre en amont

Avant d'écrire du code, trancher :

1. **Convention de clé** : `{source}/{source_id}.json.gz` proposé. À valider : est-ce que `source_id` est toujours disponible et unique au moment du fetch ?
2. **Politique de mise à jour** : quand on re-fetch une publi (hash différent), on **écrase** ou on **versionne** (`{source}/{source_id}/{fetched_at}.json.gz`) ? Recommandation : écraser au début, on verra si le besoin de versionnage apparaît.
3. **Granularité** : un objet par publi (proposé) ou des batchs ? Un objet par publi est plus simple, plus granulaire, pas de souci de taille.
4. **Ce qu'on stocke** : strictement le payload fournisseur, sans métadonnées locales ajoutées. Les métadonnées (date de fetch, version de schéma) vont en *object metadata* S3, pas dans le JSON.

## Phases

### Phase 0 — Décisions (cf. section ci-dessus)
Durée : discussion, pas de code.

### Phase 1 — Audit de pureté de la normalisation

**Prérequis pour que la re-normalisation soit fiable.**

Scanner le code des phases de normalisation pour identifier les dépendances non-pures :
- `datetime.now()`, `date.today()` utilisés pour dériver des valeurs stockées (≠ pour logger).
- Dépendances à l'état de la BDD au moment du run (ex : "regarder ce qui existe déjà pour décider quoi insérer").
- Génération d'IDs non-déterministes.

Sortie : une note listant ce qui est pur, ce qui ne l'est pas, et ce qui doit être fixé avant que la re-normalisation soit faisable.

### Phase 2 — Abstraction `RawStore`

Créer `infrastructure/raw_store/`  :
- `base.py` — Protocol `RawStore` avec `put(source, source_id, payload) -> None`, `get(source, source_id) -> bytes`, `exists(source, source_id) -> bool`, `iter_keys(source) -> Iterator[str]`.
- `local.py` — `LocalFileRawStore(root_dir)`.
- `b2.py` — `B2RawStore(bucket, prefix, endpoint_url, credentials)` via `boto3`.
- `factory.py` — construit l'impl selon `BIBLIO_RAW_STORE_URL`.

Ajouter la config dans `infrastructure/settings.py`.

Tests : store en mémoire (`InMemoryRawStore`) ou tmpdir, pas besoin de taper Backblaze en CI.

### Phase 3 — Setup Backblaze B2

- Créer un bucket dédié `bibliometrie-uca-raw` (privé).
- Créer une clé applicative scopée à ce seul bucket (pas la master key).
- Stocker credentials dans `.env` (pas dans git).
- Documenter le setup dans un court `roadmaps/raw-data-store-setup.md` ou dans le README.
- Tester manuellement que `B2RawStore` écrit et relit.

### Phase 4 — Intégration dans le pipeline

Au moment du moissonnage (dans `infrastructure/sources/` pour chaque source), après fetch et avant normalisation :

```python
raw_store.put(source="hal", source_id=publi_hal_id, payload=gzip(json_bytes))
```

Décider : on met l'appel dans l'extracteur lui-même, ou dans une phase pipeline dédiée qui wrappe l'extracteur ? Probablement dans l'extracteur, au plus près de la donnée fraîchement reçue.

Idempotence : re-fetcher une publi écrase l'objet raw (cohérent avec la décision phase 0).

### Phase 5 — Script de re-normalisation

CLI dédié : `interfaces/cli/renormalize_from_raw.py`.

```
python -m interfaces.cli.renormalize_from_raw --source hal [--publication-id ...] [--dry-run]
```

Lit le raw store, ré-exécute la normalisation pour chaque objet, écrit en BDD (en respectant la même logique que le pipeline normal). Utile pour les cas d'usage 1 et 2 (bug fix / nouveau champ).

### Phase 6 — Suppression du stockage des `source_authorships` hors périmètre

**Payoff du chantier.**

- Vérifier qu'on peut reconstruire à la demande les `source_authorships` d'une publi hors périmètre à partir du raw (script ad-hoc ou extension du script de re-normalisation).
- Migration SQL : supprimer les lignes hors périmètre de `*_authorships` (HAL, OA, WoS).
- Ajuster le pipeline pour ne plus les insérer dans ce cas.
- Documenter comment re-matérialiser ces données si le besoin surgit.

### Phase 7 — Documentation de transmission DSI

- Section dans le README / dans un doc d'archi : rôle du raw store, schéma de clé, convention de mise à jour.
- Variables d'env à renseigner en prod.
- Note sur la politique de rétention (à définir avec la DSI — a priori pas de suppression).

## Hors scope

- Pas de versionnage multi-dates des objets raw (on écrase).
- Pas de chiffrement côté client (données publiques).
- Pas de réplication / backup dédié : Backblaze gère la durabilité, on ne met pas de stratégie de backup du raw store par-dessus.
- Pas d'interface d'exploration du raw store — accès en ligne de commande uniquement.

## Estimation grossière

- Phases 0-1 (décisions + audit) : 1 demi-journée.
- Phases 2-3 (abstraction + setup B2) : 1 journée.
- Phase 4 (intégration pipeline) : 1 journée.
- Phase 5 (re-normalisation) : 1 journée.
- Phase 6 (suppression source_authorships hors périmètre) : 1 demi-journée.
- Phase 7 (doc) : 1 demi-journée.

**Total : ~4-5 journées** réparties, sans urgence.

## Dépendances / ordre

Phases 0 → 1 → 2 → (3 en parallèle de 2) → 4 → 5 → 6 → 7.

Phase 1 peut se faire en parallèle de 0 (audit, pas bloquant pour les décisions).
