import { resolve } from '$app/paths';

/** Chemin absolu (`/api/...`, `/publications`) précédé du préfixe de déploiement. Sert aux chemins que le typage de `resolve` ne couvre pas : ceux de l'API, servie par le backend hors des routes de l'application, et les chemins de route composés à l'exécution. `resolve('')` renvoie le préfixe suivi de `/`. */
export function withBase(path: string): string {
	return resolve('') + path.slice(1);
}
