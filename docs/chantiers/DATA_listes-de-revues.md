# Chantier — Listes de revues

## Contexte

Le DOAJ est la seule liste de référence des revues. L'import de son dump CSV (`enrich_serials_from_doaj`) rattache chaque ligne à sa revue par ISSN. La revue reçoit `is_in_doaj`, la ligne nettoyée (`doaj_payload`) et la date de l'import. Le DOAJ classe aussi les revues diamant et type en revue les entrées présentes. La liste des revues a une facette « DOAJ ».

Aucune table ne rattache une revue à une autre liste : revues indexées dans le Web of Science, revues recommandées par la conférence des doyens de médecine et le CNU santé.

Sources gratuites repérées (2026-11-01), conditions d'utilisation non lues :

| Source | Contenu | Accès |
|---|---|---|
| Journal Citation Reports (Clarivate) | Facteur d'impact, quartiles | Abonnement |
| Master Journal List (Clarivate) | Revues de SCIE, SSCI, AHCI, ESCI : titre, ISSN, éditeur | CSV par collection, compte gratuit |
| SCImago | Indicateur SJR, quartile par catégorie, h-index, calculés sur Scopus | CSV libre, usage non commercial en citant la source |
| OpenAlex | `2yr_mean_citedness` (moyenne des citations sur deux ans), h-index | API libre |
| Scopus | Liste des sources, CiteScore | Connexion à Scopus |
| Registre norvégien, erih+ | Niveaux 1 et 2 ; revues de SHS | Liste libre, en citant la source |
| Conférence des doyens de médecine et CNU santé | Environ 3 400 revues jugées non prédatrices | Publiée par la faculté de santé de Sorbonne Université |

## Décisions

- Le DOAJ est une liste parmi d'autres.
- La facette « DOAJ » de la liste des revues devient une facette « Listes » : un sélecteur à trois états par liste (indifférent, présente, absente).

## Phasage

### Phase 1 — Modèle

- [ ] Table des listes, table des entrées avec les informations propres à chaque liste
- [ ] DOAJ en liste : `is_in_doaj` et `doaj_payload` lus dans ses entrées

### Phase 2 — Interface

- [ ] Facette « Listes » de la liste des revues
- [ ] Listes d'une revue sur sa page

### Phase 3 — Listes

- [ ] Choix des listes importées et de leur source (question 1)

## Questions ouvertes

1. Source de chaque liste : fichier publié par l'organisme, API ou saisie dans l'administration. Accès au Journal Citation Reports après la résiliation de l'abonnement au Web of Science.
2. Mise à jour d'une liste : import complet qui la remplace, ajouts et retraits datés, ou liste posée une fois.
3. Rattachement d'une entrée à une revue : par ISSN, la revue se retrouvant par `serial_issns`, ou par titre à défaut. Sort des entrées sans revue dans le référentiel.
4. Un quartile se calcule par catégorie disciplinaire : garder chaque catégorie avec son quartile, ou le meilleur quartile seul.
