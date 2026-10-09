# Chantier — Collaborations entre structures

## Contexte

Une analyse de réseau des collaborations demande de rattacher chaque signature à ses structures, y compris hors du périmètre. La table `structures` contient seulement les structures du périmètre et leurs tutelles. La phase `affiliations` les reconnaît dans les adresses grâce à des formes de noms saisies à la main. Ce procédé est infaisable pour toutes les structures mondiales.

Les sources fournissent des ROR par signature. Couverture mesurée dans le raw store, sur un échantillon de 3 000 enregistrements par source sauf OpenAlex et Crossref (raw store entier) :

| Source | Champ | Signatures avec ROR |
|---|---|---|
| OpenAlex | `authorships[].institutions[].ror` | 588 institutions sans ROR sur 5 872 380 |
| WoS | `address_spec.organizations.organization[].ror_id` | 98 % |
| Crossref | `author[].affiliation[].id` (`id-type` ROR) | 13 % |
| ScanR | `authors[].affiliations[].ror` | 21 % |
| HAL | `<idno type="ROR">` des structures du TEI (`label_xml`) | non mesuré |
| DataCite | `creators[].affiliation[].affiliationIdentifier` | 0 % : rendu par l'API avec le paramètre `affiliation=true` seulement |

La normalisation garde seulement le texte des affiliations, dans `addresses`.

Types des institutions OpenAlex : `education` 54 %, `facility` 32 %, `government` 9 %, `healthcare` 4 %. Les nœuds du réseau sont donc des établissements et des laboratoires.

Les relations parent/enfant du ROR coïncident avec `structure_tutelles` sur le périmètre, à quelques écarts près (dump ROR v2.14).

## Décisions

**Deux référentiels.** `structures` et `structure_tutelles` restent le référentiel interne : elles définissent le périmètre et servent à la phase `affiliations`. Une partie des tutelles concerne des structures internes absentes du ROR. Le ROR est un référentiel externe en lecture seule, chargé depuis le dump publié sur Zenodo. `structures.ror_id` relie les deux, avec une contrainte d'unicité.

```
ror_organizations
  ror_id         PRIMARY KEY
  name
  country_code
  types          ror_type[]
  status

ror_relations
  parent_ror_id  → ror_organizations
  child_ror_id   → ror_organizations
  PRIMARY KEY (parent_ror_id, child_ror_id)
```

**Rafraîchissement du référentiel par le pipeline.** En tête de la phase `affiliations`, le pipeline compare le nom de la dernière archive publiée sur Zenodo au nom de la dernière archive importée. Il télécharge et importe seulement une version plus récente. La table `ror_dump_imports (version, imported_at)` garde une ligne par import.

**ROR des sources par signature.** La phase `normalize` remplit la table de liens `source_authorship_rors (source_authorship_id, ror_id)`. Ces liens entrent dans `content_hash`. `ror_id` est sans clé étrangère vers `ror_organizations` : une source peut citer un ROR plus récent que le dump importé, et l'import remplace tout le référentiel.

Lecture par source :

- OpenAlex : ROR des institutions de la signature.
- WoS : ROR des organisations des adresses de l'auteur.
- Crossref : identifiants ROR des affiliations.
- ScanR : ROR de toutes les affiliations de l'auteur, tutelles comprises.
- HAL : ROR des structures du TEI auxquelles l'auteur est affilié.
- DataCite : `affiliationIdentifier` de schéma ROR. Les trois adaptateurs qui interrogent `/dois` (extraction, `fetch_missing`, `fetch_stale`) partagent le paramètre `affiliation=true`.

**Périmètre résolu par la phase `affiliations`.** Une vue matérialisée associe chaque signature consolidée à ses ROR, sur le modèle de `authorship_structures`. Dans le périmètre, ce sont les ROR des structures résolues par `affiliations`. Hors périmètre, ce sont les ROR des sources, moins ceux du périmètre.

**Cohérence des référentiels.** Un rapport compare `structure_tutelles` à `ror_relations` dans les deux sens, par clôture transitive. Un parent ROR est couvert s'il est un ancêtre dans `structure_tutelles`. Une tutelle est couverte si son parent est un ancêtre dans le ROR. Chaque écart se corrige dans `structure_tutelles` ou se signale au ROR.

## Phasage

### 1. Référentiel ROR

- [x] Migration : tables `ror_organizations` et `ror_relations`.
- [x] Script de chargement du dump ROR : `interfaces/cli/imports/import_ror_dump.py`.
- [x] Rapport de cohérence entre `structure_tutelles` et `ror_relations` : `interfaces/cli/maintenance/report_ror_coherence.py`.
- [x] Contrainte d'unicité sur `structures.ror_id`.
- [ ] Écarts actuels reportés dans `structures` et `structure_tutelles`.

### 2. ROR des sources

- [x] DataCite : paramètre `affiliation=true` partagé par les trois adaptateurs.
- [x] Migration : tables `source_authorship_rors` et `ror_dump_imports`.
- [x] Writer partagé : ROR des signatures, dans `content_hash`.
- [x] Normalisation OpenAlex, WoS, Crossref, ScanR, HAL et DataCite : lecture des ROR.
- [x] Rafraîchissement du référentiel ROR en tête de la phase `affiliations`.
- [ ] Reprise de l'existant : réextraction DataCite, réhydratation de `staging` depuis le raw store, `normalize` complet.
- [ ] Mesure de la couverture par source.

### 3. Vue consolidée

- [ ] Vue matérialisée des ROR par signature consolidée, rafraîchie par le pipeline.
- [ ] Tests : ROR du périmètre exclus des ROR des sources ; ROR des structures résolues par `affiliations` inclus.

### 4. Mise à jour de la documentation

- [ ] `docs/` : référentiel ROR, table de liens, vue consolidée.

## Questions ouvertes

- Agrégation des nœuds : ROR cités, ou établissements obtenus par `ror_relations`.
- Faux positifs des sources hors périmètre : accord de deux sources ; vérification par un service externe (ISTEX…) dans un chantier distinct.
- Exposition : API, interface, export.
