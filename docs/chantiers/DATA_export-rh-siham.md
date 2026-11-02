# Chantier — Export RH SIHAM : matricule, périodes de présence, laboratoires

## Contexte

`interfaces/cli/imports/import_persons.py` importe les personnes d'un export RH SIHAM. Chaque ligne crée une personne et sa fiche `hr_records`, sauf doublon : même nom normalisé, même service, même fonction. Une personne a une seule fiche : email, fonction (`role_title`), service (`department_name`), dates de début et de fin. Ces dates bornent le périmètre par identifiant fort (`hr_record_source_contributions`, dans `infrastructure/sql_fragments.py`). La liste des personnes a une facette service et une facette fonction.

L'export du 2025-12-15 a une ligne par agent : matricule, nom, prénom, email, composante, corps ou statut, date de début dans le corps. Il couvre les enseignants et enseignants-chercheurs.

L'export du 2026-11-02 couvre une fenêtre d'observation, du 2025-12-15 au 2026-11-02. Colonnes : matricule, nom, prénom, sexe, catégorie (`ENSEIG` ou `BIATSS`), statut, corps, grade, email et deux affectations datées :

- l'affectation principale, à une composante ;
- la répartition organisationnelle, à un laboratoire.

Les dates des deux affectations diffèrent sur 74 lignes.

### Mesures du 2026-11-02

- 2 555 lignes, 2 075 matricules. 399 matricules ont plusieurs lignes, jusqu'à 6. Les lignes successives d'un agent sont souvent des renouvellements de contrat contigus, aux attributs identiques.
- Catégorie : 2 020 lignes `ENSEIG`, 534 lignes `BIATSS`.
- 1 547 matricules sont présents dans les deux exports. 528 sont présents seulement dans l'export de novembre, en majorité `BIATSS`. 99 sont présents seulement dans l'export de décembre.
- La répartition organisationnelle compte 48 libellés abrégés. Certains laboratoires ont plusieurs libellés, suffixés (` - Sciences`, ` - SVSAE`…). D'autres libellés désignent des laboratoires extérieurs ou des services.

## Décisions

- Le matricule SIHAM est une colonne de `hr_records`.
- Les périodes de présence sont dans une table dédiée, plusieurs par personne.
- Le lien personne-laboratoire est dans une table dédiée, rattachée à `structures`.
- La catégorie de personnel est une colonne et une facette de la liste des personnes.

## Phasage

### Phase 1 — Schéma

- [ ] `hr_records` : matricule SIHAM unique, catégorie de personnel, email, date d'export.
- [ ] Table des périodes de présence : personne, début, fin, statut, corps, grade, composante.
- [ ] Table des affectations aux laboratoires : personne, structure, début, fin.
- [ ] Migration des fiches existantes : une période par fiche, depuis `role_title`, `department_name` et les dates. Suppression de ces colonnes de `hr_records`.

### Phase 2 — Import

- [ ] Lecture du format SIHAM : titre et fenêtre d'observation sur les deux premières lignes, en-têtes sur la troisième.
- [ ] Rattachement par matricule : un agent présent en base est mis à jour, sans création de personne.
- [ ] Rattachement des fiches sans matricule, par nom et email, à l'import de l'export de décembre.
- [ ] Fusion des périodes contiguës aux attributs identiques.
- [ ] Correspondance des libellés de laboratoire avec `structures`. L'import liste les libellés sans correspondance.
- [ ] Remplacement des périodes et affectations d'un agent comprises dans la fenêtre d'observation. Les périodes antérieures sont conservées.

### Phase 3 — Consommateurs

- [ ] Années de présence du périmètre calculées depuis les périodes.
- [ ] `person_search`, purge des personnes, fusion de personnes (`_merge.py`) : lecture des tables des périodes et des affectations.
- [ ] Liste des personnes : facettes catégorie, laboratoire, corps.
- [ ] Fiche personne : périodes de présence et laboratoires.

### Phase 4 — Documentation

- [ ] Mise à jour de la documentation de l'import RH et du périmètre.

## Questions ouvertes

- L'absence d'un matricule de l'export de décembre dans l'export de novembre vaut-elle départ ? Sur ces 99 matricules, 54 sont des CCU-AH et 76 ont une fin de contrat postérieure au 2025-12-15.
- Le sexe est présent dans l'export. Le stocker ou non.
- Les affectations aux laboratoires alimentent-elles le périmètre ou l'affiliation des contributions ?
