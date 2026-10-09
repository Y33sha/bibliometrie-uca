# Chantier — Collaborations entre structures

## Contexte

Une analyse de réseau des collaborations demande de rattacher chaque signature à ses structures, y compris hors du périmètre. La table `structures` contient seulement les structures du périmètre et leurs tutelles. La phase `affiliations` les reconnaît dans les adresses grâce à des formes de noms saisies à la main. Ce procédé est infaisable pour toutes les structures mondiales.

Les sources fournissent des identifiants d'institution par signature :

| Source | Champ | Identifiant |
|---|---|---|
| OpenAlex | `authorships[].institutions[]` | ROR |
| WoS | `organizations.organization` | `ror_id` |
| DataCite | `creators[].affiliation[].affiliationIdentifier` | souvent ROR |
| ScanR | `affiliations[].id` | ROR, RNSR ou SIREN |
| HAL | `structId` | identifiant HAL |

La normalisation garde seulement le texte de ces affiliations, dans `addresses`.

Dans le raw store OpenAlex, 588 institutions citées sur 5 872 380 sont sans ROR. Types : `education` 54 %, `facility` 32 %, `government` 9 %, `healthcare` 4 %. Les nœuds du réseau sont donc des établissements et des laboratoires.

Les relations parent/enfant du ROR coïncident avec `structure_tutelles` sur le périmètre, à quelques écarts près (dump ROR v2.14).

## Décisions

**Deux référentiels.** `structures` et `structure_tutelles` restent le référentiel interne : elles définissent le périmètre et servent à la phase `affiliations`. Une partie des tutelles concerne des structures internes absentes du ROR. Le ROR est un référentiel externe en lecture seule, chargé depuis le dump publié sur Zenodo. `structures.ror_id` relie les deux.

```
ror_organizations
  ror_id         PRIMARY KEY
  name
  country_code
  types          text[]
  status

ror_relations
  parent_ror_id  → ror_organizations
  child_ror_id   → ror_organizations
  PRIMARY KEY (parent_ror_id, child_ror_id)
```

**ROR des sources par signature.** La phase `normalize` remplit la table de liens `source_authorship_rors (source_authorship_id, ror_id)`. Ces liens entrent dans `content_hash`.

**Périmètre résolu par la phase `affiliations`.** Une vue matérialisée associe chaque signature consolidée à ses ROR, sur le modèle de `authorship_structures`. Dans le périmètre, ce sont les ROR des structures résolues par `affiliations`. Hors périmètre, ce sont les ROR des sources, moins ceux du périmètre.

**Cohérence des référentiels.** Un rapport compare `structure_tutelles` à `ror_relations` dans les deux sens, par clôture transitive. Un parent ROR est couvert s'il est un ancêtre dans `structure_tutelles`. Une tutelle est couverte si son parent est un ancêtre dans le ROR. Chaque écart se corrige dans `structure_tutelles` ou se signale au ROR.

## Phasage

### 1. Référentiel ROR

- [x] Migration : tables `ror_organizations` et `ror_relations`.
- [x] Script de chargement du dump ROR : `interfaces/cli/imports/import_ror_dump.py`.
- [x] Rapport de cohérence entre `structure_tutelles` et `ror_relations` : `interfaces/cli/maintenance/report_ror_coherence.py`.
- [ ] Écarts actuels reportés dans `structures` et `structure_tutelles`.

### 2. ROR des sources

- [ ] Migration : table `source_authorship_rors`.
- [ ] Normalisation OpenAlex, WoS, DataCite et ScanR : écriture des ROR par signature.
- [ ] Mesure de la couverture par source.

### 3. Vue consolidée

- [ ] Vue matérialisée des ROR par signature consolidée, rafraîchie par le pipeline.
- [ ] Tests : ROR du périmètre exclus des ROR des sources ; ROR des structures résolues par `affiliations` inclus.

### 4. Mise à jour de la documentation

- [ ] `docs/` : référentiel ROR, table de liens, vue consolidée.

## Questions ouvertes

- Agrégation des nœuds : ROR cités, ou établissements obtenus par `ror_relations`.
- Faux positifs des sources hors périmètre : accord de deux sources ; vérification par un service externe (ISTEX…) dans un chantier distinct.
- HAL : conversion des `structId` en ROR par le référentiel HAL.
- Exposition : API, interface, export.
