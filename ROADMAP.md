# Roadmap transmission DSI

## 1. Sécurité — Bloquant

- [ ] Purger les credentials du repo (rewrite git history ou nouveau repo propre)
Purger les credentials de l'historique git (section 1) — filter-repo sur config/settings.py pour virer les anciens hashes SHA256, la clé WoS, le mot de passe ScanR des commits passés. Mais cette fois on commit avant.

## 2. Résilience pipeline — Bloquant

- [ ] Ajouter retry + backoff exponentiel sur HAL, WoS, ScanR, theses.fr (seul OpenAlex l'a)
- [ ] Alerting sur échec pipeline (email ou webhook)
- [ ] Health check métier : exposer la fraîcheur des données et l'état du dernier run pipeline dans `/api/health`

## 3. Observabilité API — Bloquant pour opérer

- [ ] Ajouter le logging dans tous les routers (seul `addresses.py` utilise le logger aujourd'hui)
Logging dans les routers (section 3) — Ajouter logger = logging.getLogger(__name__) dans chaque router. Mécanique.

- [ ] Logger structuré (JSON) pour permettre l'agrégation
- [ ] Traçabilité admin : loguer qui fait quoi sur les endpoints d'écriture
- [ ] Métriques basiques (temps de réponse, état du pool DB)

## 5. Base de données

- [ ] Documenter le schéma des colonnes JSONB (`meta`, `source_data`, `external_ids`)
- [ ] Ajouter un audit trail pour les opérations destructives (fusions, suppressions)

## 6. Validation pipeline

- [ ] Checks automatiques post-pipeline (comptages, orphelins, anomalies)

---

## A la charge de la DSI

- Authentification CAS (remplace le login admin actuel)
- RBAC (rôles : lecteur, gestionnaire, admin)
- Reverse proxy (nginx) avec headers de sécurité
- Frontend selon la charte DSI (le backend API est prêt)




# Niveau 0 — instrumenter avant de toucher.

Avant toute modif, il te faut un filet : linter configuré (ruff couvre 95% de ce que faisaient flake8+isort+pyupgrade), formateur (ruff format ou black), type checker (mypy ou pyright en mode permissif au début, strict par module ensuite), et surtout des tests qui passent, même minimaux. Sans tests, chaque refacto est un pari. Si la couverture est nulle, la première étape d'audit est d'écrire des tests de caractérisation sur les endpoints/fonctions critiques — ils documentent le comportement actuel, pas le comportement souhaité, et te protègent pendant le reste de l'opération. Ajouter coverage pour voir où tu es aveugle.


# Niveau 1 — architecture et découpage.
Bien plus important que la déduplication. Questions à poser à ton code : y a-t-il une séparation claire entre couche données (accès SQL), couche métier (logique bibliométrique, règles de matching, algorithme pays), couche API (FastAPI routes, sérialisation), et couche présentation (Svelte) ? Les dépendances vont-elles dans un seul sens, ou est-ce que tes routes FastAPI parlent directement à psycopg tout en contenant de la logique métier ? Une route qui fait parsing de requête + SQL brut + règle métier + formatage réponse est un candidat à éclater même si elle n'est dupliquée nulle part. Le critère n'est pas "ce code est-il répété" mais "ce module a-t-il une seule raison de changer" (SRP). Vu ton stack multi-sources (HAL/WoS/OpenAlex/ScanR), la question spécifique : as-tu une couche d'abstraction commune sur les sources, ou chaque source a son propre chemin qui remonte jusqu'à la route ?

# Niveau 2 — frontières et contrats. 
Où sont les entrées externes (requêtes HTTP, réponses d'API tierces, lignes de BDD, fichiers) et sont-elles validées par un modèle Pydantic au point d'entrée, plutôt que baladées en dict[str, Any] à travers trois fonctions ? Les types de retour des fonctions publiques sont-ils annotés ? Les erreurs attendues sont-elles typées (exceptions custom) ou est-ce du except Exception générique ? Ce niveau est souvent plus rentable que la déduplication : un dict mal typé qui circule est une bombe à retardement, dix lignes dupliquées ne le sont pas.

# Niveau 3 — état et effets de bord. 
Les connexions à la BDD sont-elles gérées via un pool et un context manager, ou ouvertes à la volée ? Les transactions sont-elles explicites ? Y a-t-il de la config lue par os.environ dispersée dans le code plutôt que centralisée dans un objet Settings (Pydantic Settings justement) ? Les chemins de fichier sont-ils en dur ou passent-ils par une config ? Les logs sont-ils structurés (loguru, structlog) ou des print survivants ? La gestion d'erreurs remonte-t-elle jusqu'à un handler central qui produit une réponse HTTP propre, ou chaque route fait son propre try/except ?

# Niveau 4 — ce que tu as listé. 
Ta liste arrive ici. Elle est valide mais agis dessus une fois les niveaux précédents stabilisés, sinon tu factorises des choses qui vont être redécoupées. Un ajout à ta liste à ce niveau : complexité cyclomatique et longueur des fonctions. radon cc -s ou ruff avec la règle C901 te sortent les fonctions tordues ; une fonction de 200 lignes avec 6 niveaux d'indentation est un problème de maintenabilité indépendant de toute duplication. Autre ajout : les "magic values" dont tu parles méritent d'être distinguées en deux catégories : (a) vraies constantes métier (codes de statut, seuils, noms de sources) → à centraliser et typer, éventuellement en Enum ; (b) valeurs de configuration (timeouts, tailles de batch, URLs) → à sortir en config, pas en constantes.

# Niveau 5 — dépendances et dette externe.
Les versions sont-elles épinglées (lockfile : uv.lock, poetry.lock, requirements.txt figé) ? Y a-t-il des paquets non utilisés (deptry, pip-audit) ? Des vulnérabilités connues (pip-audit) ? Python est-il sur une version maintenue ? Les migrations BDD sont-elles gérées par un outil (Alembic) ou à la main ?

# Niveau 6 — documentation vivante et DX. 
Ta mention des docstrings entre ici. Élargis à : y a-t-il un README qui permet à toi-dans-deux-ans de remonter l'environnement de dev en 15 minutes ? Un CONTRIBUTING.md ou équivalent qui dit "comment ajouter une nouvelle source de données" ? Un schéma d'archi (ton D2 récent est un bon point de départ) versionné avec le code ? Les endpoints FastAPI ont-ils des descriptions OpenAPI correctes (c'est quasi-gratuit avec Pydantic) ? Un pre-commit hook qui fait tourner ruff+mypy+tests évite la dérive.

# Niveau 7 — Svelte / front. 
Les stores sont-ils clairement séparés de la logique de composant ? Les appels API sont-ils centralisés dans un module client ou dispersés ? Les types TS (si tu utilises TS) sont-ils générés depuis ton OpenAPI plutôt que réécrits à la main ? C'est là que ta ligne "abstraire des composants, centraliser les styles" entre, mais la question de la génération de types depuis le backend est souvent plus rentable que la factorisation de composants.

Ordre concret que je suggère, vu ton contexte :

- Mettre en place linter + formateur + type checker + un filet de tests de caractérisation.
- Cartographier l'architecture actuelle (un diagramme des modules et de qui appelle qui) — D2 encore, tu es équipée.
- Identifier les couches qui fuient (route qui fait du SQL, module data qui connaît HTTP, etc.) et redresser une seule frontière à la fois.
- Typer les frontières (Pydantic partout aux entrées/sorties, Settings pour la config).
- Là tu attaques ta liste : déduplication SQL, constantes, code mort, docstrings, composants front.
- Documentation d'architecture et hooks pre-commit pour verrouiller les acquis.

Un principe transversal : **une PR, un type de changement**. Un commit qui renomme + factorise + change le comportement est inauditable même par soi-même trois mois plus tard. Formatage d'abord (un commit), renommages ensuite, déplacements de code ensuite, changements de comportement en dernier — chaque catégorie dans son propre commit/PR.