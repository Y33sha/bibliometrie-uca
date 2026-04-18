<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	type SourceState = 'all' | 'yes' | 'no';

	interface Source {
		key: string;
		label: string;
	}

	interface Props {
		sources?: Source[];
		states?: Record<string, SourceState>;
		counts?: Record<string, number>;
		onchange?: (states: Record<string, SourceState>) => void;
	}

	let {
		sources = [
			{ key: 'hal', label: 'HAL' },
			{ key: 'oa', label: 'OpenAlex' },
			{ key: 'scanr', label: 'ScanR' },
			{ key: 'wos', label: 'WoS' }
		],
		states = $bindable({}),
		counts = {},
		onchange
	}: Props = $props();

	let open = $state(false);
	const instanceId = Symbol();

	const hasFilter = $derived(Object.keys(states).length > 0);
	const activeCount = $derived(Object.keys(states).length);

	function cycle(key: string) {
		const current = states[key] || 'all';
		const next: SourceState = current === 'all' ? 'yes' : current === 'yes' ? 'no' : 'all';
		if (next === 'all') {
			const { [key]: _, ...rest } = states;
			states = rest;
		} else {
			states = { ...states, [key]: next };
		}
		onchange?.(states);
	}

	function stateOf(key: string): SourceState {
		return states[key] || 'all';
	}

	function stateIcon(state: SourceState): string {
		if (state === 'yes') return '✓';
		if (state === 'no') return '✗';
		return '—';
	}

	function tooltip(label: string, state: SourceState): string {
		if (state === 'all') return `${label} : pas de filtre (cliquer pour filtrer)`;
		if (state === 'yes') return `${label} : uniquement les publications présentes`;
		return `${label} : uniquement les publications absentes`;
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

<div class="facet">
	<button
		type="button"
		class="facet-btn"
		class:has-selection={hasFilter}
		onclick={(e) => {
			e.stopPropagation();
			if (open) { open = false; return; }
			window.dispatchEvent(new CustomEvent('facet-close', { detail: instanceId }));
			open = true;
		}}
	>
		<span class="facet-label">Sources</span>
		{#if activeCount > 0}
			<span class="facet-badge">{activeCount}</span>
		{/if}
		<span class="facet-arrow">&#9662;</span>
	</button>

	{#if open}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="facet-panel" onclick={(e) => e.stopPropagation()}>
			{#each sources as src (src.key)}
				{@const state = stateOf(src.key)}
				<button
					type="button"
					class="source-row"
					title={tooltip(src.label, state)}
					onclick={() => cycle(src.key)}
				>
					<span class="state-icon" class:state-yes={state === 'yes'} class:state-no={state === 'no'}>
						{stateIcon(state)}
					</span>
					<span class="source-label">{src.label}</span>
					{#if counts[src.key] != null}
						<span class="source-count">{counts[src.key].toLocaleString('fr-FR')}</span>
					{/if}
				</button>
			{/each}
		</div>
	{/if}
</div>

<style>
	.facet {
		position: relative;
		display: inline-block;
	}
	.facet-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 6px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--card);
		font-size: 0.95rem;
		cursor: pointer;
		color: var(--text);
		white-space: nowrap;
		font-family: inherit;
	}
	.facet-btn:hover {
		border-color: #ccc;
	}
	.facet-btn.has-selection {
		border-color: var(--accent);
		background: #e8f0f8;
	}
	.facet-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		padding: 0 5px;
		border-radius: 9px;
		background: var(--accent);
		color: white;
		font-size: 0.8rem;
		font-weight: 600;
	}
	.facet-arrow {
		font-size: 0.7rem;
		color: var(--muted);
		margin-left: 2px;
	}
	.facet-panel {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		min-width: 220px;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
		z-index: 100;
		padding: 4px 0;
	}
	.source-row {
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
	.source-row:hover {
		background: #f5f5f2;
	}
	.state-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		border-radius: 4px;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		background: #f0f0f0;
		flex-shrink: 0;
	}
	.state-icon.state-yes {
		background: #e6f4ec;
		color: #2a7d4f;
	}
	.state-icon.state-no {
		background: #fde8e8;
		color: #c0392b;
	}
	.source-label {
		flex: 1;
		font-weight: 500;
	}
	.source-count {
		font-size: 0.8rem;
		color: #888;
		margin-left: auto;
	}
</style>
