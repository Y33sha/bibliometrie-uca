<script lang="ts">
	type SourceState = 'all' | 'yes' | 'no';

	interface Source {
		key: string;
		label: string;
	}

	interface Props {
		sources?: Source[];
		states?: Record<string, SourceState>;
		onchange?: (states: Record<string, SourceState>) => void;
	}

	let {
		sources = [
			{ key: 'hal', label: 'HAL' },
			{ key: 'oa', label: 'OpenAlex' }
		],
		states = $bindable({}),
		onchange
	}: Props = $props();

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

	function stateLabel(state: SourceState): string {
		if (state === 'yes') return '\u2713 ';
		if (state === 'no') return '\u2717 ';
		return '';
	}

	function tooltip(label: string, state: SourceState): string {
		if (state === 'all') return `${label} : pas de filtre (cliquer pour filtrer)`;
		if (state === 'yes') return `${label} : uniquement les publications pr\u00e9sentes`;
		return `${label} : uniquement les publications absentes`;
	}
</script>

<div class="source-filter">
	<span class="source-filter-label">Sources</span>
	{#each sources as src (src.key)}
		{@const state = stateOf(src.key)}
		<button
			type="button"
			class="source-toggle"
			class:state-yes={state === 'yes'}
			class:state-no={state === 'no'}
			title={tooltip(src.label, state)}
			onclick={() => cycle(src.key)}
		>{stateLabel(state)}{src.label}</button>
	{/each}
</div>

<style>
	.source-filter {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.source-filter-label {
		font-size: 12px;
		color: var(--muted);
		margin-right: 2px;
	}
	.source-toggle {
		display: inline-flex;
		align-items: center;
		padding: 4px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--card);
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
		color: var(--muted);
		font-family: inherit;
		transition: all 0.15s;
		user-select: none;
		white-space: nowrap;
	}
	.source-toggle:hover {
		border-color: #bbb;
	}
	.source-toggle.state-yes {
		border-color: #2a7d4f;
		background: #e6f4ec;
		color: #2a7d4f;
		font-weight: 600;
	}
	.source-toggle.state-no {
		border-color: #c0392b;
		background: #fde8e8;
		color: #c0392b;
		font-weight: 600;
	}
</style>
