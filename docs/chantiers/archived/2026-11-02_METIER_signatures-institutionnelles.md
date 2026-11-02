# Chantier — Signatures institutionnelles

Distinguer les adresses brutes, et montrer pour chaque personne les structures citées dans ses adresses brutes.

## Contexte

Une partie des publications de l'Alliance UCA est absente des publications de l'université dans les bases bibliographiques : l'adresse de l'auteur omet l'université. Cas typique : un enseignant-chercheur de l'UCA qui exerce au CHU signe « CHU Clermont-Ferrand » seul.

`address_structures` rattache une adresse à chaque structure dont une forme de nom figure dans le texte. L'onglet Adresses d'une personne, réservé à l'administration, montre par année la part de ses publications avec une adresse rattachée à chaque structure.

Une adresse est un texte, partagé par toutes les sources qui le donnent. Une adresse brute reproduit l'adresse imprimée dans la publication. Le champ d'adresse des sources contient aussi d'autres textes :

- libellés HAL complets, « SIGLE - Nom (adresse postale - Pays) » : 11 835 adresses, presque toutes chez OpenAlex ;
- noms seuls de structure ou d'établissement : nom HAL (« Université Clermont Auvergne [2017-2020] »), nom ROR (« University of Liverpool »), nom suivi du sigle (« Laboratoire Magmas et Volcans (LMV) ») ;
- textes étrangers à une adresse (« Author to whom correspondence should be addressed. », « Professeur »).

Mesure du 2026-10-27, base locale, enseignants-chercheurs de l'UCA : 71 % des publications avec adresse brute mentionnent l'université, 62 % en comptant les libellés HAL repris par OpenAlex.

## Décisions

1. **Adresse brute** : texte de l'adresse tel qu'il figure dans la publication. La colonne énumérée `origin` de `addresses` distingue l'adresse brute du libellé HAL et du nom seul.
2. **Critères** : propriétés du texte, confronté aux référentiels HAL et ROR. `origin` vaut pour toutes les sources qui donnent le texte.
3. **Calcul** : une tâche de la phase `affiliations`, placée avant la résolution des adresses, calcule les `origin` vides.
4. **Portée** : `origin` filtre les onglets Adresses de la personne et de la structure. Toute adresse reste un indice de périmètre et rattache ses structures.
5. **Indicateur** : structures citées dans les adresses brutes de la personne, en part de ses publications avec adresse brute. Il vaut pour toute personne.

## Phasage

### Phase 1 — Adresses brutes

- [x] Adresses sans virgule, hors libellés HAL complets. Base locale, 2026-11-02 : 40 924 adresses, pour 376 722 couples (adresse, enregistrement source).
  - 52 % des couples : nom exact d'une structure HAL ou d'une organisation ROR.
  - 11 % : texte terminé par un nom de pays. Échantillon de 15 : 12 adresses brutes (« Breast Unit Institute Gustave Roussy Villejuif France »), 3 noms suivis du pays entre parenthèses, au format des libellés HAL (« Narvik University College (Norway) »).
  - 37 % : reste. Échantillon de 40 : surtout des noms seuls et des textes étrangers à une adresse ; 3 adresses brutes sans pays (« Department of Pediatrics University Hospital Rouen »).
- [x] Arborescences de structures HAL chez scanR (« Institut Pascal, UMR6602, IP, CNRS, UCA… »). Base locale, 2026-11-02 : 3 929 adresses. Le payload brut leur donne un `structId`, donc le normaliseur en tire des structures HAL. Il garde 21 de ces textes comme adresses, tous bruts. La resynchronisation des contributions sources scanR (réhydratation du staging, normalisation avec `--normalize-full`) retire les autres.
- [x] Critères : libellé HAL, avec ou sans adresse postale ; nom exact d'une structure HAL ou d'une organisation ROR ; texte sans virgule et sans nom de pays final (`dc2e61268`). Crochets contenant une période, des lieux ou un nom de structure ; « Nom, Pays » en deux segments (`2a22e8e0f`). « CHU Clermont Ferrand, Clermont Ferrand, France » reste une adresse brute : elle reproduit souvent la signature imprimée.
- [x] Colonne `origin` sur `addresses`. La migration crée la colonne vide, le passage suivant du pipeline la remplit (`dc2e61268`).

### Phase 2 — Indicateurs

- [x] Onglets Adresses de la personne et de la structure : seules les adresses brutes figurent (`b1755062a`).
- [x] Documentation : glossaire, guide d'administration, phase `affiliations`, données.

## Liens

- Convention de signature : <https://www.uca.fr/recherche/science-ouverte-et-publication/politique-de-signature-des-publications>
- Tables : `addresses`, `source_contribution_addresses`, `address_structures`, `hal_structures`, `ror_organizations`, `place_name_forms`.
- Phase `affiliations` : `pipeline/transformation/structures/`.
