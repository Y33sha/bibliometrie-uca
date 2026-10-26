import { setQueryParam } from '#lib/url.js';

/** Page demandée au-delà de la dernière page : la liste a rétréci, par exemple après le traitement de sa dernière page. */
export function isPageOutOfRange({ page, pages }: { page: number; pages: number }): boolean {
	return page > 1 && page > pages;
}

/** Retire de l'URL courante le paramètre de page `key`, sans ajouter d'entrée à l'historique. */
export function dropPageParam(key = 'page'): void {
	if (typeof window === 'undefined') return;
	if (!new URLSearchParams(window.location.search).has(key)) return;
	void setQueryParam(key, null);
}
