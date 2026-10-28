// Établissement servi par l'instance : nom, structures racines du périmètre des personnes, titre et teinte de l'application.
import { api } from '#lib/api/index.js';
import type { components } from '#lib/api/schema.js';

type InstitutionOut = components['schemas']['InstitutionOut'];

export const institution = $state({
	name: '',
	rootStructureIds: [] as number[],
	title: null as string | null,
	brandHue: null as number | null,
});

/** Affiche l'interface dans la teinte `hue` (angle OKLCH en degrés), sans l'enregistrer. */
export function previewBrandHue(hue: number): void {
	document.documentElement.style.setProperty('--brand-hue', String(hue));
}

/** Retient `hue` comme teinte de l'établissement et l'applique. Le navigateur la garde pour l'appliquer dès l'ouverture suivante (`static/brand-hue.js`). */
export function applyBrandHue(hue: number): void {
	institution.brandHue = hue;
	previewBrandHue(hue);
	try {
		localStorage.setItem('brand-hue', String(hue));
	} catch {
		// Stockage inaccessible : la teinte s'applique au chargement de l'établissement.
	}
}

let loading: Promise<void> | null = null;

/** Charge l'établissement une seule fois. Un échec laisse le nom vide, et l'appel suivant réessaie. */
export function loadInstitution(): Promise<void> {
	loading ??= api<InstitutionOut>('/api/config/institution')
		.then((data) => {
			institution.name = data.name;
			institution.rootStructureIds = data.root_structure_ids;
			institution.title = data.title;
			applyBrandHue(data.brand_hue);
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
