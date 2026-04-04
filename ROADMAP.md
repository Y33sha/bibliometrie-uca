# Roadmap — Bibliométrie UCA

Chantiers restants, classés par effort. Consolidation des TODO_LAURA.md et TODO_CLAUDE.md.

## Quick wins (< 1h)

### Suppression colonne raw_orcid (openalex_authorships)
Redondante avec openalex_authors.orcid. Migration SQL + nettoyage des références dans le code.

### Condition excluded = false dans l'onglet identités personnes
Éviter d'afficher des comptes HAL erronés dans l'onglet identités de la page personne. Ajouter `AND NOT excluded` dans la requête du router.

### Ne pas afficher "non applicable" dans les pays
Filtrer le code pays `xx` dans les facettes et l'affichage des pays des publications.

### Authorship source rejetée → rejeter de l'authorship vérité
Quand une authorship source est marquée `excluded = TRUE`, propager vers l'authorship vérité (supprimer ou marquer). Actuellement, elle reste affichée.

### Forme de nom avec zéro authorship → option supprimer
Endpoint DELETE sur person_name_forms quand aucune authorship n'est liée à cette forme. Bouton dans l'interface personne.

### Seed structures UCA
Script SQL avec les structures de base nécessaires au démarrage (UCA, départements, labos). Permet de démarrer sur une base vide sans import manuel.


## Chantiers moyens (quelques heures)

### Automatisation pays des adresses (country_name_forms)
Table `country_name_forms` avec les formes de noms de pays (français, anglais, variantes). Script de parsing des adresses pour détecter les pays automatiquement → `suggested_countries`, validables manuellement. Voir TODO_CLAUDE pour le détail.

### Cron imports + dumps
Automatiser les imports périodiques (hebdomadaires) et les dumps de sauvegarde. Docker cron ou systemd timer.

### ORCID OpenAlex : condition de fiabilité
Importer l'ORCID des openalex_authors seulement quand `display_name` correspond au `raw_author_name` de l'authorship (et pas une initiale). Condition dans normalize_openalex.py.

### Page admin configuration
Externaliser dans une page admin les paramètres de `config/settings.py` (années, collections HAL, périmètre UCA). Table `config` en base, API REST, page Svelte. Voir TODO_CLAUDE pour le détail.

### Tests d'idempotence du pipeline
Vérifier que lancer deux fois chaque phase produit le même résultat. Fixtures + double exécution + compteurs. Voir TODO_CLAUDE pour le détail.

### Type peer_review : auteurs = ceux de l'article reviewé
Les publications de type `peer_review` dans OpenAlex listent les auteurs de l'article reviewé, pas du review. Diagnostiquer et corriger (exclure de la propagation UCA — déjà fait dans build_authorships, mais vérifier l'impact sur les personnes).

### Interface mapping hal_structures → structures
Page admin pour gérer le mapping entre structures HAL et structures canoniques. Actuellement fait en SQL direct.


## Gros chantiers (à planifier)

### Mega-authorships et alignement inter-sources
Publications > 50 auteurs : désalignement des positions entre HAL/OpenAlex/WoS → faux conflits. Table `authorship_alignments` + algorithme de matching par noms. En attendant, exclusion des publis > 50 auteurs du mode "conflit de sources".

### Nouvelles sources
ArXiv, PubMed, ScanR, theses.fr. Chaque source = extraction + normalisation + intégration au pipeline.

### Relations entre publications
Modéliser les relations : est traduction de, est preprint de, fait partie de (chapitre → ouvrage), corrigendum, etc.

### Pages supplémentaires
Sujets, éditeurs, revues (avec liens DOAJ, APC). Évaluer la pertinence avant de développer.

### Uniformisation compatibilité noms (Python vs SQL)
Les fonctions `names_compatible` existent en Python (utils/names.py) et en SQL (admin_person_duplicates.py). Idéalement unifier, mais les requêtes SQL sont plus performantes pour le matching en masse.


## Bugs et bizarreries à investiguer

- openalex répète des auteurs : publi 77832
- claire richard : pourquoi 0 publi UCA sur page admin?
- publi 103567 : structures identifiées sur HAL (UCA, Inserm) → pourquoi?
- personne 57907 : comprendre comment "Damien Boyer" est devenu une forme de nom
- publi 79637 : authorship source rejetée → la rejeter de l'authorship vérité
- trous dans la numérotation des auteurs HAL : diagnostiquer et résoudre
- HAL compte-rendu → type "autre" au lieu d'article
- publications "article" avec source OA et revue inconnue → souvent des preprints
- document dumas : ouvrir sur dumas, pas HAL
- preprints en accès gold → corriger
- authorship supprimée mais publi apparaît toujours (julie gardette)


## Améliorations d'interface (non prioritaires)

- Mémoriser filtres et les rétablir au rechargement
- Rendre les filtres sticky
- Rendre tous les tableaux triables
- Interface pour afficher le staging JSON (pour vérification)
- Différencier interfaces à usage interne vs externe (rôles)
- Groupes de pays (UE, continents) pour la recherche par facettes
- Afficher les abstracts
