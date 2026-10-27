import { page } from '$app/state';
import { setQueryParam } from '#lib/url.js';

/**
 * Onglet d'une page à files de triage, gardé dans l'URL sous `?tab=<clé>`.
 *
 * L'onglet `all` (la liste) n'écrit pas de paramètre. Une clé absente de `queues`, ou `enabled` faux (hors session admin), donne `all`.
 */
export function useTabParam<K extends string>(queues: readonly K[], enabled: () => boolean) {
	return {
		get current(): K | 'all' {
			const t = page.url.searchParams.get('tab') as K | null;
			return enabled() && t !== null && queues.includes(t) ? t : 'all';
		},
		select(key: K | 'all') {
			void setQueryParam('tab', key === 'all' ? null : key);
		},
	};
}
