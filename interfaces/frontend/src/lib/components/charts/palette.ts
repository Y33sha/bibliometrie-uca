import { cssColor } from '#lib/components/charts/cssVar.js';

/** Nombre de couleurs de la palette des graphiques (`--chart-1` à `--chart-10` dans `shared.css`). */
const CHART_COLORS = 10;

/** Couleur de la série de rang `index` d'un graphique, quand la série n'a pas de couleur propre. La palette repart du début au-delà de sa dernière couleur. */
export function chartColor(index: number): string {
	return cssColor(`chart-${(index % CHART_COLORS) + 1}`);
}
