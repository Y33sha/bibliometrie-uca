import { page } from '$app/state';
import { setQueryParam } from '#lib/url.js';

/**
 * Volet d'une entité, ouvert tant que `?<param>=<id>` figure dans l'URL.
 *
 * `enabled` faux garde le volet fermé, par exemple hors session admin.
 */
export function useDrawerParam(param: string, enabled: () => boolean) {
	return {
		get id(): number | null {
			return enabled() ? Number(page.url.searchParams.get(param)) || null : null;
		},
		open(id: number | null) {
			void setQueryParam(param, id === null ? null : String(id));
		},
	};
}
