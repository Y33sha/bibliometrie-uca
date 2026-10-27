<script lang="ts">
	import { anchored } from '#lib/actions/anchored.js';
	import { useFacetPanel } from '#lib/composables/useFacetPanel.svelte.js';
	import Tooltip from '#lib/components/Tooltip.svelte';

	export interface FacetOption {
		value: string;
		text: string;
		count?: number;
	}

	interface Props {
		label: string;
		options: FacetOption[];
		searchable?: boolean;
		/** Valeurs cochées. Une sélection vide ne filtre rien. */
		selected?: string[];
		tooltip?: string;
		/** Regroupe les options sous des en-têtes (ex. familles de doc_types). Les options hors groupe sont rendues sans en-tête à la fin ; le regroupement est purement visuel, la sélection fonctionne à l'identique. */
		groups?: { label: string; values: string[] }[];
		onchange?: (selected: string[]) => void;
	}

	let { label, options, searchable = false, selected = $bindable([]), tooltip, groups, onchange }: Props = $props();

	const panel = useFacetPanel();
	const facetRoot = panel.root;
	let filterText = $state('');

	const filteredOptions = $derived(
		filterText
			? options.filter((o) => o.text.toLowerCase().includes(filterText.toLowerCase()))
			: options
	);

	function toggle(value: string) {
		selected = selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value];
		onchange?.(selected);
	}

	function clear() {
		selected = [];
		onchange?.(selected);
	}

</script>

{#snippet optionRow(opt: FacetOption)}
	<label>
		<input type="checkbox" checked={selected.includes(opt.value)} onchange={() => toggle(opt.value)} />
		<span class="facet-option-text" title={opt.text}>{opt.text}</span>{#if opt.count != null}<span class="facet-count">{opt.count}</span>{/if}
	</label>
{/snippet}

<div class="facet" use:facetRoot>
	<!-- L'infobulle se masque quand le panneau est ouvert. -->
	<Tooltip text={panel.open ? '' : (tooltip ?? '')}>
	<button
		type="button"
		class="facet-btn"
		class:has-selection={selected.length > 0}
		aria-expanded={panel.open}
		onclick={() => {
			if (!panel.open) filterText = '';
			panel.toggle();
		}}
	>
		<span class="facet-label">{label}</span>
		{#if selected.length > 0}
			<span class="facet-badge">{selected.length}</span>
		{/if}
		<span class="chevron" class:up={panel.open} aria-hidden="true"></span>
	</button>
	</Tooltip>

	{#if panel.open}
		<div class="facet-panel" use:anchored>
			{#if searchable}
				<input
					type="text"
					class="facet-search"
					placeholder="Filtrer"
					bind:value={filterText}
				/>
			{/if}
			{#if selected.length}
				<button type="button" class="facet-clear" onclick={clear}>Effacer</button>
			{/if}
			<div class="facet-options">
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
