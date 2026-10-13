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
| HAL | `authIdHal_s` (idHAL), `authIdPerson_i` (`hal_person_id`) |

## Décisions

- Interrogation des sources par identifiant de personne, après l'interrogation par affiliation.
- Personnes interrogées : celles de l'export RH, avec un identifiant confirmé ou authentifié.

## Phasage

### Phase 1 — Mesure

- [ ] Documents trouvés par ORCID dans DataCite : part déjà en base, entrepôts, types
- [ ] Même mesure pour OpenAlex, Crossref et HAL

### Phase 2 — Modèle

- [ ] Entrée en staging : mode d'entrée propre aux documents trouvés par identifiant
- [ ] Signature d'une personne trouvée par son identifiant : règle d'entrée dans le périmètre

### Phase 3 — Extraction

- [ ] Nœuds d'extraction par identifiant, une source après l'autre

### Phase 4 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

- Entrée dans le périmètre d'une signature sans affiliation au périmètre, quand l'auteur est une personne RH trouvée par son identifiant.
- Bornage par les dates de contrat : documents publiés avant l'arrivée ou après le départ de la personne.
- Suppléments d'articles déposés par les éditeurs (figshare) : jeux de données à part entière ou bruit.
