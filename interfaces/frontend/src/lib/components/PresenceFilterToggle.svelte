<script lang="ts">
	import { anchored } from '#lib/actions/anchored.js';
	import { useFacetPanel } from '#lib/composables/useFacetPanel.svelte.js';
	import PresenceOptions, { type PresenceItem, type ToggleState } from '#lib/components/filters/PresenceOptions.svelte';

	// Liste déroulante d'un filtre de présence. Les options : `PresenceOptions`.
	interface Props {
		label: string;
		items: PresenceItem[];
		states?: Record<string, ToggleState>;
		/** Clés des niveaux cochés, tous éléments confondus. */
		checkedLevels?: string[];
		counts?: Record<string, { yes: number; no: number }>;
		/** Voir `PresenceOptions`. */
		staticPresentCount?: boolean;
		onchange?: (states: Record<string, ToggleState>) => void;
	}

	let {
		label,
		items,
		states = $bindable({}),
		checkedLevels = $bindable([]),
		counts = {},
		staticPresentCount = true,
		onchange,
	}: Props = $props();

	const panel = useFacetPanel();
	const facetRoot = panel.root;

	const activeCount = $derived(Object.keys(states).length + checkedLevels.length);
</script>

<div class="facet" use:facetRoot>
	<button
		type="button"
		class="facet-btn"
		class:has-selection={activeCount > 0}
		aria-expanded={panel.open}
		onclick={panel.toggle}
	>
		<span class="facet-label">{label}</span>
		{#if activeCount > 0}
			<span class="facet-badge">{activeCount}</span>
		{/if}
		<span class="chevron" class:up={panel.open} aria-hidden="true"></span>
	</button>

	{#if panel.open}
		<div class="facet-panel popover" use:anchored>
			<PresenceOptions {items} bind:states bind:checkedLevels {counts} {staticPresentCount} {onchange} />
		</div>
	{/if}
</div>
