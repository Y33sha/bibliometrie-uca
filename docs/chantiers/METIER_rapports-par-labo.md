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
- Jeux de données des entrepôts sans DOI (GEO, ENA, PDB), cités par numéro d'accession.

### Pistes d'enrichissement

- **Montants d'APC.** Les paiements recensés sont rares et tardifs. Une extraction de l'enquête APC couvre l'année 2025. Le prix catalogue est en devise d'origine. Il ignore les accords transformants.
- **Lien ORCID–idHAL.** Déductible de `author_identifying_keys` : un `hal_person_id` associé à un ORCID (40 631 clés sur 55 559 clés HAL).
- **Revues diamant.** Une revue est diamant quand `journals.oa_model` vaut `diamond`, ou quand le payload DOAJ (`journals.doaj_payload`) n'indique ni APC (`APC`) ni autres frais (`Has other fees`).
- **Thèses.** L'ouverture d'une thèse se mesure sur plusieurs années : les thèses récentes sont en traitement ou sous embargo.
- **Licences.** Chantier [Licences](archived/2026-10-15_DATA_licences.md) : `publications.license` (version éditeur) et `publications.deposit_license` (fichier déposé dans HAL).
- **Serveurs de preprints.** `journals.journal_type = preprint_server` et `publication_relations` (`is_preprint_of`) donnent une partie de l'information.
- **Entrepôts de jeux de données.** Chantier [Extraction par identifiant de personne](archived/2026-10-14_DATA_extraction-par-identifiant-personne.md). Le moissonnage de DataCite par ORCID ajoute 49 jeux de données au périmètre, dont ceux de quatre entrepôts absents jusque-là : EarthChem Library, ICOS Carbon Portal, Build Environment Data_Experiments, DANDI Archive.
- **Affiliations des coauteurs.** Seul le pays est résolu pour les adresses hors périmètre. Les institutions partenaires demandent une résolution des adresses vers un référentiel (ROR).
- **Financements ANR et européens.** Crossref fournit les financeurs (`meta->'funder'`, avec numéro de projet) : 4 938 des 18 360 articles du périmètre parus de 2021 à 2025. Il déclare les financeurs de tous les coauteurs. HAL expose `anrProjectReference_s` et `europeanProjectReference_s`, saisis par les déposants, non extraits. OpenAlex expose `grants`, non extrait.

## Décisions

- **Livraison.** Un prototype de rapport, converti ensuite en PDF avec graphiques et feuille de style.
- **Ordre des enrichissements.** Les plus rapides d'abord.
- **Thèses.** Analyse pluriannuelle.
- **Licences.** Affichées pour les jeux de données, les preprints et les dépôts HAL, avec le nombre de textes intégraux déposés sans licence ouverte.

## Phasage

### Phase 1 — Rapport sur les données disponibles

- [x] Maquette peuplée pour un laboratoire, année 2025
- [x] Choix du format de livraison
- [x] Production du rapport pour un laboratoire quelconque : `interfaces/cli/maintenance/report_open_science.py`

### Phase 2 — Enrichissements

- [x] Lien ORCID–idHAL : auteurs du laboratoire dont le compte HAL est lié à un ORCID
- [x] Revues diamant : identification et part des articles du laboratoire
- [x] Thèses : ouverture sur plusieurs années de soutenance
- [x] Montants d'APC : import de l'extraction 2025, montant dans le rapport
- [x] Licences des jeux de données
- [x] Licences des dépôts HAL, des preprints et des jeux de données, d'après `publications.license` et `publications.deposit_license`. Pour les articles, le taux d'ouverture suffit.
- [x] Serveurs de preprints : les plus utilisés, d'après le préfixe DOI
- [x] Entrepôts de jeux de données absents de la base : moissonnage de DataCite par ORCID
- [x] idHAL des auteurs du laboratoire
- [ ] Affiliations des coauteurs
- [ ] Financements

### Phase 3 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

- Types de documents comptés dans le taux d'open access.
- Source de l'effectif du laboratoire.
- **Laboratoire d'un frais d'open access.** OpenAPC ne nomme pas le laboratoire. Règle mesurée : la seule structure de type laboratoire parmi celles des auteurs correspondants (592 paiements sur 1 217). Le rattachement dépend de `authorships`, que le pipeline reconstruit : le calcul a sa place dans une étape du pipeline.
- **Suppléments d'articles sur figshare.** Les éditeurs déposent sur figshare les suppléments de leurs articles. Les règles de correction des métadonnées les typent en jeux de données (titre « Additional file… », collection figshare). Les pièces d'un même article sont des jeux de données distincts, que seul le titre relie.
