import { Chart, registerables, type Element, type Plugin, type VisualElement } from 'chart.js';
import ChartDataLabels from 'chartjs-plugin-datalabels';
import { cssColor, cssVar, fontSize } from './cssVar';

/** Opacité des éléments de l'année en cours, incomplète. */
const CURRENT_YEAR_OPACITY = 0.5;

const faded = new WeakSet<Element>();
const wrapped = new WeakSet<Element>();

/**
 * Atténue les éléments (barres, points, secteurs) dont le libellé commence par l'année en cours : `data.labels[i]` désigne l'élément `i` de chaque jeu de données.
 */
const currentYearPlugin: Plugin = {
	id: 'currentYear',
	afterDatasetUpdate(chart, { meta }) {
		const current = String(new Date().getFullYear());
		meta.data.forEach((element, i) => {
			const year = String(chart.data.labels?.[i] ?? '').match(/^\d{4}(?!\d)/)?.[0];
			if (year !== current) {
				faded.delete(element);
				return;
			}
			faded.add(element);
			if (wrapped.has(element)) return;
			wrapped.add(element);
			const visual = element as Element & VisualElement;
			const draw = visual.draw.bind(visual);
			visual.draw = (ctx, area) => {
				if (!faded.has(element)) return draw(ctx, area);
				ctx.save();
				ctx.globalAlpha *= CURRENT_YEAR_OPACITY;
				draw(ctx, area);
				ctx.restore();
			};
		});
	}
};

/**
 * Chart.js enregistré une fois pour toute l'application : composants standard, étiquettes de valeurs, atténuation de l'année en cours, police, taille et couleur de texte lues dans les variables CSS.
 */
Chart.register(...registerables, ChartDataLabels, currentYearPlugin);
Chart.defaults.font.family = cssVar('font');
Chart.defaults.font.size = fontSize('sm');
Chart.defaults.color = cssColor('text-secondary');

export { Chart };
