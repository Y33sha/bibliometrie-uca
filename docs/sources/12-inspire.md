# INSPIRE-HEP

*À jour le 2026-11-07.*

https://inspirehep.net/

Documentation API : https://github.com/inspirehep/rest-api-doc

INSPIRE-HEP est la base disciplinaire de la physique des hautes énergies, tenue par le CERN, DESY, Fermilab, l'IHEP et SLAC. Elle couvre la discipline quel que soit le laboratoire. Ses équipes rattachent chaque auteur à des fiches d'institutions et à son profil d'auteur.

Le pipeline interroge INSPIRE-HEP de deux façons :
- [moissonnage](../pipeline/02-harvest.md#moissonnage-par-affiliation-harvest), par année : les fiches dont un auteur est affilié à une institution du périmètre (champ INSPIRE-HEP des identifiants de structure). Un numéro d'institution INSPIRE est cherché par `affid`, un nom d'affiliation par `aff` ;
- [moissonnage par personne](../pipeline/02-harvest.md#moissonnage-par-personne-harvest_by_person) : les fiches dont un auteur a l'ORCID d'une personne RH (`authors.ids.value`).

Le filtre d'année `date` retient une fiche quand l'une de ses dates tombe dans l'année : publication, impression ou prépublication. Une fiche datée de plusieurs années de la fenêtre revient seulement dans la première.

## API utilisée

**Literature API** :
- `https://inspirehep.net/api/literature?q=…` : recherche paginée (moissonnages) ;
- `https://inspirehep.net/api/literature/{numéro}` : interrogation unitaire (`fetch_stale`).

Chaque requête demande les mêmes champs (paramètre `fields`), sans nombre de citations, sans références et sans affiliations brutes. `staging` garde le seul `metadata` d'une fiche.

- Aucun identifiant d'accès
- Débit et requêtes simultanées du pipeline : `pipeline/ingestion/api_params.py`

## Données récupérées

- **Publications** : numéro de fiche, titre, type, date de publication, résumé, titre abrégé de la revue, volume, numéro, pages ou numéro d'article. Identifiants : DOI, DOI du dépôt arXiv, hal-id, numéro de fiche du CERN Document Server.
- **Auteurs** : nom et prénom, ORCID, institutions rattachées par INSPIRE, rôle (auteur, éditeur, directeur de thèse).

## Exemple de payload

Article `10.1103/PhysRevD.108.012021` de la collaboration LHCb. Réduit à un auteur et aux champs lus par le pipeline ; résumé tronqué.

```json
{
  "control_number": 2683002,
  "titles": [{ "title": "Search for baryon-number-violating B0 → pμ− decays…" }],
  "document_type": ["article"],
  "dois": [{ "source": "APS", "value": "10.1103/PhysRevD.108.012021", "material": "publication" }],
  "arxiv_eprints": [{ "value": "2210.10412", "categories": ["hep-ex"] }],
  "external_system_identifiers": [
    { "schema": "HAL", "value": "hal-04174615" },
    { "schema": "CDS", "value": "2838028" }
  ],
  "publication_info": [
    { "journal_title": "Phys.Rev.D", "journal_volume": "108", "journal_issue": "1", "artid": "012021", "year": 2023, "material": "publication" }
  ],
  "earliest_date": "2022-10-19",
  "abstracts": [{ "source": "APS", "value": "A search for the baryon- and lepton-number violating decays… (tronqué)" }],
  "authors": [
    {
      "full_name": "Deschamps, Olivier",
      "first_name": "Olivier",
      "last_name": "Deschamps",
      "ids": [{ "schema": "ORCID", "value": "0000-0002-7047-6042" }],
      "affiliations": [{ "record": { "$ref": "https://inspirehep.net/api/institutions/902740" }, "value": "Clermont-Ferrand U." }]
    }
  ]
}
```

## Particularités

### Institution comme adresse

L'adresse d'une contribution source est le nom de chaque institution rattachée à l'auteur (« Clermont-Ferrand U. »). La phase [`affiliations`](../pipeline/04-affiliations.md) la reconnaît par les formes de nom des structures. L'affiliation brute, reprise de l'éditeur, reste hors du payload : elle reproduit les décalages d'affiliations de certains éditeurs entre auteurs homonymes. Le ROR donné par INSPIRE va sur l'adresse d'un auteur à une seule institution.

### Type de document

Le type est le premier de `document_type`. Un article sans revue (`publication_info.journal_title`) a le type `article_preprint`, traduit en *preprint*. La conversion vers le vocabulaire du référentiel se fait dans le mapping `inspire` de [`doc_types`](https://github.com/Y33sha/bibliometrie-uca/blob/master/domain/source_records/doc_types.py).

### Date de publication

L'année est celle de la première publication (`publication_info.year`), hors erratum et addendum. La date d'impression (`imprints.date`) la précise quand elle a la même année. Sans publication, la date est celle de l'impression, à défaut celle de la prépublication (`preprint_date`), puis la plus ancienne date connue (`earliest_date`).

### Identifiants

Le DOI d'un autre document (erratum, addendum, jeu de données) est lié dès qu'une de ses mentions le marque ainsi. L'identifiant arXiv devient le DOI de son dépôt (`10.48550/arxiv.<identifiant>`). Le hal-id et le numéro de fiche CDS sont des clés de confirmation de la [réconciliation](../pipeline/07-publications.md) : la fiche rejoint ainsi le dépôt HAL et la copie CDS du même article.

### Revue

INSPIRE nomme la revue par son titre abrégé (`Phys.Rev.D`), sans ISSN. Ce titre reste un titre libre du conteneur. La revue d'une publication vient des autres sources.
