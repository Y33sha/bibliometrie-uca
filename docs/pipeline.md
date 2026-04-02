# Pipeline de traitement — Bibliométrie UCA

Le pipeline transforme les données brutes des 3 sources bibliographiques (HAL,
OpenAlex, Web of Science) en un référentiel dédupliqué de publications, personnes
et authorships.

## Vue d'ensemble

```
Sources externes          Staging (brut)           Source (normalisé)         Vérité
────────────────         ──────────────           ──────────────────         ──────

API HAL ──────────→ staging_hal ──────→ hal_documents ─────────────┐
                                        hal_authors                │
                                        hal_authorships            ├──→ publications
                                                                   │
API OpenAlex ─────→ staging_openalex ─→ openalex_documents ────────┤    persons
                                        openalex_authors           │    person_name_forms
                                        openalex_authorships       ├──→ person_identifiers
                                                                   │
API/fichiers WoS ─→ staging_wos ──────→ wos_documents ────────────┤    authorships
                                        wos_authors                │
                                        wos_authorships ───────────┘
```

## Exécution

```bash
# Pipeline complet
python run_pipeline.py

# Reprise à partir d'une phase
python run_pipeline.py --from persons

# Une seule phase
python run_pipeline.py --only authorships

# Dry-run (affiche le plan sans exécuter)
python run_pipeline.py --dry-run

# Mode hebdomadaire (incrémental, 6 derniers mois)
python run_pipeline.py --mode weekly
```

**Modes :**
- `full` : pipeline complet avec cross-imports et enrichissements
- `monthly` : pipeline complet sans enrichissements
- `weekly` : incrémental (6 derniers mois, pas de cross-imports)


## Phases détaillées

### Phase 1 — `extract` : Moissonnage

Récupère les données brutes depuis les API et les stocke en JSONB.

| Source | Script | Table cible |
|--------|--------|-------------|
| HAL | `extraction/hal/extract_hal.py` | `staging_hal` |
| OpenAlex | `extraction/openalex/extract_openalex.py` | `staging_openalex` |
| WoS | `extraction/wos/extract_wos.py` | `staging_wos` |

Paramètre `--mode weekly` : ne moissonne que les 6 derniers mois.


### Phase 2 — `normalize` : Normalisation

Transforme les données brutes (staging) en tables structurées par source.

| Script | Entrée | Sorties |
|--------|--------|---------|
| `processing/normalize_hal.py` | `staging_hal` | `hal_documents`, `hal_authors`, `hal_authorships`, `hal_structures` |
| `processing/normalize_openalex.py` | `staging_openalex` | `openalex_documents`, `openalex_authors`, `openalex_authorships`, `openalex_institutions` |
| `processing/normalize_wos.py` | `staging_wos` | `wos_documents`, `wos_authors`, `wos_authorships` |

Chaque authorship source reçoit une colonne `author_name_normalized` calculée
par la fonction SQL `normalize_name_form()`.


### Phase 3 — `merge_pubs` : Fusion inter-sources

Déduplique les publications entre les sources et effectue les cross-imports.

1. **`merge_hal_openalex_pubs.py`** — fusionne HAL ↔ OpenAlex par DOI et liens explicites
2. **`fetch_missing_hal.py`** — cherche dans HAL les publications trouvées dans OpenAlex
3. **`cross_import_openalex.py`** — cherche dans OpenAlex les publications trouvées dans HAL
4. Re-normalisation des nouveaux records importés

Résultat : chaque publication canonique a un `publication_id` unique dans la table
`publications`, et les documents sources pointent vers elle.


### Phase 4 — `addresses` : Adresses et affiliations

Extrait les adresses brutes des authorships sources et les résout en structures.

1. **`populate_addresses.py`** — extrait les adresses brutes (OpenAlex, WoS)
2. **`resolve_addresses.py`** — matche les adresses avec les formes de nom des structures

Les structures détectées sont écrites dans `address_structures`.


### Phase 5 — `uca_flags` : Flags UCA

Calcule `is_uca` et `structure_ids` sur les authorships sources en croisant :
- les structures HAL (`hal_authorships.hal_struct_ids` → mapping `hal_structures.structure_id`)
- les structures résolues depuis les adresses
- le périmètre UCA (restreint pour `is_uca`, élargi pour `structure_ids`)

Script : `db/populate_uca_flags.sql` (étapes 1 à 3b).


### Phase 6 — `persons` : Création de personnes

Identifie et crée les personnes à partir des authorships sources.

1. **`create_persons_from_source_authorships.py`** — 6 passes de matching progressif :
   - Passe 1 : par ORCID confirmé
   - Passe 2 : par idHAL
   - Passe 3 : par ORCID non confirmé
   - Passe 4 : par nom exact (forme de nom → personne unique)
   - Passe 5 : par nom compatible (initiales, variantes)
   - Passe 6 : création de nouvelles personnes pour les authorships restantes

2. **`populate_person_name_forms.py`** — recalcule les formes de nom depuis toutes
   les sources (personnes, HAL, OpenAlex, WoS). Pour chaque personne, génère les
   variantes : "prénom nom", "nom prénom", "initiales nom", "nom initiales".


### Phase 7 — `authorships` : Construction des authorships vérité

**`build_authorships.py`** construit la table `authorships` en 4 étapes :

1. **Insertion** des paires (publication_id, person_id) manquantes, depuis les
   authorships sources non exclues
2. **FK** : rattache chaque authorship vérité à ses authorships sources
   (`hal_authorship_id`, `openalex_authorship_id`, `wos_authorship_id`)
3. **Métadonnées** : propage `author_position` et `is_corresponding`
4. **UCA** : propage `is_uca` et `structure_ids` depuis les 3 sources (union)

Les authorships sources marquées `excluded = TRUE` sont ignorées à toutes les étapes.


### Phase 8 — `countries` : Pays des publications

`refresh_publication_countries.sql` recalcule les pays de chaque publication à
partir des affiliations résolues.


### Phase 9 — `enrich` : Enrichissements optionnels

Exécutée uniquement en mode `full` :
- Données Unpaywall (accès ouvert, APC)
- Moissonnage ORCID
- Résolution IdRef

## Dépendances entre phases

```
extract → normalize → merge_pubs → addresses → uca_flags → persons → authorships → countries
                                                                                  ↘ enrich
```

Chaque phase dépend de la précédente. Il est possible de relancer une phase
individuelle avec `--only`, à condition que ses prérequis soient à jour.

**Règle critique** : `uca_flags` doit précéder `persons`, qui doit précéder
`authorships`. Inverser cet ordre produit des données incohérentes.
