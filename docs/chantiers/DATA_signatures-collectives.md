# Chantier — Signatures collectives

## Contexte

Une liste d'auteurs contient parfois un collectif : « ATLAS Collaboration », « for the PREDISTIM working group », « The ESUB-MG Study Group ».

Chaque source les traite à sa façon :

- Crossref décrit un collectif par un champ `name`, sans `family` ni `given`. Le normaliseur Crossref l'écarte sans renuméroter : la notice a un trou de position.
- DataCite déclare certains créateurs `Organizational`. Le normaliseur les écarte. D'autres collectifs sont déclarés comme des personnes et restent.
- OpenAlex, ScanR, HAL et WoS les gardent comme des signatures ordinaires. OpenAlex ne les distingue pas des personnes.

Signatures dont le nom contient un mot de collectif (collaboration, consortium, study group, network…), au 2026-10-17 : OpenAlex 4 019, DataCite 2 076, ScanR 435, HAL 105, Crossref 53, WoS 48.

La phase `persons` en a fait des personnes : 25 personnes sont des collectifs (« ATLAS Collaboration » : 29 signatures, 24 lignes d'`authorships` ; « ALICE Collaboration », « LHCb collaboration », « The French Gut Consortium »…). Elles comptent dans les statistiques par auteur.

## Décisions

**La normalisation garde les collectifs.** Elle reproduit la liste de la source, à la position que la source donne.

**Colonne `source_authorships.collective`.** Elle vaut vrai pour une signature collective. La normalisation la pose d'après le signal explicite de la source quand il existe : Crossref, entrée à `name` seul ; DataCite, créateur `Organizational`. Sinon, une règle du domaine décide d'après le nom.

**Les traitements des personnes ignorent les signatures collectives.** La phase `persons` ne leur attribue aucune personne. La phase `authorships` ne les consolide pas. L'alignement des auteurs les écarte.

## Phasage

### 1. Schéma et règle

- [ ] Migration : colonne `source_authorships.collective`, booléen, faux par défaut.
- [ ] Règle du domaine qui reconnaît un collectif à son nom, testée sur les noms du stock.

### 2. Normalisation

- [ ] Crossref : les entrées à `name` seul deviennent des signatures collectives.
- [ ] DataCite : les créateurs `Organizational` deviennent des signatures collectives.
- [ ] Toutes les sources : le writer des signatures pose `collective` d'après le signal de la source, ou d'après la règle du nom.

### 3. Traitements en aval

- [ ] Phase `persons` : aucune personne pour une signature collective.
- [ ] Phase `authorships` : les signatures collectives ne sont pas consolidées.

### 4. Reprise du stock

- [ ] Signatures existantes marquées d'après la règle du nom.
- [ ] Notices Crossref et DataCite rejouées depuis le raw store (`rehydrate_staging_from_raw_store`), pour retrouver les collectifs écartés.
- [ ] Les 25 personnes collectives détachées de leurs signatures, puis purgées.

### 5. Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- **Précision de la règle du nom.** « Network », « Team » ou « Society » peuvent figurer dans un nom de personne ou d'entreprise. La revue des signatures marquées le dira.
