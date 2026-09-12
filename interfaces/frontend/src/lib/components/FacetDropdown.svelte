<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	export interface FacetOption {
		value: string;
		text: string;
		count?: number;
	}

	interface Props {
		label: string;
		options: FacetOption[];
		searchable?: boolean;
		selected?: string[];
		allLabel?: string;
		tooltip?: string;
		/** Regroupe les options sous des en-têtes (ex. familles de doc_types). Les options hors groupe sont rendues sans en-tête à la fin ; le regroupement est purement visuel, la sélection fonctionne à l'identique. */
		groups?: { label: string; values: string[] }[];
		onchange?: (selected: string[]) => void;
	}

	let { label, options, searchable = false, selected = $bindable([]), allLabel = 'Tous', tooltip, groups, onchange }: Props = $props();
	let showTooltip = $state(false);
	let tooltipTimer: ReturnType<typeof setTimeout>;

	let open = $state(false);
	let filterText = $state('');
	let allMode = $state(true);

	const instanceId = Symbol();

	const filteredOptions = $derived(
		filterText
			? options.filter((o) => o.text.toLowerCase().includes(filterText.toLowerCase()))
			: options
	);

	const isAllSelected = $derived(allMode && selected.length === 0);

	function toggleAll() {
		if (allMode) {
			// Décoche « Tous » → tout décocher visuellement
			allMode = false;
			selected = [];
			// Pas d'onchange : le filtre ne change pas (vide = aucun filtre)
		} else {
			// Coche « Tous » → retour à tout
			const hadFilter = selected.length > 0;
			allMode = true;
			selected = [];
			if (hadFilter) onchange?.(selected);
		}
	}

	function toggle(value: string) {
		if (allMode) {
			// En mode « tous » → décocher celui-ci = sélectionner tout sauf lui
			allMode = false;
			selected = options.filter((o) => o.value !== value).map((o) => o.value);
		} else if (selected.includes(value)) {
			selected = selected.filter((v) => v !== value);
			// Pas de bascule auto vers allMode quand vide
		} else {
			selected = [...selected, value];
			if (selected.length === options.length) {
				allMode = true;
				selected = [];
			}
		}
		onchange?.(selected);
	}

	function isChecked(value: string): boolean {
		return allMode || selected.includes(value);
	}

	function handleClickOutside() {
		open = false;
	}

	function handleFacetClose(e: Event) {
		if ((e as CustomEvent).detail !== instanceId) {
			open = false;
		}
	}

	onMount(() => {
		window.addEventListener('facet-close', handleFacetClose);
	});
	onDestroy(() => {
		window.removeEventListener('facet-close', handleFacetClose);
	});
</script>

<svelte:window onclick={handleClickOutside} />

{#snippet optionRow(opt: FacetOption)}
	<label>
		<input type="checkbox" checked={isChecked(opt.value)} onchange={() => toggle(opt.value)} />
		<span class="facet-option-text" title={opt.text}>{opt.text}</span>{#if opt.count != null}<span class="facet-count">{opt.count}</span>{/if}
	</label>
{/snippet}

<div class="facet">
	<button
		type="button"
		class="facet-btn"
		class:has-selection={selected.length > 0}
		onclick={(e) => {
			e.stopPropagation();
			showTooltip = false;
			if (open) {
				open = false;
				return;
			}
			window.dispatchEvent(new CustomEvent('facet-close', { detail: instanceId }));
			// La sélection change aussi hors du panneau (URL, barre des filtres actifs) : « Tous » est coché quand elle est vide.
			allMode = selected.length === 0;
			open = true;
			filterText = '';
		}}
		onmouseenter={() => {
			if (tooltip && !open) {
				showTooltip = true;
			}
		}}
		onmouseleave={() => { showTooltip = false; }}
	>
		<span class="facet-label">{label}</span>
		{#if selected.length > 0}
			<span class="facet-badge">{selected.length}</span>
		{/if}
		<span class="facet-arrow">&#9662;</span>
	</button>
	{#if showTooltip && tooltip}
		<div class="facet-tooltip facet-tooltip-below">{tooltip}</div>
	{/if}

	{#if open}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="facet-panel" onclick={(e) => e.stopPropagation()}>
			{#if searchable}
				<input
					type="text"
					class="facet-search"
					placeholder="Filtrer..."
					bind:value={filterText}
				/>
			{/if}
			<div class="facet-options">
				<label>
					<input type="checkbox" checked={isAllSelected} onchange={toggleAll} />
					<span style="font-weight:500">{allLabel}</span>
				</label>
				{#if groups}
					{#each groups as g (g.label)}
						{@const opts = filteredOptions.filter((o) => g.values.includes(o.value))}
						{#if opts.length}
							<div class="facet-group-label">{g.label}</div>
							{#each opts as opt (opt.value)}{@render optionRow(opt)}{/each}
						{/if}
					{/each}
					{@const ungrouped = filteredOptions.filter(
						(o) => !groups.some((g) => g.values.includes(o.value)),
					)}
					{#each ungrouped as opt (opt.value)}{@render optionRow(opt)}{/each}
				{:else}
					{#each filteredOptions as opt (opt.value)}{@render optionRow(opt)}{/each}
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	/* Bouton, panneau et options : styles communs des facettes, dans shared.css. */
	.facet-tooltip {
		position: absolute;
		bottom: calc(100% + 6px);
		left: 50%;
		transform: translateX(-50%);
		background: #333;
		color: #fff;
		font-size: 0.78rem;
		line-height: 1.4;
		padding: 6px 10px;
		border-radius: 5px;
		white-space: pre-line;
		z-index: 200;
		pointer-events: none;
		box-shadow: 0 2px 8px rgba(0,0,0,0.2);
	}
	.facet-tooltip::after {
		content: '';
		position: absolute;
		top: 100%;
		left: 50%;
		transform: translateX(-50%);
		border: 5px solid transparent;
		border-top-color: #333;
	}
	.facet-tooltip-below {
		bottom: auto;
		top: calc(100% + 6px);
	}
	.facet-tooltip-below::after {
		top: auto;
		bottom: 100%;
		border-top-color: transparent;
		border-bottom-color: #333;
	}

	.facet-group-label {
		margin-top: 4px;
		padding: 7px 12px 3px;
		border-top: 1px solid var(--border);
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--muted);
	}
	.facet-options label {
		white-space: nowrap;
	}
</style>
