import { Chart, registerables, type BarElement, type Element, type FontSpec, type Plugin, type VisualElement } from 'chart.js';
import { toFont } from 'chart.js/helpers';
import ChartDataLabels from 'chartjs-plugin-datalabels';
import type { Context as DataLabelsContext } from 'chartjs-plugin-datalabels';
import { cssColor, cssVar, fontSize } from './cssVar';

/** Opacité des éléments de l'année en cours, incomplète. */
const CURRENT_YEAR_OPACITY = 0.5;

const faded = new WeakSet<Element>();
const wrapped = new WeakSet<Element>();

/**
 * Atténue les éléments (barres, points) dont le libellé commence par l'année en cours : `data.labels[i]` désigne l'élément `i` de chaque jeu de données.
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

/** Marge intérieure minimale autour d'une étiquette de valeur dans son segment de barre, en pixels. */
const BAR_LABEL_PADDING = 4;

/**
 * Vrai si `text`, écrit dans la police `font`, tient dans le segment de barre de l'étiquette `ctx` : en longueur et en épaisseur, marges comprises.
 */
export function fitsInBar(ctx: DataLabelsContext, text: string, font: Partial<FontSpec>): boolean {
	const bar = ctx.chart.getDatasetMeta(ctx.datasetIndex).data[ctx.dataIndex] as BarElement;
	const { x, y, base, width, height, horizontal } = bar.getProps(['x', 'y', 'base', 'width', 'height', 'horizontal'], true);
	const length = Math.abs(((horizontal ? x : y) ?? base) - base);
	const thickness = horizontal ? height : width;
	const resolved = toFont(font);
	const canvas = ctx.chart.ctx;
	canvas.save();
	canvas.font = resolved.string;
	const textLength = canvas.measureText(text).width;
	canvas.restore();
	const [along, across] = horizontal ? [textLength, resolved.lineHeight] : [resolved.lineHeight, textLength];
	return length >= along + 2 * BAR_LABEL_PADDING && thickness >= across;
}

/** Espace entre deux segments voisins d'une barre empilée, en pixels. */
const SEGMENT_GAP = 2;

/** Couleur du fond sur lequel `canvas` est posé : le premier fond non transparent de ses ancêtres, `--bg` à défaut. */
export function backdropColor(canvas: HTMLCanvasElement): string {
	for (let el = canvas.parentElement; el; el = el.parentElement) {
		const color = getComputedStyle(el).backgroundColor;
		if (color && color !== 'transparent' && !/^rgba\(.*,\s*0\)$/.test(color)) return color;
	}
	return cssColor('bg');
}

/**
 * Options d'un jeu de données de barres empilées dessinées dans `canvas` : un liseré de la couleur du fond, au bout de chaque segment, le sépare du suivant. `horizontal` : barres horizontales.
 */
export function stackedSegmentOptions(canvas: HTMLCanvasElement, horizontal = false) {
	return {
		borderColor: backdropColor(canvas),
		borderWidth: horizontal ? { right: SEGMENT_GAP } : { top: SEGMENT_GAP },
	};
}

/** `text` tronqué et terminé par une ellipse pour tenir en `maxWidth` pixels dans la police `font` ; `text` entier s'il tient. */
export function truncateToWidth(canvas: CanvasRenderingContext2D, text: string, font: Partial<FontSpec>, maxWidth: number): string {
	canvas.save();
	canvas.font = toFont(font).string;
	let length = text.length;
	const candidate = () => (length === text.length ? text : `${text.slice(0, length).trimEnd()}…`);
	while (length > 0 && canvas.measureText(candidate()).width > maxWidth) length--;
	canvas.restore();
	return candidate();
}

export { Chart };
