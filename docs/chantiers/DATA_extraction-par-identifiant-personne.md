# Chantier — Extraction par identifiant de personne

## Contexte

L'extraction interroge chaque source sur les affiliations : nom d'une structure du périmètre, ROR, collection HAL. Un document dont les auteurs du périmètre signent sans affiliation, ou sous une autre tutelle sans mention de l'université, est absent de la base.

### Mesures

Mesures du 2026-10-13 sur DataCite.

- **Affiliation par ROR.** 884 DOI ont un créateur affilié à l'université par son ROR. 880 sont dans la base. La moisson par nom d'affiliation couvre donc les dépôts affiliés.
- **ORCID.** Les 1 772 ORCID confirmés ou authentifiés des auteurs du périmètre actifs depuis 2021 désignent environ 59 400 DOI publiés de 2021 à 2026, doublons compris.

### Personnes interrogées

Les personnes de l'export RH (`persons_rh`), avec un identifiant confirmé ou authentifié (`person_identifiers.status`).

| Identifiant | Personnes RH |
| --- | --- |
| ORCID authentifié | 574 |
| ORCID confirmé | 512 |
| IdRef confirmé | 1 062 |
| `hal_person_id` confirmé | 991 |
| idHAL confirmé | 735 |

`persons_rh` donne les dates de début et de fin de contrat (`start_date`, `end_date`).

### Requêtes par identifiant

| Source | Champ |
| --- | --- |
| DataCite | `creators.nameIdentifiers.nameIdentifier` (ORCID) |
| OpenAlex | filtre `author.orcid` |
| Crossref | filtre `orcid` |
| HAL | `authIdHal_s` (idHAL) |

## Décisions

- Phase `extract_by_person`, après `extract` : un nœud par source.
- Identifiants acceptés : ORCID dans toutes les sources, idHAL dans HAL, IdRef dans HAL et ScanR (`domain/sources/person_search.py`).
- Personnes interrogées : celles de l'export RH, avec un identifiant confirmé ou authentifié.
- Mode d'entrée en staging : `person_identifier`.
- L'extraction par personne suit la plage d'années des autres extractions.
- Périmètre : la signature d'une personne RH entre dans le périmètre quand le document paraît entre ses dates de début et de fin de contrat, même sans affiliation au périmètre.

## Phasage

### Phase 1 — Mesure

- [ ] Documents trouvés par ORCID dans DataCite : part déjà en base, entrepôts, types
- [ ] Même mesure pour OpenAlex, Crossref et HAL

### Phase 2 — Modèle

- [x] Entrée en staging : mode d'entrée `person_identifier`
- [ ] Signature d'une personne trouvée par son identifiant : règle d'entrée dans le périmètre

### Phase 3 — Extraction

- [x] Nœud DataCite, par lots de 10 ORCID
- [ ] Nœuds OpenAlex, Crossref, HAL, ScanR

### Phase 4 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

- Représentation du périmètre d'une signature : booléen `in_perimeter`, ou valeur qui dit pourquoi la signature entre dans le périmètre (affiliation, personne RH dans ses dates).
- Décision du périmètre par la phase `persons`, d'après le `person_id` de la signature. La phase `persons` rattache seulement les signatures des notices devenues publications. Elle rattacherait aussi, par identifiant fort, celles des notices hors périmètre. Une notice qui entre ainsi dans le périmètre devient publication au run suivant.
- Suppléments d'articles déposés par les éditeurs sur figshare. Les règles de correction des métadonnées les typent en jeux de données (titre « Additional file… », collection figshare). Les pièces d'un même article sont des jeux de données distincts, que seul le titre relie.
