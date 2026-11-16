import { asset } from '$app/paths';
import { apiOnce } from '#lib/api/index.js';
import type { components } from '#lib/api/schema.js';

type EnumOption = components['schemas']['EnumOption'];

/** Libellés des licences, servis par `GET /api/publications/licenses`. */
export function licenseLabels(): Promise<Record<string, string>> {
	return apiOnce<EnumOption[]>('/api/publications/licenses').then((options) =>
		Object.fromEntries(options.map((o) => [o.value, o.label_fr])),
	);
}

/** Pictogramme d'une licence : suffixes des classes `fi-brands-*` de la police d'icônes (`glyphs`), ou logo local (`image`). Les autres licences s'affichent par leur libellé. */
export type LicenseIcon = { glyphs: string[] } | { image: string };

export const LICENSE_ICONS: Record<string, LicenseIcon> = {
	'cc-by': { glyphs: ['creative-commons', 'creative-commons-by'] },
	'cc-by-sa': { glyphs: ['creative-commons', 'creative-commons-by', 'creative-commons-sa'] },
	'cc-by-nd': { glyphs: ['creative-commons', 'creative-commons-by', 'creative-commons-nd'] },
	'cc-by-nc': { glyphs: ['creative-commons', 'creative-commons-by', 'creative-commons-nc'] },
	'cc-by-nc-sa': { glyphs: ['creative-commons', 'creative-commons-by', 'creative-commons-nc', 'creative-commons-sa'] },
	'cc-by-nc-nd': { glyphs: ['creative-commons', 'creative-commons-by', 'creative-commons-nc', 'creative-commons-nd'] },
	'public-domain': { glyphs: ['creative-commons-pd'] },
	'licence-ouverte': { image: asset('icons/licence-ouverte.svg') },
};
