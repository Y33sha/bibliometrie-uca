/**
 * Registre des filtres d'une liste. Chaque filtre se déclare une fois ; le registre en dérive l'état initial, les paramètres de la requête, la synchronisation avec l'URL, la configuration des décomptes, les colonnes à afficher et la place du contrôle dans la page.
 */
import type { FacetOption } from '$lib/components/FacetDropdown.svelte';
import type { FacetDef } from '$lib/composables/useFacets.svelte';
import type { FilterDef as UrlFilterDef } from '$lib/composables/useUrlFilters.svelte';
import type { EntityKind } from '$lib/entityLabels';

/** État d'un filtre de présence, par élément : `yes` retient les présents, `no` les absents. */
export type PresenceStates = Record<string, 'all' | 'yes' | 'no'>;

interface BaseFilter {
	/** Identifiant du filtre dans l'état et dans les décomptes. */
	key: string;
	label: string;
	/** Paramètre de la requête, repris comme clé d'URL. */
	param: string;
	/** Rubrique du panneau « Plus de filtres ». Sans rubrique, le contrôle figure dans la barre principale. */
	group?: string;
	/** Valeur imposée par la page : elle remplace la sélection dans la requête, et le contrôle disparaît. */
	fixed?: () => string | null;
	/** Filtre proposé dans cette page. Vrai par défaut. */
	enabled?: () => boolean;
	/** Colonnes affichées quand le filtre est actif au chargement de la page. */
	showColumns?: string[];
}

export interface CheckboxFilter extends BaseFilter {
	control: 'checkbox';
	facet: FacetDef;
	searchable?: boolean;
	tooltip?: string;
	groups?: { label: string; values: string[] }[];
	/** Masque le contrôle tant que sa facette ne propose aucune option. */
	hideWhenEmpty?: boolean;
	/** Écriture de la sélection dans l'URL, quand elle diffère de la liste des valeurs. `defaultValue` n'est pas écrite. */
	url?: { encode: (selected: string[]) => string; decode: (raw: string) => string[]; defaultValue: string };
	/** Corrige une sélection qui vient de changer. */
	normalize?: (selected: string[]) => string[];
}

export interface EntityChoiceFilter extends BaseFilter {
	control: 'entity';
	entity: EntityKind;
}

export interface PresenceFilter extends BaseFilter {
	control: 'presence';
	items: { key: string; label: string }[];
}

export type ListFilter = CheckboxFilter | EntityChoiceFilter | PresenceFilter;

/** Valeurs des filtres, par type de contrôle et par clé. */
export interface FilterValues {
	checkbox: Record<string, string[]>;
	entity: Record<string, string | null>;
	presence: Record<string, PresenceStates>;
}

/** Vide la sélection d'un filtre. */
export function clearValue(filter: ListFilter, values: FilterValues): void {
	if (filter.control === 'checkbox') values.checkbox[filter.key] = [];
	else if (filter.control === 'entity') values.entity[filter.key] = null;
	else values.presence[filter.key] = {};
}

export function initialValues(filters: ListFilter[]): FilterValues {
	const values: FilterValues = { checkbox: {}, entity: {}, presence: {} };
	for (const f of filters) clearValue(f, values);
	return values;
}

/** Filtre proposé dans la page, et que la page ne fixe pas. */
export function isAvailable(filter: ListFilter): boolean {
	return (filter.enabled?.() ?? true) && (filter.fixed?.() ?? null) === null;
}

/** Contrôle à afficher : filtre disponible, avec des options quand le filtre l'exige. */
export function isShown(filter: ListFilter, optionCount: (key: string) => number): boolean {
	if (!isAvailable(filter)) return false;
	return !(filter.control === 'checkbox' && filter.hideWhenEmpty && optionCount(filter.key) === 0);
}

/** Contrôles de la barre principale, puis rubriques du panneau « Plus de filtres », dans l'ordre de déclaration. */
export function filterSections(filters: ListFilter[]): {
	primary: ListFilter[];
	groups: { label: string; filters: ListFilter[] }[];
} {
	const primary: ListFilter[] = [];
	const groups = new Map<string, ListFilter[]>();
	for (const f of filters) {
		if (f.group) groups.set(f.group, [...(groups.get(f.group) ?? []), f]);
		else primary.push(f);
	}
	return { primary, groups: [...groups].map(([label, members]) => ({ label, filters: members })) };
}

/** Sélection d'un filtre de présence sous la forme `hal_yes,wos_no`. */
export function encodePresence(states: PresenceStates): string {
	return Object.entries(states)
		.filter(([, v]) => v === 'yes' || v === 'no')
		.map(([k, v]) => `${k}_${v}`)
		.join(',');
}

export function isActive(filter: ListFilter, values: FilterValues): boolean {
	if (filter.control === 'checkbox') return (values.checkbox[filter.key] ?? []).length > 0;
	if (filter.control === 'entity') return (values.entity[filter.key] ?? null) !== null;
	return encodePresence(values.presence[filter.key] ?? {}) !== '';
}

/** Nombre maximal d'éléments nommés dans le résumé d'une sélection ; au-delà, le dernier devient un décompte. */
const SUMMARY_PARTS = 3;

/** Résumé d'une sélection de cases à cocher. Un groupe entièrement coché est nommé par son libellé. */
export function checkboxSummary(filter: CheckboxFilter, selected: string[], options: FacetOption[]): string {
	const text = new Map(options.map((o) => [o.value, o.text]));
	const parts: string[] = [];
	let rest = selected;
	for (const g of filter.groups ?? []) {
		if (g.values.length && g.values.every((v) => rest.includes(v))) {
			parts.push(g.label);
			rest = rest.filter((v) => !g.values.includes(v));
		}
	}
	for (const v of rest) parts.push(text.get(v) ?? v);
	if (parts.length <= SUMMARY_PARTS) return parts.join(', ');
	return `${parts.slice(0, SUMMARY_PARTS - 1).join(', ')} +${parts.length - SUMMARY_PARTS + 1}`;
}

/** Résumé d'un filtre de présence, sous la forme « avec HAL, sans WoS ». */
export function presenceSummary(filter: PresenceFilter, states: PresenceStates): string {
	return filter.items
		.filter((i) => states[i.key] === 'yes' || states[i.key] === 'no')
		.map((i) => `${states[i.key] === 'yes' ? 'avec' : 'sans'} ${i.label}`)
		.join(', ');
}

/** Valeur d'un filtre dans la requête, ou `null` quand il ne filtre rien. */
function paramValue(filter: ListFilter, values: FilterValues): string | null {
	const fixed = filter.fixed?.() ?? null;
	if (fixed !== null) return fixed;
	if (filter.control === 'checkbox') return (values.checkbox[filter.key] ?? []).join(',') || null;
	if (filter.control === 'entity') return values.entity[filter.key] || null;
	return encodePresence(values.presence[filter.key] ?? {}) || null;
}

export function appendFilterParams(
	filters: ListFilter[],
	values: FilterValues,
	params: URLSearchParams,
): void {
	for (const f of filters) {
		const value = paramValue(f, values);
		if (value !== null) params.set(f.param, value);
	}
}

/** Configuration des décomptes pour `useFacets`, par clé de filtre. */
export function facetDefs(filters: ListFilter[]): Record<string, FacetDef> {
	const defs: Record<string, FacetDef> = {};
	for (const f of filters) if (f.control === 'checkbox') defs[f.key] = f.facet;
	return defs;
}

/** Configuration de l'URL pour `useUrlFilters`, par clé de filtre. */
export function urlFilterDefs(filters: ListFilter[]): Record<string, UrlFilterDef> {
	const defs: Record<string, UrlFilterDef> = {};
	for (const f of filters) {
		if (f.control === 'checkbox') {
			defs[f.key] = f.url
				? { type: 'single', urlKey: f.param, defaultValue: f.url.defaultValue }
				: { type: 'string_array', urlKey: f.param };
		} else if (f.control === 'entity') {
			defs[f.key] = { type: 'single', urlKey: f.param };
		} else {
			defs[f.key] = { type: 'source_states', urlKey: f.param };
		}
	}
	return defs;
}

/** État à écrire dans l'URL, dans la forme qu'attend `useUrlFilters`. */
export function urlState(filters: ListFilter[], values: FilterValues): Record<string, unknown> {
	const state: Record<string, unknown> = {};
	for (const f of filters) {
		if (f.control === 'checkbox') {
			const selected = values.checkbox[f.key] ?? [];
			state[f.key] = f.url ? f.url.encode(selected) : selected;
		} else if (f.control === 'entity') {
			state[f.key] = values.entity[f.key] ?? null;
		} else {
			state[f.key] = values.presence[f.key] ?? {};
		}
	}
	return state;
}

/** Reporte dans `values` les sélections que `useUrlFilters` a lues dans l'URL. */
export function restoreValues(
	filters: ListFilter[],
	restored: Record<string, unknown>,
	values: FilterValues,
): void {
	for (const f of filters) {
		const raw = restored[f.key];
		if (raw == null || raw === '') continue;
		if (f.control === 'checkbox') {
			values.checkbox[f.key] = f.url ? f.url.decode(raw as string) : (raw as string[]);
		} else if (f.control === 'entity') {
			values.entity[f.key] = raw as string;
		} else {
			values.presence[f.key] = raw as PresenceStates;
		}
	}
}

/** Colonnes à afficher pour les filtres actifs proposés dans la page. */
export function activeColumns(filters: ListFilter[], values: FilterValues): string[] {
	const columns = new Set<string>();
	for (const f of filters) {
		if (!f.showColumns || !(f.enabled?.() ?? true) || !isActive(f, values)) continue;
		for (const column of f.showColumns) columns.add(column);
	}
	return [...columns];
}
