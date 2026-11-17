import { asset } from '$app/paths';
import { apiOnce } from '#lib/api/index.js';
import type { components } from '#lib/api/schema.js';
import type { CreativeCommonsGlyph } from '#lib/creativeCommonsIcons.js';

type EnumOption = components['schemas']['EnumOption'];

/** Libellés des licences, servis par `GET /api/publications/licenses`. */
export function licenseLabels(): Promise<Record<string, string>> {
	return apiOnce<EnumOption[]>('/api/publications/licenses').then((options) =>
		Object.fromEntries(options.map((o) => [o.value, o.label_fr])),
	);
}

/** Pictogramme d'une licence : suite de pictogrammes Creative Commons (`glyphs`), ou logo local (`image`). Les autres licences s'affichent par leur libellé. */
export type LicenseIcon = { glyphs: CreativeCommonsGlyph[] } | { image: string };

export const LICENSE_ICONS: Record<string, LicenseIcon> = {
	'cc-by': { glyphs: ['cc', 'by'] },
	'cc-by-sa': { glyphs: ['cc', 'by', 'sa'] },
	'cc-by-nd': { glyphs: ['cc', 'by', 'nd'] },
	'cc-by-nc': { glyphs: ['cc', 'by', 'nc'] },
	'cc-by-nc-sa': { glyphs: ['cc', 'by', 'nc', 'sa'] },
	'cc-by-nc-nd': { glyphs: ['cc', 'by', 'nc', 'nd'] },
	'public-domain': { glyphs: ['pd'] },
	'licence-ouverte': { image: asset('icons/licence-ouverte.svg') },
};
