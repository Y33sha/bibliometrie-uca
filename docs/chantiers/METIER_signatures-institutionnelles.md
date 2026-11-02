# Chantier — Signatures institutionnelles

Distinguer les adresses brutes, et montrer pour chaque personne les structures citées dans ses adresses brutes.

## Contexte

Une partie des publications de l'Alliance UCA est absente des publications de l'université dans les bases bibliographiques : l'adresse de l'auteur omet l'université. Cas typique : un enseignant-chercheur de l'UCA qui exerce au CHU signe « CHU Clermont-Ferrand » seul.

`address_structures` rattache une adresse à chaque structure dont une forme de nom figure dans le texte. L'onglet Adresses d'une personne, réservé à l'administration, montre par année la part de ses publications avec une adresse rattachée à chaque structure.

Une adresse est un texte, partagé par toutes les sources qui le donnent. Une adresse brute reproduit l'adresse imprimée dans la publication. Le champ d'adresse des sources contient aussi d'autres textes :

- libellés HAL complets, « SIGLE - Nom (adresse postale - Pays) » : 11 835 adresses, presque toutes chez OpenAlex ;
- noms seuls de structure ou d'établissement : nom HAL (« Université Clermont Auvergne [2017-2020] »), nom ROR (« University of Liverpool »), nom suivi du sigle (« Laboratoire Magmas et Volcans (LMV) ») ;
- arborescences de structures HAL chez scanR : nom, code et sigle du laboratoire, puis ses tutelles et son adresse postale (« Institut Pascal, UMR6602, UMR6602, IP, CNRS, UCA… ») ;
- textes étrangers à une adresse (« Author to whom correspondence should be addressed. », « Professeur »).

Mesure du 2026-10-27, base locale, enseignants-chercheurs de l'UCA : 71 % des publications avec adresse brute mentionnent l'université, 62 % en comptant les libellés HAL repris par OpenAlex.

## Décisions

1. **Adresse brute** : texte de l'adresse tel qu'il figure dans la publication. La colonne `is_raw` de `addresses` la distingue des autres textes.
2. **Critères** : propriétés du texte seul. `is_raw` vaut pour toutes les sources qui donnent le texte.
3. **Portée** : `is_raw` filtre les indicateurs. Toute adresse reste un indice de périmètre et rattache ses structures.
4. **Indicateur** : structures citées dans les adresses brutes de la personne, en part de ses publications avec adresse brute. Il vaut pour toute personne.
5. **Restitution** : sur la personne seulement. Le lien entre une personne et une structure se déduit des structures de ses contributions : un indicateur par structure serait circulaire.

## Phasage

### Phase 1 — Adresses brutes

- [x] Adresses sans virgule, hors libellés HAL complets. Base locale, 2026-11-02 : 40 924 adresses, pour 376 722 couples (adresse, enregistrement source).
  - 52 % des couples : nom exact d'une structure HAL ou d'une organisation ROR.
  - 11 % : texte terminé par un nom de pays. Échantillon de 15 : 12 adresses brutes (« Breast Unit Institute Gustave Roussy Villejuif France »), 3 noms suivis du pays entre parenthèses.
  - 37 % : reste. Échantillon de 40 : surtout des noms seuls et des textes étrangers à une adresse ; 3 adresses brutes sans pays (« Department of Pediatrics University Hospital Rouen »).
- [ ] Critères : libellé HAL complet ; nom exact d'une structure HAL ou d'une organisation ROR ; texte sans virgule et sans nom de pays final ; arborescence de structures HAL.
- [ ] Colonne `is_raw` sur `addresses`, calculée par le pipeline. La migration remplit le stock.
- [ ] Adresses non brutes signalées sur la page d'administration des adresses.

### Phase 2 — Indicateurs

- [ ] Onglet Adresses de la personne : comptes calculés sur les seules adresses brutes.
- [ ] Dashboard de la personne : structures citées dans ses adresses brutes, toutes années confondues.
- [ ] Documentation.

## Questions ouvertes

- **Arborescences de structures HAL** : quel critère de texte ? Elles contiennent des virgules.
- **Calcul de `is_raw`** : quelle phase ? Les critères lisent les noms HAL, les noms ROR et les noms de pays. Recalcul de toutes les adresses à chaque passage, ou des seules adresses créées ?
- **Visibilité de l'indicateur** sur le dashboard de la personne : tous les utilisateurs, ou l'administration seulement, comme l'onglet Adresses ?

## Liens

- Convention de signature : <https://www.uca.fr/recherche/science-ouverte-et-publication/politique-de-signature-des-publications>
- Tables : `addresses`, `source_contribution_addresses`, `address_structures`, `hal_structures`, `ror_organizations`, `place_name_forms`.
- Phase `affiliations` : `pipeline/transformation/structures/`.
