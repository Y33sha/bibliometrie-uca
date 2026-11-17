/**
 * Axe horizontal linéaire des années `years`, croissantes : une graduation par année, une demi-année de marge de part et d'autre. Laissé à Chart.js, un pas de 1 partirait de la borne et graduerait les demi-années.
 */
export function yearAxis(years: number[]) {
	return {
		type: 'linear' as const,
		min: years[0] - 0.5,
		max: years[years.length - 1] + 0.5,
		afterBuildTicks(axis: { ticks: { value: number }[] }) {
			axis.ticks = years.map((value) => ({ value }));
		},
		ticks: { callback: (value: number | string) => String(value) },
	};
}
