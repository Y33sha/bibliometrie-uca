<script lang="ts">
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';
	import { coreRange, rangeSelection, rangeSummary } from '#lib/filterRegistry.js';

	// Options d'un filtre d'intervalle (années) : histogramme des décomptes, et curseur à deux poignées qui fixe les bornes de l'intervalle. La sélection est la liste des valeurs de l'intervalle.
	// L'histogramme montre une barre par année de la plage qui concentre les décomptes (`coreRange`). Les années écartées de la plage forment une barre de plus de chaque côté : « avant » et « après ». Une poignée posée à une extrémité ne borne pas l'intervalle de ce côté.
	// Les poignées se posent sur les bords des barres : la poignée gauche au bord gauche de la première barre retenue, la poignée droite au bord droit de la dernière. Avec m barres, le curseur a m + 1 positions, de 0 à m.
	interface Props {
		/** Options de valeur entière, avec leur décompte. */
		options: FacetOption[];
		/** Valeurs sélectionnées. Une sélection vide ne filtre rien. */
		selected?: string[];
		onchange?: (selected: string[]) => void;
	}

	let { options, selected = $bindable([]), onchange }: Props = $props();

	const counts = $derived(new Map(options.filter((o) => o.count).map((o) => [Number(o.value), o.count ?? 0])));
	const pairs = $derived([...counts].sort(([a], [b]) => a - b));
	const first = $derived(pairs[0]?.[0] ?? 0);
	const last = $derived(pairs[pairs.length - 1]?.[0] ?? 0);
	const core = $derived(pairs.length ? coreRange(pairs) : null);
	const lo = $derived(core?.[0] ?? 0);
	const hi = $derived(core?.[1] ?? 0);
	const before = $derived(lo > first);
	const after = $derived(hi < last);
	const sumCounts = (keep: (year: number) => boolean) => pairs.reduce((sum, [y, c]) => (keep(y) ? sum + c : sum), 0);
	// Barres de l'histogramme : une par année de la plage, une année sans décompte comprise ; les années écartées de la plage, regroupées de chaque côté.
	const bars = $derived([
		...(before ? [{ key: 'before', title: `Avant ${lo}`, count: sumCounts((y) => y < lo) }] : []),
		...(core ? rangeSelection(lo, hi) : []).map((y) => ({ key: y, title: y, count: counts.get(Number(y)) ?? 0 })),
		...(after ? [{ key: 'after', title: `Après ${hi}`, count: sumCounts((y) => y > hi) }] : []),
	]);
	const m = $derived(bars.length);
	const offset = $derived(before ? 1 : 0);
	const maxCount = $derived(Math.max(1, ...bars.map((b) => b.count)));

	// Année de la poignée gauche ou droite à une position du curseur. Une poignée à une extrémité ne borne pas son côté.
	const startYear = (p: number) => (p === 0 ? first : lo + p - offset);
	const endYear = (p: number) => (p === m ? last : lo + p - offset - 1);

	// Bords de la sélection ; sans sélection, les extrémités.
	const selectedYears = $derived(selected.map(Number));
	const selectedStart = $derived.by(() => {
		if (!selected.length) return 0;
		const y = Math.min(...selectedYears);
		if (y < lo) return 0;
		return y > hi ? m - 1 : y - lo + offset;
	});
	const selectedEnd = $derived.by(() => {
		if (!selected.length) return m;
		const y = Math.max(...selectedYears);
		if (y > hi) return m;
		return y < lo ? 1 : y - lo + offset + 1;
	});

	// Bords pendant le glissement ; la sélection change au relâchement.
	let dragStart = $state<number | null>(null);
	let dragEnd = $state<number | null>(null);
	const start = $derived(dragStart ?? selectedStart);
	const end = $derived(dragEnd ?? selectedEnd);
	const filtered = $derived(start > 0 || end < m);
	const bounds = $derived<[number, number]>([startYear(start), endYear(end)]);
	const summary = $derived(filtered ? rangeSummary(bounds, options) : 'Toutes les années');

	// Texte lu par un lecteur d'écran pour chaque poignée : l'année du bord, ou les années écartées de la plage.
	const startText = $derived(start === 0 && before ? `Avant ${lo}` : String(startYear(start)));
	const endText = $derived(end === m && after ? `Après ${hi}` : String(endYear(end)));

	// Une poignée ne passe pas l'autre : l'intervalle garde une année au moins.
	function onStartInput(e: Event & { currentTarget: HTMLInputElement }) {
		dragStart = Math.min(Number(e.currentTarget.value), end - 1);
		e.currentTarget.value = String(dragStart);
	}
	function onEndInput(e: Event & { currentTarget: HTMLInputElement }) {
		dragEnd = Math.max(Number(e.currentTarget.value), start + 1);
		e.currentTarget.value = String(dragEnd);
	}

	function commit() {
		const next = filtered ? rangeSelection(bounds[0], bounds[1]) : [];
		dragStart = dragEnd = null;
		if (next.join() === selected.join()) return;
		selected = next;
		onchange?.(selected);
	}
</script>

{#if m}
	<div class="range">
		<div class="range-head">
			<span class="range-value" class:filtered aria-live="polite">{summary}</span>
		</div>
		<div class="histogram" aria-hidden="true">
			{#each bars as bar, i (bar.key)}
				<span class="bar-slot" title="{bar.title} : {bar.count.toLocaleString('fr-FR')}">
					<span class="bar" class:in-range={i >= start && i < end} style:height="{bar.count ? Math.max(4, (bar.count / maxCount) * 100) : 0}%"></span>
				</span>
			{/each}
		</div>
		<div class="slider">
			<input type="range" aria-label="Première année" aria-valuetext={startText} min="0" max={m} step="1" value={start} oninput={onStartInput} onchange={commit} />
			<input type="range" aria-label="Dernière année" aria-valuetext={endText} min="0" max={m} step="1" value={end} oninput={onEndInput} onchange={commit} />
		</div>
		<!-- Première et dernière années de la plage, sous le bord extérieur de leur barre. -->
		<div class="ends" aria-hidden="true">
			<span style:left="{(offset / m) * 100}%">{lo}</span><span style:right="{((after ? 1 : 0) / m) * 100}%">{hi}</span>
		</div>
	</div>
{/if}

<style>
	/* Poignée visible de 14 px, zone de saisie de 24 px : la bordure transparente agrandit la cible sans agrandir le disque. */
	.range {
		--thumb: 24px;
		--thumb-visible: 14px;
		padding-top: 2px;
	}
	.range-head {
		font-size: var(--fs-sm);
	}
	.range-value {
		color: var(--muted);
	}
	.range-value.filtered {
		color: var(--text);
		font-weight: 600;
	}
	/* Histogramme aligné sur la course des poignées : le centre d'une poignée va d'une demi-poignée du bord gauche à une demi-poignée du bord droit. Chaque barre occupe 1/n de cette course, ses bords tombent sur les positions du curseur. */
	.histogram {
		display: flex;
		align-items: flex-end;
		height: 40px;
		margin: 6px calc(var(--thumb) / 2) 0;
	}
	.bar-slot {
		display: flex;
		align-items: flex-end;
		flex: 1;
		min-width: 0;
		height: 100%;
		padding: 0 0.5px;
	}
	.bar {
		width: 100%;
		border-radius: 1px 1px 0 0;
		background: var(--border);
	}
	.bar.in-range {
		background: var(--accent-mid);
	}
	/* Deux curseurs superposés : seule la poignée de chacun capte le pointeur. */
	.slider {
		position: relative;
		height: var(--thumb);
		margin-top: calc(var(--thumb) / -2 + 1px);
	}
	.slider input[type='range'] {
		position: absolute;
		inset: 0;
		width: 100%;
		height: var(--thumb);
		margin: 0;
		background: transparent;
		appearance: none;
		pointer-events: none;
	}
	/* Ligne du curseur, du centre d'une poignée en butée à l'autre. Les pistes des deux champs restent transparentes. */
	.slider::before {
		content: '';
		position: absolute;
		top: calc(50% - 1px);
		left: calc(var(--thumb) / 2);
		right: calc(var(--thumb) / 2);
		height: 2px;
		background: var(--border);
	}
	.slider input[type='range']::-webkit-slider-runnable-track {
		height: 2px;
		background: transparent;
	}
	.slider input[type='range']::-moz-range-track {
		height: 2px;
		background: transparent;
	}
	.slider input[type='range']::-webkit-slider-thumb {
		appearance: none;
		box-sizing: border-box;
		width: var(--thumb);
		height: var(--thumb);
		margin-top: calc((2px - var(--thumb)) / 2);
		border: calc((var(--thumb) - var(--thumb-visible)) / 2) solid transparent;
		border-radius: 50%;
		background: var(--accent) content-box;
		cursor: grab;
		pointer-events: auto;
	}
	.slider input[type='range']::-moz-range-thumb {
		box-sizing: border-box;
		width: var(--thumb);
		height: var(--thumb);
		border: calc((var(--thumb) - var(--thumb-visible)) / 2) solid transparent;
		border-radius: 50%;
		background: var(--accent) content-box;
		cursor: grab;
		pointer-events: auto;
	}
	.slider input[type='range']:focus-visible {
		outline: none;
	}
	/* Focus clavier : la zone de saisie devient un halo autour de la poignée. */
	.slider input[type='range']:focus-visible::-webkit-slider-thumb {
		border-color: color-mix(in srgb, var(--accent) 40%, transparent);
	}
	.slider input[type='range']:focus-visible::-moz-range-thumb {
		border-color: color-mix(in srgb, var(--accent) 40%, transparent);
	}
	/* Même course que l'histogramme : les années tombent sous les bords de leurs barres. */
	.ends {
		position: relative;
		height: 1.5em;
		margin: 0 calc(var(--thumb) / 2);
		font-size: var(--fs-xs);
		color: var(--muted);
	}
	.ends span {
		position: absolute;
		top: 0;
	}
</style>
