// Établissement servi par l'instance : nom, structures racines du périmètre des personnes et titre de l'application.
import { api } from '#lib/api/index.js';
import type { components } from '#lib/api/schema.js';

type InstitutionOut = components['schemas']['InstitutionOut'];

export const institution = $state({ name: '', rootStructureIds: [] as number[], title: null as string | null });

let loading: Promise<void> | null = null;

/** Charge l'établissement une seule fois. Un échec laisse le nom vide, et l'appel suivant réessaie. */
export function loadInstitution(): Promise<void> {
	loading ??= api<InstitutionOut>('/api/config/institution')
		.then((data) => {
			institution.name = data.name;
			institution.rootStructureIds = data.root_structure_ids;
			institution.title = data.title;
		})
		.catch(() => {
			loading = null;
		});
	return loading;
}

/** Titre généré : « Bibliométrie », suivi du nom de l'établissement une fois chargé. */
export function defaultSiteTitle(): string {
	return institution.name ? `Bibliométrie ${institution.name}` : 'Bibliométrie';
}

/** Titre du site : le titre configuré, à défaut le titre généré. */
export function siteTitle(): string {
	return institution.title || defaultSiteTitle();
}

/** Titre de page : libellé de la page, puis titre du site. */
export function pageTitle(label: string): string {
	return `${label} — ${siteTitle()}`;
}
