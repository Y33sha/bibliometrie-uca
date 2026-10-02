# Chantier — Rapports annuels par laboratoire

## Contexte

La cellule Science ouverte produit chaque année un bilan par laboratoire : production, taux d'open access, revues, APC, collaborations, thèses, ORCID, jeux de données. Une maquette peuplée pour un laboratoire, sur l'année 2025, sert de référence.

### Données disponibles

Une publication appartient au laboratoire si une adresse d'auteur est rattachée à la structure (`publication_structures`).

- Typologie, revues, éditeurs, conférences, thèses : `publications`, `journals`, `publishers`.
- Open access : `publications.oa_status`. Le texte intégral dans HAL se lit sur la source HAL (`source_publications.oa_status` `green` ou `embargoed`, dérivé de `fileMain_s`).
- Modèle de la revue : `journals.oa_model` (abonnement ou open access), `is_in_doaj`. Le statut diamant vient de `publications.oa_status`.
- APC payées : `apc_payments`, rattachées à la publication. APC catalogue : `journals.apc_amount` et `apc_currency`.
- Auteur correspondant : `authorships.is_corresponding`.
- Pays des coauteurs : `publications.countries`.
- ORCID : `person_identifiers`, sur les auteurs du laboratoire.

### Données absentes

- Effectif du laboratoire : l'export RH omet certains laboratoires.
- CV HAL.
- Régime de diffusion des thèses et délai de mise en ligne.
- Entrepôts et licences des jeux de données.

### Pistes d'enrichissement

- **Montants d'APC.** Les paiements recensés sont rares et tardifs. Le prix catalogue est en devise d'origine. Il ignore les accords transformants.
- **Affiliations des coauteurs.** Seul le pays est résolu pour les adresses hors périmètre. Les institutions partenaires demandent une résolution des adresses vers un référentiel (ROR).
- **Serveurs de preprints.** `journals.journal_type = preprint_server` et `publication_relations` (`is_preprint_of`) donnent une partie de l'information.
- **Licences.** Chantier [Licences](DATA_licences.md).
- **Revues diamant.** `journals.oa_model` ne distingue pas le diamant. Candidats : revues DOAJ sans APC, listes nationales.
- **Lien ORCID–idHAL.** Déductible de `author_identifying_keys` : un `hal_person_id` associé à un ORCID.
- **Financements ANR et européens.** Crossref fournit les financeurs (`meta->'funder'`, avec numéro de projet). HAL expose `anrProjectReference_s` et `europeanProjectReference_s`, non extraits. OpenAlex expose `grants`, non extrait.

## Décisions

## Phasage

### Phase 1 — Rapport sur les données disponibles

- [x] Maquette peuplée pour un laboratoire, année 2025
- [ ] Choix du format de livraison
- [ ] Production du rapport pour un laboratoire quelconque

### Phase 2 — Enrichissements

- [ ] Licences (chantier dédié)
- [ ] Financements
- [ ] Serveurs de preprints
- [ ] Revues diamant
- [ ] Montants d'APC
- [ ] Affiliations des coauteurs

### Phase 3 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

- Format de livraison : document généré, page du frontend, export PDF.
- Types de documents comptés dans le taux d'open access.
- Source de l'effectif du laboratoire.
