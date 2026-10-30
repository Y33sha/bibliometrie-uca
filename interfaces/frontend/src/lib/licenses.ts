import { api } from '#lib/api/index.js';
import type { components } from '#lib/api/schema.js';

type EnumOption = components['schemas']['EnumOption'];

let pending: Promise<Record<string, string>> | null = null;

/** Libellés des licences, servis par `GET /api/publications/licenses` et chargés une fois par session. Un échec de chargement autorise un nouvel essai. */
export function licenseLabels(): Promise<Record<string, string>> {
	pending ??= api<EnumOption[]>('/api/publications/licenses')
		.then((options) => Object.fromEntries(options.map((o) => [o.value, o.label_fr])))
		.catch((e) => {
			pending = null;
			throw e;
		});
	return pending;
}

/** Pictogrammes Creative Commons d'une licence : suffixes des classes `fi-brands-*` de la police d'icônes. Les autres licences s'affichent par leur libellé. */
export const LICENSE_ICONS: Record<string, string[]> = {
	'cc-by': ['creative-commons', 'creative-commons-by'],
	'cc-by-sa': ['creative-commons', 'creative-commons-by', 'creative-commons-sa'],
	'cc-by-nd': ['creative-commons', 'creative-commons-by', 'creative-commons-nd'],
	'cc-by-nc': ['creative-commons', 'creative-commons-by', 'creative-commons-nc'],
	'cc-by-nc-sa': ['creative-commons', 'creative-commons-by', 'creative-commons-nc', 'creative-commons-sa'],
	'cc-by-nc-nd': ['creative-commons', 'creative-commons-by', 'creative-commons-nc', 'creative-commons-nd'],
	'public-domain': ['creative-commons-pd'],
};
