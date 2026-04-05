# Glossaire — Bibliométrie UCA

Termes métier utilisés dans le projet. Pour la documentation technique (pipeline, architecture, sources de données), voir les pages dédiées.

## Sources de données

| Terme | Définition |
|-------|-----------|
| **HAL** | Archive ouverte nationale française. Les chercheurs y déposent volontairement leurs publications en texte intégral. Bonne couverture en SHS, plus faible en sciences dures. |
| **OpenAlex** | Index bibliographique ouvert (successeur de Microsoft Academic). Couverture très large (>200M de publications), rattachement institutionnel algorithmique. |
| **Web of Science (WoS)** | Index bibliographique commercial (Clarivate). Couverture sélective mais métadonnées de qualité. Accès par API payante avec quota annuel. |
| **Unpaywall** | Service qui associe un statut d'accès ouvert à chaque DOI. Utilisé pour enrichir le champ `oa_status` des publications. |

## Identifiants

| Terme | Définition |
|-------|-----------|
| **DOI** | Digital Object Identifier. Identifiant unique et pérenne d'une publication (ex: `10.1234/article.5678`). Un même DOI peut être partagé entre un ouvrage et ses chapitres (cas problématique géré par le pipeline). |
| **ORCID** | Identifiant unique d'un chercheur (ex: `0000-0001-2345-6789`). Auto-déclaratif. Fiable quand confirmé, mais parfois attribué par erreur dans les bases bibliographiques. |
| **idHAL** | Identifiant auteur dans HAL. Créé par le chercheur dans AuréHAL pour regrouper ses publications sous un compte unique. Plus fiable que l'ORCID dans le contexte HAL. |
| **IdRef** | Identifiant du référentiel des autorités du SUDOC (réseau des bibliothèques universitaires françaises). Utilisé pour relier un chercheur à sa production dans le catalogue des thèses. |
| **AuréHAL** | Interface de gestion des référentiels HAL (auteurs, structures, revues). C'est là que les chercheurs créent leur idHAL et rattachent leurs publications à leur compte. |
| **ROR** | Research Organization Registry. Identifiant unique d'une institution de recherche (ex: `https://ror.org/01a8ajp46` pour l'UCA). Utilisé par OpenAlex pour le rattachement institutionnel. |

## Édition scientifique

| Terme | Définition |
|-------|-----------|
| **APC** | Article Processing Charge. Frais de publication facturés par l'éditeur pour publier en accès ouvert (gold ou hybrid). Peut aller de quelques centaines à plusieurs milliers d'euros. |
| **Éditeur** (publisher) | Maison d'édition scientifique (Elsevier, Springer Nature, EDP Sciences...). Un éditeur publie plusieurs revues. |
| **Revue** (journal) | Périodique scientifique identifié par un ou plusieurs ISSN. Rattaché à un éditeur. |
| **ISSN** | International Standard Serial Number. Identifiant d'un périodique. Il peut exister un ISSN print, un eISSN (électronique) et un ISSN-L (de liaison, qui regroupe les deux). |
| **DOAJ** | Directory of Open Access Journals. Répertoire des revues en accès ouvert intégral (gold/diamond). Une revue présente dans le DOAJ est considérée full open access. |
| **Auteur correspondant** | Auteur désigné comme contact principal pour une publication. Souvent le chercheur qui a piloté l'étude. Information disponible principalement dans WoS. |
| **Premier auteur / dernier auteur** | Conventions de signature scientifique : le premier auteur a généralement fait le travail principal ; le dernier auteur est souvent le directeur de l'équipe (en sciences expérimentales). |

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
| <a id="authorship"></a>**Authorship** | Couple (publication, personne) représentant la contribution d'un auteur à une publication. Porte les informations d'affiliation (structures UCA), de position (rang dans la liste d'auteurs) et le flag `is_uca`. Aussi appelé "contribution" dans le langage courant. |
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
