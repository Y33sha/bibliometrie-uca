// Fichiers d'environnement du projet, lus par la configuration de SvelteKit et de vite.
//
// Le `.env` racine est lu s'il existe : le conteneur frontend reçoit seulement
// `interfaces/frontend`, sans lui. Quand `BIBLIO_INSTANCE` désigne une instance,
// `instances/<nom>/instance.env` prime sur le `.env` racine, et son absence est une erreur.
// Le backend applique la même règle (`infrastructure/__init__.py`).
import { parse } from 'dotenv';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const PROJECT_ROOT = fileURLToPath(new URL('../../', import.meta.url));

/**
 * Variables du `.env` racine, surchargées par celles du fichier de l'instance.
 * @param {Record<string, string | undefined>} [environ] environnement où lire `BIBLIO_INSTANCE`
 * @param {string} [root] racine du dépôt
 * @returns {Record<string, string>}
 */
export function loadProjectEnv(environ = process.env, root = PROJECT_ROOT) {
	const rootEnv = join(root, '.env');
	const values = existsSync(rootEnv) ? parse(readFileSync(rootEnv)) : {};
	const instance = (environ.BIBLIO_INSTANCE ?? '').trim();
	if (instance) {
		const instanceEnv = join(root, 'instances', instance, 'instance.env');
		if (!existsSync(instanceEnv)) {
			throw new Error(`BIBLIO_INSTANCE=${instance} : fichier ${instanceEnv} absent`);
		}
		Object.assign(values, parse(readFileSync(instanceEnv)));
	}
	return values;
}
