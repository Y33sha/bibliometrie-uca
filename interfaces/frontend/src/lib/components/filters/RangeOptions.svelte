<script lang="ts">
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';
	import { coreRange, rangeSelection, rangeSummary } from '#lib/filterRegistry.js';

	// Options d'un filtre d'intervalle (années) : histogramme des décomptes, et curseur à deux poignées qui fixe les bornes de l'intervalle. La sélection est la liste des valeurs de l'intervalle.
	// Le curseur couvre la plage qui concentre les décomptes (`coreRange`). Une poignée posée à une extrémité ne borne pas l'intervalle de ce côté : les valeurs écartées de la plage y restent comprises.
	// Les poignées se posent sur les bords des barres : la poignée gauche au bord gauche de la première année retenue, la poignée droite au bord droit de la dernière. Avec n années, le curseur a n + 1 positions, de 0 à n.
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
	// Toutes les années de la plage : une année sans décompte garde sa place dans l'histogramme.
	const span = $derived(core ? rangeSelection(lo, hi).map(Number) : []);
	const n = $derived(span.length);
	const maxCount = $derived(Math.max(1, ...span.map((y) => counts.get(y) ?? 0)));

	// Bords de la sélection : la sélection est ramenée dans la plage ; sans sélection, les extrémités.
	const clampYear = (y: number) => Math.min(hi, Math.max(lo, y));
	const selectedYears = $derived(selected.map(Number));
	const selectedStart = $derived(selected.length ? clampYear(Math.min(...selectedYears)) - lo : 0);
	const selectedEnd = $derived(selected.length ? clampYear(Math.max(...selectedYears)) - lo + 1 : n);

	// Bords pendant le glissement ; la sélection change au relâchement.
	let dragStart = $state<number | null>(null);
	let dragEnd = $state<number | null>(null);
	const start = $derived(dragStart ?? selectedStart);
	const end = $derived(dragEnd ?? selectedEnd);
	const filtered = $derived(start > 0 || end < n);
	// Intervalle de la sélection : une poignée à une extrémité ne borne pas son côté.
	const bounds = $derived<[number, number]>([start === 0 ? first : lo + start, end === n ? last : lo + end - 1]);
	const summary = $derived(filtered ? rangeSummary(bounds, options) : 'Toutes les années');

	// Texte lu par un lecteur d'écran pour chaque poignée : l'année du bord, ou l'absence de borne.
	const startText = $derived(start === 0 ? (lo > first ? `${lo} et avant` : String(lo)) : String(lo + start));
	const endText = $derived(end === n ? (hi < last ? `${hi} et après` : String(hi)) : String(lo + end - 1));

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

{#if n}
	<div class="range" style:--n={n}>
		<div class="range-head">
			<span class="range-value" class:filtered aria-live="polite">{summary}</span>
		</div>
		<div class="histogram" aria-hidden="true">
			{#each span as year, i (year)}
				{@const c = counts.get(year) ?? 0}
				<span class="bar-slot" title="{year} : {c.toLocaleString('fr-FR')}">
					<span class="bar" class:in-range={filtered && i >= start && i < end} style:height="{c ? Math.max(4, (c / maxCount) * 100) : 0}%"></span>
				</span>
			{/each}
		</div>
		<div class="slider">
			<input type="range" aria-label="Première année" aria-valuetext={startText} min="0" max={n} step="1" value={start} oninput={onStartInput} onchange={commit} />
			<input type="range" aria-label="Dernière année" aria-valuetext={endText} min="0" max={n} step="1" value={end} oninput={onEndInput} onchange={commit} />
		</div>
		<div class="ends" aria-hidden="true"><span>{lo > first ? `${lo} et avant` : lo}</span><span>{hi < last ? `${hi} et après` : hi}</span></div>
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
	.slider input[type='range']:first-child::-webkit-slider-runnable-track {
		height: 2px;
		background: var(--border);
	}
	.slider input[type='range']:first-child::-moz-range-track {
		height: 2px;
		background: var(--border);
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
	.ends {
		display: flex;
		justify-content: space-between;
		margin: 0 calc(var(--thumb) / 2 - 4px);
		font-size: var(--fs-xs);
		color: var(--muted);
	}
</style>
