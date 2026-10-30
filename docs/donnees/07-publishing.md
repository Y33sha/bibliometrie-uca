# Édition

*À jour le 2026-10-28.*

Les référentiels de l'édition décrivent où paraissent les publications. Une publication en série réunit des documents sous un même titre : revue, collection d'ouvrages, recueil d'actes, serveur de preprints, archive ouverte, média. Une monographie est un livre ou un volume d'actes. Un éditeur publie les documents et reçoit les frais de publication. Une plateforme héberge des copies sans les publier : entrepôt, serveur de preprints, plateforme d'éditeurs.

Schéma PostgreSQL `publishing`.

## Publications en série

| Table | Contenu | Contrainte |
|---|---|---|
| `serials` | Titre, type (`serial_type`), éditeur, modèle open access, présence dans le DOAJ, nombre de publications. `manual_fields` : champs saisis à la main, conservés par le pipeline | Identifiant OpenAlex unique |
| `serial_issns` | ISSN, support, ISSN de liaison, statut, date de vérification dans le Sudoc. Un ISSN vérifié sans publication en série désigne une publication absente de la base | Un ISSN de liaison par publication en série |
| `serial_name_forms` | Formes du titre qui désignent la publication en série, avec l'éditeur de la source | Une forme par éditeur, éditeur absent compris |
| `serial_doi_namespaces` | Espaces de noms DOI qui désignent une publication en série, avec la part de leurs DOI qui la désignent | |

## Monographies

| Table | Contenu | Contrainte |
|---|---|---|
| `monographs` | Titre, année, ISBN, éditeur, collection (`serial_id`). `proceedings` distingue un volume d'actes d'un livre | ISBN unique |

## Éditeurs

| Table | Contenu | Contrainte |
|---|---|---|
| `publishers` | Nom, pays, type, nombre de publications | Identifiant OpenAlex unique |
| `publisher_name_forms` | Formes de nom qui désignent l'éditeur | Une forme désigne un seul éditeur |
| `doi_prefixes` | Agence d'enregistrement d'un préfixe DOI et son titulaire, membre Crossref ou client DataCite | Une ligne par préfixe |

L'éditeur d'une publication est le titulaire du préfixe de son DOI Crossref, à défaut l'éditeur de ses enregistrements sources. L'éditeur d'une publication en série est celui de ses publications les plus récentes.

## Plateformes

| Table | Contenu | Contrainte |
|---|---|---|
| `platforms` | Plateformes que nomme OpenAlex : nom et type (entrepôt, serveur de preprints, plateforme d'éditeurs) | Identifiant OpenAlex unique |

Une copie est rattachée à une plateforme connue (`domain/platforms/registry.py`) par son hôte, son préfixe DOI ou sa source OpenAlex. Une autre plateforme garde le nom que lui donne OpenAlex. Les copies hébergées sont les localisations des [enregistrements sources](02-sources.md).

## Frais de publication

| Table | Contenu | Contrainte |
|---|---|---|
| `apc_payments` | Paiement importé d'un fichier ([import](../sources/10-imports-manuels.md#données-apc)) : DOI, montant, années, laboratoire et payeur, publication, publication en série, éditeur. `open_access_fee` distingue les frais d'open access des autres frais | Un paiement par DOI, payeur, montant et nature |

Seuls les paiements d'un payeur du périmètre sont retenus par les lectures.

## Écriture

**Pipeline :**

- La phase [`normalize`](../pipeline/03-normalize.md) crée ou reconnaît la publication en série, la monographie, l'éditeur et les plateformes de chaque enregistrement source.
- Les phases [`resolve_ra` et `publishing`](../pipeline/05-publishing.md) résolvent les préfixes DOI, vérifient les ISSN, fusionnent les doublons, typent les publications en série et calculent les espaces de noms DOI.
- La phase [`finalize`](../pipeline/10-finalize.md) recalcule l'éditeur des publications en série et les nombres de publications, puis supprime les entrées sans usage.

**Administration :**

- Publications en série (`application/services/serials.py`) : édition et fusion. Un changement de type ou de modèle open access requalifie aussitôt les publications de la publication en série.
- Éditeurs (`application/services/publishers.py`) : édition et fusion. La fusion réunit d'abord les publications en série de même titre. Des ISSN contradictoires ou des membres Crossref distincts bloquent la fusion.

**Imports :** frais de publication (`interfaces/cli/imports/import_apc.py`), DOAJ (`interfaces/cli/imports/import_doaj_csv.py`), pays des éditeurs (`interfaces/cli/maintenance/enrich_publishers.py`).
