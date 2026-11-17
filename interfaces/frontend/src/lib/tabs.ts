import { paramsToQuery } from '#lib/utils.js';

export interface TabDef {
	id: string;
	label: string;
	/** Nombre d'éléments de l'onglet, affiché à côté du libellé. */
	count?: number;
}

/** Renvoie l'onglet désigné par le paramètre `tab` de l'URL s'il figure parmi `tabs`, sinon le premier onglet. */
export function activeTabId(tabs: TabDef[], params: Pick<URLSearchParams, 'get'>): string {
	const t = params.get('tab');
	return t && tabs.some((tab) => tab.id === t) ? t : (tabs[0]?.id ?? '');
}

/** Onglet de la page courante, avec ses paramètres d'URL : filtres, vue, réglages. */
export interface TabLink {
	tab: string;
	params?: Record<string, string>;
}

/** Lien vers un onglet de la page courante : une requête seule (`?tab=…`), sans chemin ni hôte. */
export function tabHref({ tab, params = {} }: TabLink): string {
	return '?' + paramsToQuery(new URLSearchParams({ tab, ...params }));
}
