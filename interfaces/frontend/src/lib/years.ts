/**
 * Années des graphiques par année : dashboard et vue Statistiques. Les années vides comprises entre la première et la dernière année affichées restent sur l'axe.
 */
import { coreRange, rangeSelection } from '#lib/filterRegistry.js';

/** Années du dashboard, décroissantes : de la première à la dernière année présente entre `currentYear - 5` et `currentYear`, années vides comprises. Les années postérieures (prépublications datées de l'année suivante) sont exclues. */
export function defaultYears(years: string[], currentYear: number): string[] {
	const present = years.map(Number).filter((y) => Number.isInteger(y) && y >= currentYear - 5 && y <= currentYear);
	if (!present.length) return [];
	return rangeSelection(Math.min(...present), Math.max(...present)).reverse();
}

/** Années de l'axe des années de la vue Statistiques, croissantes. Avec un filtre d'années (`selected`, valeurs séparées par des virgules), les années choisies. Sans filtre, la plage qui concentre les valeurs des lignes `rows` du pivot (`coreRange`), années vides comprises. */
export function pivotAxisYears(rows: Record<string, unknown>[], selected: string | null): string[] {
	if (selected) {
		const years = selected.split(',').map(Number).filter(Number.isInteger);
		return [...new Set(years)].sort((a, b) => a - b).map(String);
	}
	const totals = new Map<number, number>();
	for (const r of rows) {
		if (r.year == null) continue;
		const year = Number(r.year);
		if (Number.isInteger(year)) totals.set(year, (totals.get(year) ?? 0) + Number(r.value ?? 0));
	}
	if (!totals.size) return [];
	return rangeSelection(...coreRange([...totals].sort(([a], [b]) => a - b)));
}
