# Roadmap transmission DSI

## 1. Sécurité — Bloquant

- [ ] Purger les credentials du repo (rewrite git history ou nouveau repo propre)
- [ ] Passer tous les secrets en variables d'environnement (`.env` en `.gitignore`, `.env.example` versionné)
- [ ] Auditer et corriger les injections SQL par f-string (routers : addresses, admin_duplicates, structures, feedback, journals)
- [ ] Remplacer SHA256 par bcrypt pour le hash admin, générer un vrai session secret
- [ ] Rendre CORS configurable par environnement (origins, methods, headers)

## 2. Résilience pipeline — Bloquant

- [ ] Ajouter retry + backoff exponentiel sur HAL, WoS, ScanR, theses.fr (seul OpenAlex l'a)
- [ ] Alerting sur échec pipeline (email ou webhook)
- [ ] Health check métier : exposer la fraîcheur des données et l'état du dernier run pipeline dans `/api/health`

## 3. Observabilité API — Bloquant pour opérer

- [ ] Ajouter le logging dans tous les routers (seul `addresses.py` utilise le logger aujourd'hui)
- [ ] Logger structuré (JSON) pour permettre l'agrégation
- [ ] Traçabilité admin : loguer qui fait quoi sur les endpoints d'écriture
- [ ] Métriques basiques (temps de réponse, état du pool DB)

## 4. Qualité code backend

- [ ] Remplacer les `body: dict` par des modèles Pydantic sur les endpoints POST/PUT
- [ ] Remplacer les `sys.path.insert` par un packaging propre
- [ ] Ajouter un middleware catch-all pour les erreurs inattendues (JSON 500 au lieu de HTML)

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
