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
