# Plateformes et localisations — cycle de vie

*À jour le 2026-10-25.*

Une localisation est une copie d'un document : une page, éventuellement un PDF, avec sa version, sa licence et son ouverture. Une plateforme héberge des copies sans les publier : entrepôt (HAL, PubMed Central, Zenodo), serveur de preprints (arXiv, bioRxiv), plateforme d'éditeurs (Cairn, OpenEdition). Une plateforme n'est pas un éditeur. `domain/platforms/` définit les types de plateforme et la liste fermée des plateformes connues ; `domain/publications/access.py`, le choix des copies d'accès d'une publication.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `platforms` | La plateforme | `name` / `name_normalized`, `platform_type` (`repository`, `preprint_server`, `publisher_platform`, `unknown`), `openalex_id` (unique) |
| `source_record_locations` | Copie d'un document, d'après un enregistrement source | `(source_record_id, url)`, `pdf_url`, `oai_id`, `version` (vocabulaire de la source), `license`, `is_oa`, `platform_id` |

## Écriture par le pipeline

**Localisations (`normalize`).** Les localisations d'un enregistrement source se réécrivent à chaque normalisation (`pipeline/ingestion/common/locations.py`) :

- OpenAlex donne chaque copie du document, avec sa version, sa licence et son ouverture. Une copie sur une source OpenAlex de type `repository` reçoit sa plateforme. OpenAlex range parfois sous PubMed Central une page PubMed : son adresse devient la page de l'article sur PMC, d'après le PMCID de son PDF, à défaut la copie perd sa plateforme.
- Crossref donne la page vers laquelle résout le DOI, avec la licence de la version éditeur.
- HAL donne la page du dépôt et le fichier déposé, sur la plateforme HAL. La copie est ouverte quand un fichier est déposé, hors embargo actif.
- Pour toutes les sources, l'identifiant arXiv et le PMCID d'un enregistrement donnent une copie ouverte, sans version, sur arXiv et PubMed Central (`domain/platforms/registry.py`, `IDENTIFIER_COPIES`).

**Plateformes (`normalize`).** Une plateforme se crée à sa première localisation et se reconnaît par son identifiant OpenAlex. Une plateforme de la liste des plateformes connues en prend le nom et le type ; une autre prend le nom que lui donne OpenAlex et le type entrepôt.

## Lecture par le pipeline

**Éditeur d'une publication.** Le préfixe DOI d'une plateforme d'éditeurs désigne la plateforme : ni son titulaire ni un enregistrement source qui le nomme ne donnent l'éditeur (fiche [publications](publications.md)). La liste des plateformes connues contient ces préfixes.

**Serveur de preprints.** Le bilan Science ouverte (`interfaces/cli/maintenance/report_open_science.py`) reconnaît le serveur de preprints d'une publication par la plateforme de ses localisations, à défaut par le préfixe de son DOI.

## Lecture par l'API

Le détail d'une publication (`GET /api/publications/{id}`) donne ses copies d'accès, calculées sur les localisations de ses enregistrements sources, hors formes secondaires :

- seules comptent les copies ouvertes à adresse `http` ou `https` ;
- sur une plateforme qui décrit elle-même la publication, HAL pour HAL, l'enregistrement source de la plateforme décide de l'ouverture : les copies que les autres sources lui attribuent sont écartées ;
- une copie se classe par sa version (éditeur, acceptée, soumise, inconnue), puis par l'ordre d'arrivée de son enregistrement source ;
- la meilleure copie est l'adresse d'accès ; les liens d'accès donnent la meilleure copie de chaque plateforme, sauf la copie désignée par le DOI, affiché à part.

Le détail donne aussi les sources qui référencent la publication sans en donner de copie : toutes sauf Crossref et DataCite, que couvre le DOI, et HAL quand HAL figure parmi les liens d'accès.

Les adresses des copies sont les seules adresses affichées dont l'hôte vient des données : le serveur en vérifie seulement le schéma (`interfaces/frontend/src/lib/external-links.test.ts`).
