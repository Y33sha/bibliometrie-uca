# Chantier — Extraction par identifiant de personne

## Contexte

L'extraction interroge chaque source sur les affiliations : nom d'une structure du périmètre, ROR, collection HAL. Un document dont les auteurs du périmètre signent sans affiliation, ou sous une autre tutelle sans mention de l'université, est absent de la base.

### Mesures

Mesures du 2026-10-13 sur DataCite.

- **Affiliation par ROR.** 884 DOI ont un créateur affilié à l'université par son ROR. 880 sont dans la base. La moisson par nom d'affiliation couvre donc les dépôts affiliés.
- **ORCID.** Les 1 772 ORCID confirmés ou authentifiés des auteurs du périmètre actifs depuis 2021 désignent environ 59 400 DOI publiés de 2021 à 2026, doublons compris.
- **Crossref.** Les 1 091 ORCID des personnes RH désignent 9 697 œuvres parues de 2017 à 2026.
- **OpenAlex.** Les mêmes ORCID désignent 71 131 works parus de 2017 à 2026.
- **Grandes collaborations.** Une notice compte jusqu'à un millier d'auteurs : environ 200 Kio dans DataCite, 500 Kio dans Crossref. Une page trop grande dépasse le délai de DataCite (502) ou la taille de réponse de Crossref (100 Mio).

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
| OpenAlex | filtre `authorships.author.orcid` |
| Crossref | filtre `orcid` |
| HAL | `authIdHal_s` (idHAL) |

## Décisions

- Phase `extract_by_person`, après `extract` : un nœud par source.
- Identifiants acceptés : ORCID dans toutes les sources, idHAL dans HAL, IdRef dans HAL et ScanR (`domain/sources/person_search.py`).
- Personnes interrogées : celles de l'export RH, avec un identifiant confirmé ou authentifié.
- Mode d'entrée en staging : `person_identifier`.
- L'extraction par personne suit la plage d'années des autres extractions.
- Périmètre : la signature d'une personne RH entre dans le périmètre quand le document paraît entre ses dates de début et de fin de contrat, même sans affiliation au périmètre.
- Règle appliquée par la phase `affiliations`, avec `in_perimeter` : la signature contient un identifiant fort (ORCID, IdRef, `hal_person_id`) confirmé ou authentifié d'une personne RH. Les filtres de confiance sont ceux de la phase `persons` (identifiant neutralisé, ORCID des seules sources à dépôt auteur), dans un fragment SQL commun.
- Dates : année de publication comparée aux années de début et de fin de contrat, bornes incluses. Une date inconnue ne borne pas.
- Une signature entrée par l'identité n'est rattachée à aucun laboratoire.
- `in_perimeter` reste booléen.

## Phasage

### Phase 1 — Mesure

- [ ] Documents trouvés par ORCID dans DataCite : part déjà en base, entrepôts, types
- [ ] Même mesure pour OpenAlex, Crossref et HAL

### Phase 2 — Modèle

- [x] Entrée en staging : mode d'entrée `person_identifier`
- [x] Fragment SQL commun des signatures qui contiennent l'identifiant fort d'une personne, repris par la phase `persons`
- [x] Règle d'entrée dans le périmètre par l'identité : phase `affiliations` et recalcul après édition d'une adresse

### Phase 3 — Extraction

- [x] Nœud DataCite, par lots de 10 ORCID, pages de 25 notices
- [x] Socle commun des nœuds : lots, pagination, document écrit une fois par run
- [x] Nœud Crossref, par lots de 10 ORCID, pages de 50 œuvres
- [x] Nœud OpenAlex, par lots de 50 ORCID, pages de 200 works
- [ ] Nœuds HAL, ScanR

### Phase 4 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

- Raison de l'entrée dans le périmètre (affiliation, personne RH dans ses dates) : enum à ajouter, puis suppression éventuelle du booléen.
- Laboratoire d'une signature entrée par l'identité, déduit des publications de la personne. Les `department_name` de l'export RH désignent rarement un laboratoire.
- Suppléments d'articles déposés par les éditeurs sur figshare. Les règles de correction des métadonnées les typent en jeux de données (titre « Additional file… », collection figshare). Les pièces d'un même article sont des jeux de données distincts, que seul le titre relie.
