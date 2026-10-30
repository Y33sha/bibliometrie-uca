<script lang="ts">
	/** Choix d'une année : curseur gradué, une graduation par année, et flèches pour l'année précédente ou suivante. */
	let {
		min,
		max,
		value = $bindable(),
		onchange
	}: {
		min: number;
		max: number;
		value: number;
		/** Appelé à chaque année retenue : curseur relâché ou flèche. */
		onchange: (year: number) => void;
	} = $props();

	const years = $derived(Array.from({ length: max - min + 1 }, (_, i) => min + i));
	// Années étiquetées : les bornes, et les multiples de 5 assez loin des bornes pour ne pas les chevaucher.
	const labelled = $derived(
		new Set(years.filter((y) => y === min || y === max || (y % 5 === 0 && y - min > 2 && max - y > 2)))
	);
	const position = (year: number) => (max === min ? 50 : (100 * (year - min)) / (max - min));

	function step(delta: number) {
		const year = Math.min(max, Math.max(min, value + delta));
		if (year === value) return;
		value = year;
		onchange(year);
	}
</script>

<div class="year-slider">
	<button type="button" class="year-arrow" aria-label="Année précédente" disabled={value <= min} onclick={() => step(-1)}>‹</button>
	<div class="year-track">
		<input
			type="range"
			aria-label="Année"
			{min}
			{max}
			step="1"
			bind:value
			onchange={() => onchange(value)}
		/>
		<div class="year-scale" aria-hidden="true">
			{#each years as y (y)}
				<span class="year-tick" class:labelled={labelled.has(y)} style:left="{position(y)}%">
					{#if labelled.has(y)}<span class="year-tick-label">{y}</span>{/if}
				</span>
			{/each}
		</div>
	</div>
	<button type="button" class="year-arrow" aria-label="Année suivante" disabled={value >= max} onclick={() => step(1)}>›</button>
</div>

<style>
	.year-slider {
		--thumb: 14px;
		display: flex;
		align-items: flex-start;
		gap: 6px;
	}
	.year-arrow {
		flex: none;
		width: 24px;
		height: 24px;
		padding: 0;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--card);
		color: var(--text);
		font-size: var(--fs-md);
		line-height: 1;
		cursor: pointer;
	}
	.year-arrow:hover:not(:disabled) {
		border-color: var(--accent);
		color: var(--accent);
	}
	.year-arrow:disabled {
		color: var(--border);
		cursor: default;
	}
	.year-track {
		flex: 1;
		min-width: 0;
	}
	/* Piste neutre, sans remplissage à gauche du curseur. */
	input[type='range'] {
		display: block;
		width: 100%;
		height: 24px;
		margin: 0;
		background: transparent;
		appearance: none;
		cursor: pointer;
	}
	input[type='range']::-webkit-slider-runnable-track {
		height: 4px;
		border-radius: 2px;
		background: var(--border);
	}
	input[type='range']::-moz-range-track {
		height: 4px;
		border-radius: 2px;
		background: var(--border);
	}
	input[type='range']::-webkit-slider-thumb {
		appearance: none;
		width: var(--thumb);
		height: var(--thumb);
		margin-top: calc((4px - var(--thumb)) / 2);
		border: none;
		border-radius: 50%;
		background: var(--accent);
	}
	input[type='range']::-moz-range-thumb {
		width: var(--thumb);
		height: var(--thumb);
		border: none;
		border-radius: 50%;
		background: var(--accent);
	}
	/* Graduations alignées sur le centre du curseur : sa course s'arrête à une demi-largeur des bords. */
	.year-scale {
		position: relative;
		height: 22px;
		margin: 0 calc(var(--thumb) / 2);
	}
	.year-tick {
		position: absolute;
		top: 0;
		width: 1px;
		height: 4px;
		background: var(--border);
	}
	.year-tick.labelled {
		height: 7px;
		background: var(--muted);
	}
	.year-tick-label {
		position: absolute;
		top: 8px;
		left: 50%;
		transform: translateX(-50%);
		font-size: var(--fs-xs);
		color: var(--muted);
		white-space: nowrap;
	}
</style>
