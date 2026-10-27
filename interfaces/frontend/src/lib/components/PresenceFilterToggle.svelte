<script lang="ts">
	import { anchored } from '#lib/actions/anchored.js';
	import { useFacetPanel } from '#lib/composables/useFacetPanel.svelte.js';

	type ToggleState = 'all' | 'yes' | 'no';

	interface Item {
		key: string;
		label: string;
	}

	interface Props {
		label: string;
		items: Item[];
		states?: Record<string, ToggleState>;
		counts?: Record<string, { yes: number; no: number }>;
		/** Si true (défaut), affiche toujours le décompte des « présents » (counts.yes) quel que soit l'état du toggle. Garde une référence stable pendant que l'utilisateur cycle ses filtres. Passer false pour faire suivre le décompte (yes → présents, no → absents, all → total). */
		staticPresentCount?: boolean;
		onchange?: (states: Record<string, ToggleState>) => void;
	}

	let {
		label,
		items,
		states = $bindable({}),
		counts = {},
		staticPresentCount = true,
		onchange,
	}: Props = $props();

	const panel = useFacetPanel();
	const facetRoot = panel.root;

	const activeCount = $derived(Object.keys(states).length);

	function cycle(key: string) {
		const current = states[key] || 'all';
		const next: ToggleState = current === 'all' ? 'yes' : current === 'yes' ? 'no' : 'all';
		if (next === 'all') {
			const { [key]: _, ...rest } = states;
			states = rest;
		} else {
			states = { ...states, [key]: next };
		}
		onchange?.(states);
	}

	function stateOf(key: string): ToggleState {
		return states[key] || 'all';
	}

	function stateIcon(state: ToggleState): string {
		if (state === 'yes') return '✓';
		if (state === 'no') return '✗';
		return '—';
	}

	function tooltip(itemLabel: string, state: ToggleState): string {
		if (state === 'all') return `${itemLabel} : pas de filtre (cliquer pour filtrer)`;
		if (state === 'yes') return `${itemLabel} : uniquement les présents`;
		return `${itemLabel} : uniquement les absents`;
	}

	function countFor(key: string, state: ToggleState): number | null {
		const c = counts[key];
		if (!c) return null;
		if (staticPresentCount) return c.yes;
		if (state === 'yes') return c.yes;
		if (state === 'no') return c.no;
		return c.yes + c.no;
	}

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
		<div class="facet-panel" use:anchored>
			{#each items as item (item.key)}
				{@const state = stateOf(item.key)}
				{@const c = countFor(item.key, state)}
				<button
					type="button"
					class="item-row"
					title={tooltip(item.label, state)}
					onclick={() => cycle(item.key)}
				>
					<span
						class="state-icon"
						class:state-yes={state === 'yes'}
						class:state-no={state === 'no'}
					>
						{stateIcon(state)}
					</span>
					<span class="item-label">{item.label}</span>
					{#if c != null}
						<span class="item-count">{c.toLocaleString('fr-FR')}</span>
					{/if}
				</button>
			{/each}
		</div>
	{/if}
</div>

<style>
	/* Bouton et panneau : styles communs des facettes, dans shared.css. */
	.item-row {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 6px 12px;
		border: none;
		background: none;
		font-size: 0.95rem;
		cursor: pointer;
		font-family: inherit;
		color: var(--text);
		text-align: left;
	}
	.item-row:hover {
		background: var(--hover);
	}
	.state-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		border-radius: var(--radius);
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		background: var(--surface);
		flex-shrink: 0;
	}
	.state-icon.state-yes {
		background: var(--success-light);
		color: var(--success);
	}
	.state-icon.state-no {
		background: var(--danger-light);
		color: var(--danger);
	}
	.item-label {
		flex: 1;
		font-weight: 500;
	}
	.item-count {
		font-size: 0.8rem;
		color: var(--muted);
		margin-left: auto;
	}
</style>
