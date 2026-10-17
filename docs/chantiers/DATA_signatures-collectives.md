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

- [x] Migration : colonne `source_authorships.collective`, booléen, faux par défaut (`8b3f1c2e9d54`).
- [x] Règle du domaine qui reconnaît un collectif à son nom (`domain/persons/collective_names.py`). Sur le stock, 2026-10-17 : 1 406 noms distincts, 7 182 signatures (OpenAlex 4 257, DataCite 2 089, ScanR 545, HAL 145, WoS 82, Crossref 64). Aucun nom de personne RH ne la déclenche. « Comite » en est exclu : c'est aussi un nom de famille.

### 2. Normalisation

- [x] Crossref : les entrées à `name` seul deviennent des signatures collectives.
- [x] DataCite : les créateurs `Organizational` deviennent des signatures collectives.
- [x] Toutes les sources : le writer des signatures pose `collective` d'après le signal de la source, ou d'après la règle du nom. La marque entre dans l'empreinte de la signature.

### 3. Traitements en aval

- [x] Phase `persons` : aucune personne pour une signature collective. Les requêtes de sélection et le vote des identifiants les écartent. Une signature collective rattachée à une personne en est détachée, sauf épinglage.
- [x] Phase `authorships` : une signature collective sans personne ne produit aucune ligne d'`authorships`.
- [x] Mesure de l'alignement des auteurs : les signatures collectives sont écartées.

### 4. Reprise du stock

- [ ] Signatures existantes marquées d'après la règle du nom.
- [ ] Notices Crossref et DataCite rejouées depuis le raw store (`rehydrate_staging_from_raw_store`), pour retrouver les collectifs écartés.
- [ ] Les 25 personnes collectives purgées : la phase `persons` détache leurs signatures marquées, puis supprime les personnes vidées.

### 5. Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- **Précision de la règle du nom.** « Network », « Team » ou « Society » peuvent figurer dans un nom de personne ou d'entreprise. La revue des signatures marquées le dira.
