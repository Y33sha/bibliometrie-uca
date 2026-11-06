<script lang="ts">
	import { anchored } from '#lib/actions/anchored.js';
	import { useFacetPanel } from '#lib/composables/useFacetPanel.svelte.js';
	import Tooltip from '#lib/components/Tooltip.svelte';
	import CheckboxOptions from '#lib/components/filters/CheckboxOptions.svelte';

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
		/** Regroupe les options sous des en-têtes (ex. familles de doc_types). */
		groups?: { label: string; values: string[] }[];
		onchange?: (selected: string[]) => void;
	}

	let { label, options, searchable = false, selected = $bindable([]), tooltip, groups, onchange }: Props = $props();

	const panel = useFacetPanel();
	const facetRoot = panel.root;
</script>

<div class="facet" use:facetRoot>
	<!-- L'infobulle se masque quand le panneau est ouvert. -->
	<Tooltip text={panel.open ? '' : (tooltip ?? '')}>
	<button
		type="button"
		class="facet-btn"
		class:has-selection={selected.length > 0}
		aria-expanded={panel.open}
		onclick={panel.toggle}
	>
		<span class="facet-label">{label}</span>
		{#if selected.length > 0}
			<span class="facet-badge">{selected.length}</span>
		{/if}
		<span class="chevron" class:up={panel.open} aria-hidden="true"></span>
	</button>
	</Tooltip>

	{#if panel.open}
		<div class="facet-panel popover" use:anchored>
			<CheckboxOptions {options} {searchable} {groups} bind:selected {onchange} />
		</div>
	{/if}
</div>
