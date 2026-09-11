import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';
import { loadProjectEnv } from './project-env.js';

// Fichiers d'environnement du projet (cf. project-env.js), lus sans polluer `process.env` :
// ils font autorité sur les deux variables consommées ici, sans que leur valeur fuite vers
// les processus enfants.
const fileEnv = loadProjectEnv();

// `BASE_PATH` : préfixe de déploiement, les fichiers font autorité (cf. svelte.config.js).
// Doit matcher `paths.base` dans svelte.config.js. Vide par défaut (app à la racine) ;
// en dev, vite strip ce préfixe avant de proxyfier vers le backend.
const basePath = fileEnv.BASE_PATH ?? process.env.BASE_PATH ?? '';

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
	plugins: [sveltekit()],
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
	test: {
		include: ['src/**/*.test.ts', 'project-env.test.ts'],
	}
});
