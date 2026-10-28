import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defaultClientConditions } from 'vite';
import { defineConfig } from 'vitest/config';
import { csp } from './csp.js';
import { loadProjectEnv } from './project-env.js';

// Fichiers d'environnement du projet (cf. project-env.js), lus sans polluer `process.env` :
// ils font autorité sur les variables consommées ici, sans que leur valeur fuite vers
// les processus enfants. Ils priment aussi sur une valeur que l'environnement injecte déjà
// (cas de l'extension Python `useEnvFile`, dont la valeur est par ailleurs corrompue par la
// conversion de chemin POSIX→Windows de Git Bash).
const fileEnv = loadProjectEnv();

// `BASE_PATH` : préfixe de déploiement (cf. ROOT_PATH côté backend), lu au build et en dev.
// Vide par défaut → app servie à la racine (cas du dépôt cloné lancé via `docker compose`).
// Un sous-chemin (ex. `/bibliometrie`) sert un déploiement derrière un reverse-proxy. En dev,
// vite retire ce préfixe avant de transmettre les requêtes au backend.
const basePathBrut = fileEnv.BASE_PATH ?? process.env.BASE_PATH ?? '';
if (basePathBrut !== '' && !basePathBrut.startsWith('/')) {
	throw new Error(`BASE_PATH est vide ou commence par « / » ; reçu : « ${basePathBrut} »`);
}
// Le contrôle ci-dessus établit la forme que le typage de SvelteKit exige du préfixe.
const basePath = basePathBrut as '' | `/${string}`;

// `API_TARGET` : cible du proxy, les fichiers font autorité comme pour `BASE_PATH`. Un
// environnement peut en porter une valeur périmée — VSCode injecte le `.env` dans ses
// terminaux et un terminal ouvert avant une modification du fichier en garde l'état
// antérieur —, qui masquerait en silence la valeur du fichier et dirigerait le proxy
// vers un backend qui n'est pas celui du projet.
// Le conteneur frontend ne reçoit que `interfaces/frontend` : le `.env` racine y est
// absent, et la variable que docker-compose injecte (`http://backend:8000`) s'applique.
// Sans `API_TARGET`, la cible se déduit de `API_PORT`, port de l'API lancée par `start.sh`
// (8000 par défaut, comme dans `infrastructure/settings.py`).
const apiPort = fileEnv.API_PORT ?? process.env.API_PORT ?? '8000';
const apiTarget = fileEnv.API_TARGET || process.env.API_TARGET || `http://127.0.0.1:${apiPort}`;

// `FRONT_PORT` : port du serveur vite. Un port occupé est une erreur (`strictPort`) : vite en
// prendrait sinon un autre, et l'adresse de l'instance changerait.
const frontPort = Number(fileEnv.FRONT_PORT ?? process.env.FRONT_PORT ?? 5173);

export default defineConfig({
	plugins: [
		sveltekit({
			// adapter-static : la SPA (ssr=false) est servie en fichiers statiques par
			// FastAPI (cf. interfaces/api/spa.py). `fallback` : les routes non prérendues
			// retombent sur index.html (routage client-side).
			adapter: adapter({ fallback: 'index.html' }),
			paths: { base: basePath },
			csp
		})
	],
	server: {
		port: frontPort,
		strictPort: true,
		proxy: {
			[`${basePath}/api`]: {
				target: apiTarget,
				rewrite: (path: string) => path.replace(new RegExp(`^${basePath}`), '')
			}
		}
	},
	// Sous vitest, Svelte résout sa version navigateur : les tests de composants appellent `mount`.
	resolve: process.env.VITEST ? { conditions: ['browser', ...defaultClientConditions] } : undefined,
	test: {
		include: ['src/**/*.test.ts', 'project-env.test.ts'],
	}
});
