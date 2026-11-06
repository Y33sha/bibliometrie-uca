/**
 * Registre des filtres d'une liste. Chaque filtre se déclare une fois ; le registre en dérive l'état initial, les paramètres de la requête, la synchronisation avec l'URL, la configuration des décomptes, les colonnes à afficher et la rubrique du filtre dans le panneau des filtres.
 */
import type { FacetOption } from '#lib/components/FacetDropdown.svelte';
import type { PresenceItem } from '#lib/components/filters/PresenceOptions.svelte';
import type { FacetDef } from '#lib/composables/useFacets.svelte.js';
import type { FilterDef as UrlFilterDef } from '#lib/composables/useUrlFilters.svelte.js';
import type { EntityKind } from '#lib/entityLabels.js';

/** État d'un filtre de présence, par élément : `yes` retient les présents, `no` les absents. */
export type PresenceStates = Record<string, 'all' | 'yes' | 'no'>;

interface BaseFilter {
	/** Identifiant du filtre dans l'état et dans les décomptes. */
	key: string;
	label: string;
	/** Paramètre de la requête, repris comme clé d'URL. */
	param: string;
	/** Clé de la rubrique du filtre dans le panneau des filtres (`FilterGroup`). */
	group: string;
	/** Texte d'aide, au survol du nom du filtre. */
	tooltip?: string;
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
	groups?: { label: string; values: string[] }[];
	/** Valeurs entières ordonnées (années) : la sélection est un intervalle, choisi par ses bornes. */
	range?: boolean;
	/** Corrige une sélection qui vient de changer. */
	normalize?: (selected: string[]) => string[];
	/** Sélection à l'ouverture de la page. L'URL omet cette sélection ; une sélection vidée s'y écrit `all`. */
	defaultSelection?: () => string[];
	/** Valeur du paramètre de la requête pour une sélection, quand elle diffère des valeurs jointes par des virgules ; `null` pour ne pas filtrer. */
	serialize?: (selected: string[]) => string | null;
}

export interface EntityChoiceFilter extends BaseFilter {
	control: 'entity';
	entity: EntityKind;
	/** Cases à cocher : plusieurs entités, retenues si l'une au moins porte la publication. Sinon, un seul choix. */
	multiple?: boolean;
}

export interface PresenceFilter extends BaseFilter {
	control: 'presence';
	/** Éléments du filtre. Des éléments servis par l'API se déclarent par un getter. */
	items: PresenceItem[];
	/** Un paramètre de requête par élément (`has_orcid=yes`), au lieu du paramètre commun `param` (`hal_yes,wos_no`). `param` reste la clé d'URL. */
	itemParams?: Record<string, string>;
	/** Paramètre des niveaux cochés des éléments (`fnege-1,norway-2`), repris comme clé d'URL. */
	levelsParam?: string;
}

/** Jeton d'URL d'une sélection vidée, pour un filtre qui a une sélection par défaut. */
export const ALL_TOKEN = 'all';

export type ListFilter = CheckboxFilter | EntityChoiceFilter | PresenceFilter;

/** Rubrique du panneau des filtres. Une rubrique rassemble les filtres qui portent sur une même entité : la publication, ses affiliations, sa revue, ses auteurs… */
export interface FilterGroup {
	key: string;
	label: string;
}

/** Valeurs des filtres, par type de contrôle et par clé. Un filtre d'entité porte des ids : un au plus en choix simple. */
export interface FilterValues {
	checkbox: Record<string, string[]>;
	entity: Record<string, string[]>;
	presence: Record<string, PresenceStates>;
	/** Niveaux cochés d'un filtre de présence, tous éléments confondus. */
	levels: Record<string, string[]>;
}

/** Vide la sélection d'un filtre. */
export function clearValue(filter: ListFilter, values: FilterValues): void {
	if (filter.control === 'checkbox') values.checkbox[filter.key] = [];
	else if (filter.control === 'entity') values.entity[filter.key] = [];
	else {
		values.presence[filter.key] = {};
		values.levels[filter.key] = [];
	}
}

/** Valeurs à l'ouverture de la page : la sélection par défaut de chaque filtre, sinon une sélection vide. */
export function initialValues(filters: ListFilter[]): FilterValues {
	const values: FilterValues = { checkbox: {}, entity: {}, presence: {}, levels: {} };
	for (const f of filters) {
		clearValue(f, values);
		if (f.control === 'checkbox' && f.defaultSelection) values.checkbox[f.key] = f.defaultSelection();
	}
	return values;
}

/** Filtre proposé dans la page, et que la page ne fixe pas. */
export function isAvailable(filter: ListFilter): boolean {
	return (filter.enabled?.() ?? true) && (filter.fixed?.() ?? null) === null;
}

/** Décomptes d'un élément de filtre de présence. */
export type PresenceCounts = Record<string, { yes: number; no: number }>;

/** Élément de présence qui départage les publications : présent dans certaines, absent d'autres. Sans décompte connu, l'élément est réputé départager. */
export function discriminates(counts: { yes: number; no: number } | undefined): boolean {
	return !counts || (counts.yes > 0 && counts.no > 0);
}

/**
 * Filtre à afficher : filtre disponible et utile. Une case à cocher est utile quand une option au moins a un décompte non nul ; un filtre de présence, quand un de ses éléments départage les publications. Un filtre actif reste affiché, pour être retiré.
 *
 * `nonZeroOptions` renvoie le nombre d'options de décompte non nul d'une case à cocher.
 */
export function isShown(
	filter: ListFilter,
	values: FilterValues,
	nonZeroOptions: (key: string) => number,
	presenceCounts: PresenceCounts,
): boolean {
	if (!isAvailable(filter)) return false;
	if (isActive(filter, values)) return true;
	if (filter.control === 'checkbox') return nonZeroOptions(filter.key) > 0;
	if (filter.control === 'presence') return filter.items.some((i) => discriminates(presenceCounts[i.key]));
	return true;
}

/** Filtres de chaque rubrique, dans l'ordre des rubriques puis dans l'ordre de déclaration des filtres. Une rubrique sans filtre est omise. Un filtre dont la rubrique est inconnue lève une erreur. */
export function filterGroups(
	filters: ListFilter[],
	groups: readonly FilterGroup[],
): { group: FilterGroup; filters: ListFilter[] }[] {
	for (const f of filters) {
		if (!groups.some((g) => g.key === f.group)) throw new Error(`Rubrique inconnue pour le filtre ${f.key} : ${f.group}`);
	}
	return groups
		.map((group) => ({ group, filters: filters.filter((f) => f.group === group.key) }))
		.filter((g) => g.filters.length);
}

/** Nombre de filtres actifs proposés dans la page. */
export function activeCount(filters: ListFilter[], values: FilterValues): number {
	return filters.filter((f) => isAvailable(f) && isActive(f, values)).length;
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
	if (filter.control === 'entity') return (values.entity[filter.key] ?? []).length > 0;
	return encodePresence(values.presence[filter.key] ?? {}) !== '' || (values.levels[filter.key] ?? []).length > 0;
}

/** Nombre maximal d'éléments nommés dans le résumé d'une sélection ; au-delà, le dernier devient un décompte. */
const SUMMARY_PARTS = 3;

/** Résumé d'une liste de libellés, pour la barre des filtres actifs. */
export function summarizeParts(parts: string[]): string {
	if (parts.length <= SUMMARY_PARTS) return parts.join(', ');
	return `${parts.slice(0, SUMMARY_PARTS - 1).join(', ')} +${parts.length - SUMMARY_PARTS + 1}`;
}

/** Bornes d'une sélection d'entiers consécutifs, ou `null` quand la sélection n'est pas un intervalle. */
export function rangeBounds(selected: string[]): [number, number] | null {
	const years = selected.map(Number).sort((a, b) => a - b);
	if (!years.length || years.some((y) => !Number.isInteger(y))) return null;
	const [first, last] = [years[0], years[years.length - 1]];
	return last - first + 1 === new Set(years).size ? [first, last] : null;
}

/**
 * Bornes de la plage qui concentre les décomptes. À chaque bout, les valeurs qui réunissent ensemble moins de `share` du total sont écartées.
 *
 * `counts` : paires (valeur, décompte), triées par valeur croissante, non vides.
 */
export function coreRange(counts: [number, number][], share = 0.01): [number, number] {
	const threshold = share * counts.reduce((sum, [, c]) => sum + c, 0);
	let lo = 0;
	for (let cumulated = counts[0][1]; cumulated < threshold && lo < counts.length - 1; cumulated += counts[++lo][1]);
	let hi = counts.length - 1;
	for (let cumulated = counts[hi][1]; cumulated < threshold && hi > lo; cumulated += counts[--hi][1]);
	return [counts[lo][0], counts[hi][0]];
}

/** Entiers de `from` à `to`, bornes comprises, en sélection. */
export function rangeSelection(from: number, to: number): string[] {
	return Array.from({ length: to - from + 1 }, (_, i) => String(from + i));
}

/** Résumé d'un intervalle : « Jusqu'à 2025 » quand il part de la première valeur des options, « Depuis 2021 » quand il va jusqu'à la dernière, sinon ses bornes. */
export function rangeSummary([from, to]: [number, number], options: FacetOption[]): string {
	const values = options.filter((o) => o.count).map((o) => Number(o.value));
	if (from === to) return String(from);
	if (values.length && from <= Math.min(...values)) return `Jusqu'à ${to}`;
	if (values.length && to >= Math.max(...values)) return `Depuis ${from}`;
	return `${from}–${to}`;
}

/** Résumé d'une sélection de cases à cocher. Un groupe entièrement coché est nommé par son libellé ; un intervalle, par `rangeSummary`. */
export function checkboxSummary(filter: CheckboxFilter, selected: string[], options: FacetOption[]): string {
	const bounds = filter.range ? rangeBounds(selected) : null;
	if (bounds) return rangeSummary(bounds, options);
	const text = new Map(options.map((o) => [o.value, o.text]));
	const parts: string[] = [];
	let rest = selected;
	for (const g of filter.groups ?? []) {
		if (g.values.length && g.values.every((v) => rest.includes(v))) {
			parts.push(g.label);
			rest = rest.filter((v) => !g.values.includes(v));
		}
	}
	// Options pas encore chargées : « … » à la place de la valeur brute (un identifiant).
	for (const v of rest) parts.push(text.get(v) ?? (options.length ? v : '…'));
	return summarizeParts(parts);
}

/** Résumé d'un filtre de présence, sous la forme « avec HAL, sans WoS ». Un élément à niveaux cochés se résume par ses niveaux, sous la forme « FNEGE rang 1 ou rang 2 ». */
export function presenceSummary(filter: PresenceFilter, states: PresenceStates, levels: string[] = []): string {
	const parts: string[] = [];
	for (const i of filter.items) {
		const checked = (i.levels ?? []).filter((l) => levels.includes(l.key));
		if (checked.length) parts.push(`${i.label} ${checked.map((l) => l.label).join(' ou ')}`);
		else if (states[i.key] === 'yes' || states[i.key] === 'no') parts.push(`${states[i.key] === 'yes' ? 'avec' : 'sans'} ${i.label}`);
	}
	return parts.join(', ');
}

/** Valeur d'un filtre dans la requête, ou `null` quand il ne filtre rien ou n'est pas proposé dans la page. */
function paramValue(filter: ListFilter, values: FilterValues): string | null {
	if (!(filter.enabled?.() ?? true)) return null;
	const fixed = filter.fixed?.() ?? null;
	if (fixed !== null) return fixed;
	if (filter.control === 'checkbox') {
		const selected = values.checkbox[filter.key] ?? [];
		return filter.serialize ? filter.serialize(selected) : selected.join(',') || null;
	}
	if (filter.control === 'entity') return (values.entity[filter.key] ?? []).join(',') || null;
	return encodePresence(values.presence[filter.key] ?? {}) || null;
}

/** Écrit dans `params` les filtres qui filtrent. Un filtre de présence à `itemParams` écrit un paramètre par élément filtré ; à `levelsParam`, un paramètre pour ses niveaux cochés. */
export function appendFilterParams(
	filters: ListFilter[],
	values: FilterValues,
	params: URLSearchParams,
): void {
	for (const f of filters) {
		if (f.control === 'presence' && f.levelsParam && isAvailable(f)) {
			const levels = values.levels[f.key] ?? [];
			if (levels.length) params.set(f.levelsParam, levels.join(','));
		}
		if (f.control === 'presence' && f.itemParams) {
			if (!isAvailable(f)) continue;
			for (const [item, state] of Object.entries(values.presence[f.key] ?? {})) {
				const param = f.itemParams[item];
				if (param && (state === 'yes' || state === 'no')) params.set(param, state);
			}
			continue;
		}
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

/** Clé, dans l'état de l'URL, des niveaux cochés d'un filtre de présence. */
const levelsKey = (filter: PresenceFilter): string => `${filter.key}.levels`;

/** Configuration de l'URL pour `useUrlFilters`, par clé de filtre. */
export function urlFilterDefs(filters: ListFilter[]): Record<string, UrlFilterDef> {
	const defs: Record<string, UrlFilterDef> = {};
	for (const f of filters) {
		if (f.control === 'presence') {
			defs[f.key] = { type: 'source_states', urlKey: f.param };
			if (f.levelsParam) defs[levelsKey(f)] = { type: 'string_array', urlKey: f.levelsParam };
		} else if (f.control === 'checkbox' && f.defaultSelection) {
			defs[f.key] = { type: 'single', urlKey: f.param, defaultValue: f.defaultSelection().join(',') };
		} else {
			defs[f.key] = { type: 'string_array', urlKey: f.param };
		}
	}
	return defs;
}

/** Texte d'URL d'une sélection, pour un filtre qui a une sélection par défaut. Une sélection qui reprend les valeurs par défaut, dans n'importe quel ordre, s'écrit comme elle, donc l'URL l'omet. Une sélection vidée s'écrit `all`. */
function selectionToken(selected: string[], defaults: string[]): string {
	if (selected.length === defaults.length && selected.every((v) => defaults.includes(v))) return defaults.join(',');
	return selected.join(',') || ALL_TOKEN;
}

/** État à écrire dans l'URL, dans la forme qu'attend `useUrlFilters`. */
export function urlState(filters: ListFilter[], values: FilterValues): Record<string, unknown> {
	const state: Record<string, unknown> = {};
	for (const f of filters) {
		if (f.control === 'checkbox') {
			const selected = values.checkbox[f.key] ?? [];
			state[f.key] = f.defaultSelection ? selectionToken(selected, f.defaultSelection()) : selected;
		} else if (f.control === 'entity') {
			state[f.key] = values.entity[f.key] ?? [];
		} else {
			state[f.key] = values.presence[f.key] ?? {};
			if (f.levelsParam) state[levelsKey(f)] = values.levels[f.key] ?? [];
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
		if (f.control === 'presence' && f.levelsParam) {
			const levels = restored[levelsKey(f)];
			if (Array.isArray(levels) && levels.length) values.levels[f.key] = levels as string[];
		}
		const raw = restored[f.key];
		if (raw == null || raw === '') continue;
		if (f.control === 'checkbox' && f.defaultSelection) {
			values.checkbox[f.key] = raw === ALL_TOKEN ? [] : String(raw).split(',');
		} else if (f.control === 'checkbox') {
			values.checkbox[f.key] = raw as string[];
		} else if (f.control === 'entity') {
			values.entity[f.key] = raw as string[];
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
