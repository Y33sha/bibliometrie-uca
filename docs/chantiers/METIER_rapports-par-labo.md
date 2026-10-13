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

- **Montants d'APC.** Les paiements recensés sont rares et tardifs. Une extraction de l'enquête APC couvre l'année 2025. Le prix catalogue est en devise d'origine. Il ignore les accords transformants.
- **Lien ORCID–idHAL.** Déductible de `author_identifying_keys` : un `hal_person_id` associé à un ORCID (40 631 clés sur 55 559 clés HAL).
- **Revues diamant.** `journals.oa_model` ne distingue pas le diamant. Le payload DOAJ (`journals.doaj_payload`) indique les APC (`APC`) et les autres frais (`Has other fees`) : 835 revues sont sans APC ni autres frais.
- **Thèses.** L'ouverture d'une thèse se mesure sur plusieurs années : les thèses récentes sont en traitement ou sous embargo.
- **Licences.** Chantier [Licences](DATA_licences.md). La licence des jeux de données vient de DataCite (`meta->'rights'`).
- **Serveurs de preprints.** `journals.journal_type = preprint_server` et `publication_relations` (`is_preprint_of`) donnent une partie de l'information.
- **Entrepôts de jeux de données.** Des entrepôts où déposent les laboratoires sont absents des sources de la base.
- **Affiliations des coauteurs.** Seul le pays est résolu pour les adresses hors périmètre. Les institutions partenaires demandent une résolution des adresses vers un référentiel (ROR).
- **Financements ANR et européens.** Crossref fournit les financeurs (`meta->'funder'`, avec numéro de projet). HAL expose `anrProjectReference_s` et `europeanProjectReference_s`, non extraits. OpenAlex expose `grants`, non extrait.

## Décisions

- **Livraison.** Un prototype de rapport, converti ensuite en PDF avec graphiques et feuille de style.
- **Ordre des enrichissements.** Les plus rapides d'abord.
- **Thèses.** Analyse pluriannuelle.
- **Licences.** Affichées au moins pour les jeux de données.

## Phasage

### Phase 1 — Rapport sur les données disponibles

- [x] Maquette peuplée pour un laboratoire, année 2025
- [x] Choix du format de livraison
- [ ] Production du rapport pour un laboratoire quelconque

### Phase 2 — Enrichissements

- [ ] Lien ORCID–idHAL : auteurs du laboratoire dont le compte HAL est lié à un ORCID
- [ ] Revues diamant : identification et part des articles du laboratoire
- [ ] Thèses : ouverture sur plusieurs années de soutenance
- [ ] Montants d'APC : import de l'extraction 2025, montant dans le rapport
- [ ] Licences : licence des jeux de données, puis des publications (chantier dédié)
- [ ] Serveurs de preprints : les plus utilisés
- [ ] Entrepôts de jeux de données absents de la base
- [ ] Affiliations des coauteurs
- [ ] Financements

### Phase 3 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

- Types de documents comptés dans le taux d'open access.
- Source de l'effectif du laboratoire.
