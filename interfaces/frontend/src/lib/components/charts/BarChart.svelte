<script module lang="ts">
	/** Place réservée au texte au bout des barres horizontales, à droite de la borne haute de l'axe des valeurs, en pixels. */
	export const BAR_LABEL_SPACE = 48;
</script>

<script lang="ts">
	import type { CartesianScaleOptions, Plugin, Scale } from 'chart.js';
	import { cssColor, fontSize } from '#lib/components/charts/cssVar.js';
	import { Chart, truncateToWidth } from '#lib/components/charts/chart.js';

	let {
		labels,
		values,
		datasetLabel = '',
		color,
		horizontal = false,
		height = 280,
		max,
		barLabel,
		tooltipLabel,
		prominentLabels = false,
		categoryAxisWidth
	}: {
		labels: string[];
		values: number[];
		datasetLabel?: string;
		/** Couleur des barres, unique ou une par barre ; défaut = variable CSS `--accent-mid`. */
		color?: string | string[];
		/** Barres horizontales (axe des valeurs en X). */
		horizontal?: boolean;
		height?: number;
		/** Borne haute de l'axe des valeurs ; défaut = ajustée aux valeurs. */
		max?: number;
		/** Texte au bout de la barre `index` ; défaut = la valeur. */
		barLabel?: (value: number, index: number) => string;
		/** Texte de l'infobulle de la barre `index` ; défaut = « libellé du jeu de données : valeur ». */
		tooltipLabel?: (value: number, index: number) => string;
		/** Libellés des catégories et texte au bout des barres en taille `--fs-md`, couleur `--text`. */
		prominentLabels?: boolean;
		/** Barres horizontales : largeur fixe en pixels de l'axe des catégories, libellés compris ; libellé trop long tronqué, entier au survol. Défaut = ajustée aux libellés. */
		categoryAxisWidth?: number;
	} = $props();

	let canvas = $state<HTMLCanvasElement | undefined>();
	let chart: Chart | null = null;

	/** Libellé entier de la catégorie survolée à gauche de l'axe des barres horizontales, s'il est tronqué. */
	const fullLabelOnHover: Plugin<'bar'> = {
		id: 'fullLabelOnHover',
		afterEvent(c, { event }) {
			const scale = c.scales.y;
			const onAxis = event.x !== null && event.y !== null && event.x < c.chartArea.left;
			const index = onAxis ? Number(scale.getValueForPixel(event.y!)) : -1;
			const label = labels[index];
			c.canvas.title = label !== undefined && scale.ticks[index]?.label !== label ? label : '';
		}
	};

	function render() {
		if (chart) {
			chart.destroy();
			chart = null;
		}
		if (!canvas || values.length === 0) return;
		const barColor = color ?? cssColor('accent-mid');
		const valueScale = {
			beginAtZero: true,
			max,
			ticks: { precision: 0 }
		};
		const labelStyle: { font?: { size: number }; color?: string } = prominentLabels ? { font: { size: fontSize('md') }, color: cssColor('text') } : {};
		const fixedAxisWidth = horizontal ? categoryAxisWidth : undefined;
		const categoryScale = {
			grid: { display: false },
			ticks: {
				...labelStyle,
				...(fixedAxisWidth !== undefined && {
					callback(this: Scale, _value: unknown, index: number) {
						const { ticks, grid } = (this as Scale<CartesianScaleOptions>).options;
						const labelSpace = fixedAxisWidth - ticks.padding - (grid.tickLength ?? 0);
						return truncateToWidth(this.ctx, labels[index], labelStyle.font ?? {}, labelSpace);
					}
				})
			},
			...(fixedAxisWidth !== undefined && {
				afterFit: (scale: { width: number }) => {
					scale.width = fixedAxisWidth;
				}
			})
		};

		chart = new Chart(canvas, {
			type: 'bar',
			data: {
				labels,
				datasets: [{ label: datasetLabel, data: values, backgroundColor: barColor }]
			},
			options: {
				indexAxis: horizontal ? 'y' : 'x',
				responsive: true,
				maintainAspectRatio: false,
				// Place pour les valeurs affichées au bout des barres.
				layout: { padding: horizontal ? { right: BAR_LABEL_SPACE } : { top: 20 } },
				plugins: {
					legend: { display: false },
					datalabels: {
						anchor: 'end',
						align: 'end',
						...labelStyle,
						font: { weight: 600, ...labelStyle.font },
						...(barLabel && {
							formatter: (v: number, ctx: { dataIndex: number }) => barLabel(v, ctx.dataIndex)
						})
					},
					...(tooltipLabel && {
						tooltip: {
							callbacks: {
								label: (item: { dataIndex: number }) => tooltipLabel(values[item.dataIndex], item.dataIndex)
							}
						}
					})
				},
				scales: horizontal
					? { x: valueScale, y: categoryScale }
					: { y: valueScale, x: categoryScale }
			},
			plugins: fixedAxisWidth !== undefined ? [fullLabelOnHover] : []
		});
	}

	$effect(() => {
		void labels;
		void values;
		void color;
		void horizontal;
		void max;
		void barLabel;
		void tooltipLabel;
		void prominentLabels;
		void categoryAxisWidth;
		void canvas;
		render();
		return () => {
			if (chart) {
				chart.destroy();
				chart = null;
			}
		};
	});
</script>

<!-- Le graphique est dessiné dans un canvas : les lecteurs d'écran lisent le tableau des données. -->
<div class="chart-wrap" style="height: {height}px">
	<canvas bind:this={canvas} aria-hidden="true"></canvas>
</div>
<div class="visually-hidden">
	<table>
		<thead>
			<tr><td></td><th scope="col">{datasetLabel || 'Nombre'}</th></tr>
		</thead>
		<tbody>
			{#each labels as label, i (i)}
				<tr><th scope="row">{label}</th><td>{tooltipLabel ? tooltipLabel(values[i], i) : values[i]}{#if barLabel} ({barLabel(values[i], i)}){/if}</td></tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.chart-wrap {
		position: relative;
	}
</style>
