# Résolution des affiliations

*À jour le 2026-10-26.*

La phase `affiliations` rattache les contributions sources aux structures du périmètre, et marque leur entrée dans le périmètre.

- **`refresh_ror`** — importe la dernière version du dump ROR, publié sur Zenodo, si elle n'est pas déjà importée.

- **`refresh_hal_structures`** — charge depuis l'API HAL les structures citées par les contributions sources et absentes du référentiel `ref.hal_structures`, puis leurs parents.

- **`resolve_addresses`** — cherche dans le texte de chaque adresse normalisée les formes de nom des structures (`structure_name_forms`). Le résultat est écrit dans `address_structures`, avec la forme de nom détectée. Les rattachements confirmés ou saisis à la main restent en place.

   Trois options des formes de nom limitent les faux positifs :
   - une forme courte ou marquée « mot entier » compte seulement entre deux caractères qui ne sont pas des lettres ;
   - une forme « à contexte requis » compte seulement si une autre structure de sa liste est reconnue dans l'adresse ;
   - une forme « excluante » empêche la reconnaissance de sa structure dans l'adresse qui la contient.

- **`resolve_thesis_partners`** — rattache le PPN IdRef de chaque laboratoire partenaire de thèse à une structure, par les formes de noms (`idref_structures`).

- **`populate`** — rafraîchit la vue matérialisée `source_contribution_structures`, qui rattache chaque contribution source aux structures du périmètre qu'elle atteint, avec l'indice : adresse, ROR, structure HAL, établissement de soutenance ou laboratoire partenaire d'une thèse. Seul un ROR sans adresse est un indice : pour un ROR rattaché à une adresse, l'adresse fait autorité. Une contribution source entre aussi dans le périmètre quand elle contient un identifiant fort (ORCID, IdRef, `hal_person_id`) d'une personne qui a une fiche RH. Le document paraît alors entre l'année qui suit l'arrivée de la personne et la fin de son contrat. Ces indices sont écrits dans `source_contributions.perimeter_evidence` ; `in_perimeter` est vrai quand la contribution source en a au moins un. Un enregistrement source sans publication dont une contribution source entre dans le périmètre est signalé à la phase [`publications`](07-publications.md), qui en fait une publication.
