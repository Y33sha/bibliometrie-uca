import { goto } from '$app/navigation';

import { paramsToQuery } from '#lib/utils.js';

/**
 * Remplace la query de l'URL de la page `path` (préfixe de déploiement compris), sans ajouter d'entrée à l'historique. Défilement, focus et ancre restent en place.
 *
 * `goto` synchronise l'historique, `page` et le bfcache : au retour arrière, l'URL et l'état restauré de la page concordent. L'appel est sans effet si la page courante n'est plus `path`, cas d'un appel postérieur à un chargement asynchrone pendant lequel l'utilisateur a changé de page.
 */
export function replaceQuery(path: string, params: URLSearchParams): Promise<void> {
	if (typeof window !== 'undefined' && window.location.pathname !== path) return Promise.resolve();
	const qs = paramsToQuery(params);
	const hash = typeof window !== 'undefined' ? window.location.hash : '';
	return goto(path + (qs ? '?' + qs : '') + hash, { replace: true, reset: false });
}

/** Pose le paramètre `key` de l'URL courante, ou le retire quand `value` est `null`. */
export function setQueryParam(key: string, value: string | null): Promise<void> {
	const params = new URLSearchParams(window.location.search);
	if (value === null) params.delete(key);
	else params.set(key, value);
	return replaceQuery(window.location.pathname, params);
}
