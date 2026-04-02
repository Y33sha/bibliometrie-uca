# Glossaire — Bibliométrie UCA

Ce glossaire définit les termes métier utilisés dans le projet. Les termes sont
regroupés par domaine.

## Sources de données

| Terme | Définition |
|-------|-----------|
| **HAL** | Archive ouverte nationale française. Les chercheurs y déposent volontairement leurs publications. |
| **OpenAlex** | Index bibliographique ouvert (successeur de Microsoft Academic). Large couverture mais entités auteur peu fiables (fusions erronées fréquentes). |
| **Web of Science (WoS)** | Index bibliographique commercial (Clarivate). Couverture sélective mais métadonnées de qualité. Entités auteur algorithmiques, non fiables. |
| **Staging** | Tables d'import brut (`staging_hal`, `staging_openalex`, `staging_wos`). Contiennent la réponse API en JSONB, sans transformation. |
| **Normalisation** | Transformation des données brutes (staging) en tables structurées par source (documents, authors, authorships). |

## Entités

| Terme | Définition |
|-------|-----------|
| **Publication** | Entité canonique dédupliquée. Plusieurs documents sources (HAL, OA, WoS) peuvent pointer vers la même publication. Déduplication par DOI, liens explicites, ou heuristique titre+année+journal. |
| **Personne** (`persons`) | Individu physique unique. Hub d'identité reliant les auteurs de toutes les sources. Peut être créé automatiquement (pipeline) ou manuellement (import RH). |
| **Auteur source** (`hal_authors`, etc.) | Entité auteur telle que définie par la source. Un même individu peut avoir plusieurs auteurs source (variantes de nom, comptes multiples). Non fiable pour OpenAlex et WoS. |
| **Authorship source** (`hal_authorships`, etc.) | Lien entre un document source et un auteur source. Porte le `person_id` (lien vers la personne canonique), les affiliations, et le flag `is_uca`. |
| **Authorship vérité** (`authorships`) | Lien canonique entre une publication et une personne. Construit par `build_authorships.py` à partir des authorships sources. Porte les FK vers les authorships sources d'origine. |
| **Structure** | Entité institutionnelle : université, laboratoire, équipe, tutelle (CNRS, INRAE...), partenaire (CHU, INP...). Référentiel maintenu manuellement. |

## Personnes et noms

| Terme | Définition |
|-------|-----------|
| **`persons_rh`** | Table satellite contenant les données RH (département, poste, dates). Une personne sans entrée RH a été créée automatiquement depuis les authorships. |
| **Forme de nom** (`person_name_forms`) | Forme normalisée d'un nom d'auteur observé dans les sources. Utilisée pour le matching automatique lors de la création de personnes. Une forme peut pointer vers plusieurs personnes (homonymes = forme **ambiguë**). |
| **`author_name_normalized`** | Colonne sur chaque authorship source contenant le nom de l'auteur normalisé via `normalize_name_form()`. Permet le matching direct avec `person_name_forms.name_form`. |
| **Identifiant certifiant** | ORCID, idHAL ou IdRef. Garantit l'unicité d'une personne : si deux authorships partagent le même ORCID, elles correspondent à la même personne. Stockés dans `person_identifiers` avec un statut (`pending`, `confirmed`, `rejected`). |
| **Fusion** (merge) | Opération qui absorbe une personne dans une autre : transfère tous les auteurs, authorships, identifiants et formes de nom. Bloquée si les deux personnes ont chacune une fiche RH. |

## Périmètre UCA

| Terme | Définition |
|-------|-----------|
| **UCA** | Université Clermont Auvergne — l'institution dont on suit la production scientifique. |
| **Périmètre restreint** (`is_uca`) | UCA + ses unités en tutelle directe (`est_tutelle_de`). Détermine si un auteur est considéré "UCA" sur une publication. |
| **Périmètre élargi** (`structure_ids`) | Périmètre restreint + partenaires (`est_partenaire_de` : CHU, INP, VetAgro Sup). Utilisé pour les affiliations. |
| **`is_uca`** | Flag booléen sur les authorships (sources et vérité). TRUE si l'auteur est affilié au périmètre UCA restreint sur cette publication. |
| **`excluded`** | Flag sur une authorship source indiquant un rattachement erroné (homonyme, affiliation incorrecte). Les authorships exclues sont ignorées par `build_authorships.py`. |

## Pipeline

| Terme | Définition |
|-------|-----------|
| **Moissonnage** (extract) | Récupération des données depuis les API sources (HAL, OpenAlex, WoS) vers les tables staging. |
| **Cross-import** | Récupération dans une source B des publications trouvées dans une source A mais absentes de B (ex: un DOI trouvé dans HAL est cherché dans OpenAlex). |
| **UCA flags** | Étape qui calcule `is_uca` et `structure_ids` sur les authorships sources, en croisant les affiliations avec le référentiel de structures. |
| **Build authorships** | Construction de la table `authorships` (vérité) par agrégation des authorships sources. Insère les paires (publication, personne), peuple les FK, propage positions, UCA et structures. |

## Interface d'administration

| Terme | Définition |
|-------|-----------|
| **Authorship orpheline** | Authorship source UCA dont le `person_id` est NULL — l'auteur n'a pas encore été identifié. Visible dans l'interface admin pour attribution manuelle. |
| **Forme ambiguë** | Forme de nom associée à plusieurs `person_ids`. Signale un homonyme potentiel nécessitant une intervention manuelle. |
| **Doublon publications** | Deux publications distinctes dans la table `publications` qui correspondent en réalité au même article. Détectées par similarité de titre et proposées à la fusion dans l'interface admin. |
| **Doublon personnes** | Deux personnes distinctes qui correspondent au même individu. Détectées par similarité de nom + publications communes et proposées à la fusion. |
