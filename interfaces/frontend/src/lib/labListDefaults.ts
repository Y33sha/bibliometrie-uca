// Sélection par défaut de la liste des labos : types de structure configurés comme laboratoires, et périmètre des personnes.
import { api } from '#lib/api/index.js';
import type { components } from '#lib/api/schema.js';

type Perimeter = components['schemas']['PerimeterOut'];
type ConfigItem = components['schemas']['ConfigItem'];

export interface LabListDefaults {
	/** Types de structure retenus comme laboratoires (`laboratory_types`), `labo` à défaut. */
	types: string[];
	/** Identifiant du périmètre des personnes, en sélection : vide sans périmètre des personnes. */
	perimeters: string[];
}

/** Charge la sélection par défaut de la liste des labos. */
export async function labListDefaults(): Promise<LabListDefaults> {
	const [config, perimeters] = await Promise.all([api<ConfigItem[]>('/api/config'), api<Perimeter[]>('/api/perimeters')]);
	const persons = perimeters.find((p) => p.is_persons);
	return {
		types: (config.find((c) => c.key === 'laboratory_types')?.value ?? ['labo']) as string[],
		perimeters: persons ? [String(persons.id)] : [],
	};
}
