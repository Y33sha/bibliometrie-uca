<script lang="ts">
	// Options d'un filtre de présence : chaque élément passe de « tous » à « présents », puis « absents ». Partagé par la liste déroulante d'un filtre et le panneau des filtres.
	export type ToggleState = 'all' | 'yes' | 'no';

	export interface PresenceItem {
		key: string;
		label: string;
		/** Niveaux de l'élément, cochés un à un et combinés en OU. Cachés quand l'élément est exclu. */
		levels?: { key: string; label: string }[];
	}

	interface Props {
		items: PresenceItem[];
		states?: Record<string, ToggleState>;
		/** Clés des niveaux cochés, tous éléments confondus. */
		checkedLevels?: string[];
		counts?: Record<string, { yes: number; no: number }>;
		/** Si true (défaut), affiche toujours le décompte des « présents » (counts.yes) quel que soit l'état du toggle. Garde une référence stable pendant que l'utilisateur cycle ses filtres. Passer false pour faire suivre le décompte (yes → présents, no → absents, all → total). */
		staticPresentCount?: boolean;
		onchange?: (states: Record<string, ToggleState>) => void;
	}

	let {
		items,
		states = $bindable({}),
		checkedLevels = $bindable([]),
		counts = {},
		staticPresentCount = true,
		onchange,
	}: Props = $props();

	const activeCount = $derived(Object.keys(states).length + checkedLevels.length);

	function cycle(item: PresenceItem) {
		const current = states[item.key] || 'all';
		const next: ToggleState = current === 'all' ? 'yes' : current === 'yes' ? 'no' : 'all';
		if (next === 'all') {
			const { [item.key]: _, ...rest } = states;
			states = rest;
		} else {
			states = { ...states, [item.key]: next };
		}
		// Un élément exclu perd ses niveaux cochés.
		if (next === 'no' && item.levels) {
			const own = new Set(item.levels.map((l) => l.key));
			checkedLevels = checkedLevels.filter((k) => !own.has(k));
		}
		onchange?.(states);
	}

	function toggleLevel(key: string) {
		checkedLevels = checkedLevels.includes(key)
			? checkedLevels.filter((k) => k !== key)
			: [...checkedLevels, key];
		onchange?.(states);
	}

	function clear() {
		states = {};
		checkedLevels = [];
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

{#if activeCount > 0}
	<button type="button" class="option-row facet-clear" onclick={clear}>Effacer</button>
{/if}
{#each items as item (item.key)}
	{@const state = stateOf(item.key)}
	{@const c = countFor(item.key, state)}
	<button
		type="button"
		class="option-row"
		title={tooltip(item.label, state)}
		onclick={() => cycle(item)}
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
	{#if item.levels?.length && state !== 'no'}
		<div class="levels">
			{#each item.levels as level (level.key)}
				{@const lc = counts[level.key]?.yes}
				<label class="level-row">
					<input
						type="checkbox"
						checked={checkedLevels.includes(level.key)}
						onchange={() => toggleLevel(level.key)}
					/>
					<span class="level-label">{level.label}</span>
					{#if lc != null}
						<span class="item-count">{lc.toLocaleString('fr-FR')}</span>
					{/if}
				</label>
			{/each}
		</div>
	{/if}
{/each}

<style>
	.state-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		border-radius: var(--radius);
		font-size: var(--fs-sm);
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
		font-size: var(--fs-sm);
		color: var(--muted);
		margin-left: auto;
	}
	.levels {
		padding: 0 12px 4px 40px;
	}
	.level-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 2px 0;
		font-size: var(--fs-sm);
		cursor: pointer;
	}
	.level-row input {
		margin: 0;
	}
	.level-label {
		flex: 1;
	}
</style>
