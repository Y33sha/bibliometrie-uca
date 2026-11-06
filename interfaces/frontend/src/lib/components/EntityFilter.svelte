<script lang="ts">
	import { anchored } from '#lib/actions/anchored.js';
	import { useFacetPanel } from '#lib/composables/useFacetPanel.svelte.js';
	import { useEntityLabels } from '#lib/composables/useEntityLabels.svelte.js';
	import type { EntityKind } from '#lib/entityLabels.js';
	import EntityOptions from '#lib/components/filters/EntityOptions.svelte';

	/** Liste déroulante d'un filtre d'entité (éditeur, revue, auteur, sujet). En choix simple, le bouton affiche le nom de l'entité choisie. Les options : `EntityOptions`. */
	interface Props {
		label: string;
		/** Base de la facette contextuelle (ex. /api/publications/facets). */
		endpoint: string;
		kind: EntityKind;
		/** Filtres actifs du contexte. */
		buildParams: () => URLSearchParams;
		/** Ids des entités sélectionnées. */
		selected?: string[];
		/** Cases à cocher : plusieurs entités. Sinon, un seul choix. */
		multiple?: boolean;
		onchange?: (ids: string[]) => void;
	}

	let { label, endpoint, kind, buildParams, selected = [], multiple = false, onchange }: Props = $props();

	const panel = useFacetPanel();
	const facetRoot = panel.root;
	const names = useEntityLabels(() => kind, () => selected);

	const buttonText = $derived(!multiple && selected.length ? (names.labels[selected[0]] ?? label) : label);
</script>

<div class="facet" use:facetRoot>
	<button
		type="button"
		class="facet-btn"
		class:has-selection={selected.length > 0}
		aria-expanded={panel.open}
		onclick={panel.toggle}
	>
		<span class="facet-label">{buttonText}</span>
		{#if multiple && selected.length}
			<span class="facet-badge">{selected.length}</span>
		{/if}
		<span class="chevron" class:up={panel.open} aria-hidden="true"></span>
	</button>

	{#if panel.open}
		<div class="facet-panel popover" use:anchored>
			<EntityOptions {endpoint} {kind} {buildParams} {selected} {multiple} {onchange} onchosen={() => (panel.open = false)} />
		</div>
	{/if}
</div>

<style>
	/* Bouton, panneau et options : styles communs des facettes, dans shared.css. Le nom choisi s'affiche sur le bouton, d'où une largeur bornée. */
	.facet-btn {
		max-width: 240px;
	}
	.facet-label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.facet-panel {
		min-width: 260px;
	}
</style>
