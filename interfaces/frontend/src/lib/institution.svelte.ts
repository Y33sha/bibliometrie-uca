// Établissement servi par l'instance : nom et structures racines du périmètre des personnes.
import { api } from '$lib/api';
import type { components } from '$lib/api/schema';

type InstitutionOut = components['schemas']['InstitutionOut'];

export const institution = $state({ name: '', rootStructureIds: [] as number[] });

let loading: Promise<void> | null = null;

/** Charge l'établissement une seule fois. Un échec laisse le nom vide, et l'appel suivant réessaie. */
export function loadInstitution(): Promise<void> {
	loading ??= api<InstitutionOut>('/api/config/institution')
		.then((data) => {
			institution.name = data.name;
			institution.rootStructureIds = data.root_structure_ids;
		})
		.catch(() => {
			loading = null;
		});
	return loading;
}

/** Titre du site : « Bibliométrie », suivi du nom de l'établissement une fois chargé. */
export function siteTitle(): string {
	return institution.name ? `Bibliométrie ${institution.name}` : 'Bibliométrie';
}

/** Titre de page : libellé de la page, puis titre du site. */
export function pageTitle(label: string): string {
	return `${label} — ${siteTitle()}`;
}
