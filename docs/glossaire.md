# Glossaire métier — Bibliométrie UCA

Termes métier utilisés dans le projet. Pour la documentation technique (pipeline, architecture, sources de données), voir les pages dédiées.

## Sources de données

| Terme | Définition |
|-------|-----------|
| **HAL** | Archive ouverte nationale française. |
| **AuréHAL** | Référentiel d'entités HAL (auteurs, structures, revues). |
| **OpenAlex** | Index bibliographique ouvert (successeur de Microsoft Academic). |
| **Web of Science (WoS)** | Index bibliographique commercial (Clarivate). |
| **Unpaywall** | <span id="unpaywall"></span>Service qui associe un statut d'accès ouvert à chaque DOI. Utilisé pour enrichir le champ `oa_status` des publications. |
| **OpenAPC** | TODO |
| **ScanR** | TODO |
| **CrossRef** | TODO |
| **DataCite** | TODO |


## Identifiants

| Terme | Définition |
|-------|-----------|
| **DOI** | *Digital Object Identifier*. Identifiant unique et pérenne d'une publication (ex: `10.1234/article.5678`). |
| **ORCID** | Identifiant unique d'un chercheur (ex: `0000-0001-2345-6789`). Créé par le chercheur. |
| **idHAL** | Identifiant auteur dans HAL. Créé par le chercheur dans son profil HAL. |
| **IdRef** | Identifiant auteur créé et maintenu par l'ABES (Agence bibliographique de l'enseignement supérieur). |
| **ROR** | <span id="ror"></span>*Research Organization Registry*. Registre international des structures de recherche, attribuant des identifiants uniques à chaque structure. (ex: [01a8ajp46](https://ror.org/01a8ajp46) pour l'UCA). |

## Édition scientifique

| Terme | Définition |
|-------|-----------|
| **APC** | Article Processing Charge. Frais de publication facturés par l'éditeur pour publier en accès ouvert (gold ou hybrid). Peut aller de quelques centaines à plusieurs milliers d'euros. |
| **Éditeur** (publisher) | Maison d'édition scientifique (Elsevier, Springer Nature, EDP Sciences...). Un éditeur publie plusieurs revues. |
| **Revue** (journal) | Périodique scientifique identifié par un ou plusieurs ISSN. Rattaché à un éditeur. |
| **ISSN** | International Standard Serial Number. Identifiant d'un périodique. Il peut exister un ISSN print, un eISSN (électronique) et un ISSN-L (de liaison, qui regroupe les deux). |
| **DOAJ** | Directory of Open Access Journals. Répertoire des revues en accès ouvert. |
| **Auteur correspondant** | Auteur désigné comme contact principal pour une publication. Il peut y en avoir plusieurs. |
| **Premier auteur / dernier auteur** | Conventions de signature scientifique : le premier auteur a généralement fait le travail principal ; le dernier auteur est souvent le directeur de l'équipe. Notion pertinente dans les disciplines STEM. |
| **Adresse** | (= signature institutionnelle) Chaîne de caractères associée à une publication et signalant l'affiliation institutionnelle de chaque auteur. Fournie par chaque auteur à l'éditeur. |

## Voies open access

| Terme | Définition |
|-------|-----------|
| **Green** | Publication déposée en archive ouverte (HAL, arXiv...), en général par l'auteur, parallèlement à sa publication dans une revue. La version déposée peut être un preprint ou un postprint. |
| **Gold** | Publication en accès ouvert dans une revue entièrement OA. Souvent payant (APC). |
| **Diamond** | Sous-catégorie du gold : revue OA sans APC (financement institutionnel). [Unpaywall](sources#unpaywall) ne distingue pas diamond de gold. |
| **Hybrid** | Publication en accès ouvert dans une revue sous abonnement payant. L'auteur paie un APC pour rendre son article spécifique en OA. Déconseillé (l'institution paye les APC + l'abonnement à la revue). |
| **Bronze** | Publication accessible gratuitement sur le site de l'éditeur, sans licence OA explicite. Open access éditeur *de facto*, accès sans garantie de pérennité. |
| **Closed** | Publication fermée, accessible uniquement via abonnement. |

## Entités du référentiel

| Terme | Définition |
|-------|-----------|
| **Publication** | Entité canonique dédupliquée. Plusieurs documents sources (HAL, OA, WoS) peuvent pointer vers la même publication. Déduplication par DOI ou par titre+année+journal. |
| **Personne** | Individu physique unique. Hub d'identité reliant les auteurs de toutes les sources. Peut être créé automatiquement (pipeline) ou manuellement (import RH). |
| **Authorship** | <span id="authorship"></span>Couple (publication, personne) représentant la contribution d'un auteur à une publication. Porte les informations d'affiliation (structures UCA), de position (rang dans la liste d'auteurs) et le flag `is_uca`. |
| **Structure** | Entité institutionnelle : université, laboratoire, organisme national de recherche (CNRS, INRAE...), établissement partenaire (CHU, INP...). Référentiel maintenu manuellement. |
| **Forme de nom** | Variante normalisée d'un nom de structure (`structure_name_forms`) ou d'un nom d'auteur (`person_name_forms`). Utilisée pour le matching automatique (résolution d'adresses pour les structures, création de personnes pour les auteurs). |

## Types de documents

| Terme | Définition |
|-------|-----------|
| **Article** | Publication dans une revue à comité de lecture. Type le plus courant. |
| **Review** | Article de synthèse (revue de la littérature). Attention : dans WoS, "book review" désigne un compte-rendu d'ouvrage, pas une revue de la littérature. |
| **Book** | Ouvrage (monographie). Peut partager un DOI avec ses chapitres. |
| **Book chapter** | Chapitre d'ouvrage. Le DOI est parfois celui de l'ouvrage entier (cas géré par le pipeline). |
| **Conference paper** | Communication dans un colloque ou une conférence. Inclut les posters dans certaines sources. |
| **Preprint** | Version pré-publication déposée avant peer review (arXiv, HAL, etc.). |
| **Thesis** | Thèse de doctorat ou HDR (habilitation à diriger des recherches). |
| **Editorial** | Éditorial de revue. |
| **Peer review** | Rapport d'évaluation d'un article. Les "auteurs" listés sont ceux de l'article évalué, pas du review — cas traité spécifiquement dans le pipeline. |

## Périmètre UCA

| Terme | Définition |
|-------|-----------|
| **Périmètre restreint** | UCA + ses unités en tutelle directe. Détermine si un auteur est considéré "UCA" sur une publication (flag `is_uca`). |
| **Périmètre élargi** | Périmètre restreint + établissements partenaires (CHU Clermont-Ferrand, Clermont Auvergne INP, VetAgro Sup...). Utilisé pour les affiliations détaillées (`structure_ids`). |
| **Tutelle** | Relation hiérarchique entre une institution et un laboratoire. L'UCA est tutelle de ~30 laboratoires. Un laboratoire peut avoir plusieurs tutelles (co-tutelle CNRS, INRAE...). |
