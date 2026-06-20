import { base } from '$app/paths';
import { halDocUrl, scanrPubUrl } from '$lib/utils';

interface SourceMeta {
	/** Libellé court (badges, liens). */
	label: string;
	/** Logo local — l'appli doit tourner hors ligne (pas de logo distant). */
	icon?: string;
	/** Lien vers la notice d'origine sur le portail de la source. */
	externalUrl: (sourceId: string, oaStatus?: string | null) => string;
}

/**
 * Métadonnées d'affichage par source : libellé, logo et lien externe.
 * Source unique de vérité pour le rendu des sources (composant `SourceTag`,
 * en-tête de publication, listes de doublons…). Ajouter une source = une entrée ici.
 */
export const SOURCES: Record<string, SourceMeta> = {
	hal: { label: 'HAL', icon: `${base}/icons/hal.ico`, externalUrl: (id, oa) => halDocUrl(id, oa) },
	openalex: {
		label: 'OpenAlex',
		icon: `${base}/icons/openalex.png`,
		externalUrl: (id) => `https://openalex.org/${id}`
	},
	scanr: {
		label: 'ScanR',
		icon: `${base}/scanr-icon.svg`,
		externalUrl: (id) => scanrPubUrl(id)
	},
	wos: {
		label: 'WoS',
		icon: `${base}/icons/wos.ico`,
		externalUrl: (id) => `https://www.webofscience.com/wos/woscc/full-record/${id}`
	},
	theses: {
		label: 'theses.fr',
		icon: `${base}/icons/theses.ico`,
		externalUrl: (id) => `https://theses.fr/${id}`
	},
	crossref: {
		label: 'Crossref',
		icon: `${base}/icons/crossref.ico`,
		externalUrl: (id) => `https://doi.org/${id}`
	},
	datacite: {
		label: 'DataCite',
		icon: `${base}/icons/datacite.ico`,
		externalUrl: (id) => `https://doi.org/${id}`
	}
};

/** Ordre d'affichage des sources (regroupement visuel stable). */
export const SOURCE_ORDER = ['hal', 'openalex', 'scanr', 'wos', 'theses', 'crossref', 'datacite'];

/** Libellé d'une source (avec repli sur la clé brute si source inconnue). */
export function sourceLabel(source: string): string {
	return SOURCES[source]?.label ?? source;
}

/** Chemin du logo local d'une source (`undefined` si aucun). */
export function sourceIcon(source: string): string | undefined {
	return SOURCES[source]?.icon;
}

/** Lien externe vers la notice d'origine (`#` si source inconnue). */
export function sourceExternalUrl(
	source: string,
	sourceId: string,
	oaStatus?: string | null
): string {
	return SOURCES[source]?.externalUrl(sourceId, oaStatus) ?? '#';
}
