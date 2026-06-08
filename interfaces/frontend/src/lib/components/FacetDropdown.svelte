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
		onchange?: (selected: string[]) => void;
	}

	let { label, options, searchable = false, selected = $bindable([]), allLabel = 'Tous', tooltip, onchange }: Props = $props();
	let showTooltip = $state(false);
	let tooltipTimer: ReturnType<typeof setTimeout>;

	let open = $state(false);
	let filterText = $state('');
	let allMode = $state(true);

	// Sync allMode when selected is set externally (e.g. from URL params)
	$effect(() => {
		if (selected.length > 0 && allMode) {
			allMode = false;
		}
	});

	const instanceId = Symbol();

	const filteredOptions = $derived(
		filterText
			? options.filter((o) => o.text.toLowerCase().includes(filterText.toLowerCase()))
			: options
	);

	const isAllSelected = $derived(allMode && selected.length === 0);

	function toggleAll() {
		if (allMode) {
			// Uncheck "Tous" → uncheck everything visually
			allMode = false;
			selected = [];
			// No onchange: filter doesn't change (empty = no filter)
		} else {
			// Check "Tous" → back to all
			const hadFilter = selected.length > 0;
			allMode = true;
			selected = [];
			if (hadFilter) onchange?.(selected);
		}
	}

	function toggle(value: string) {
		if (allMode) {
			// Was in "all" mode → uncheck this one = select everything except it
			allMode = false;
			selected = options.filter((o) => o.value !== value).map((o) => o.value);
		} else if (selected.includes(value)) {
			selected = selected.filter((v) => v !== value);
			// Don't auto-switch to allMode when empty
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
		<div class="facet-tooltip facet-tooltip-below">{@html tooltip}</div>
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
				{#each filteredOptions as opt (opt.value)}
					<label>
						<input
							type="checkbox"
							checked={isChecked(opt.value)}
							onchange={() => toggle(opt.value)}
						/>
						{opt.text}{#if opt.count != null}<span class="facet-count">{opt.count}</span>{/if}
					</label>
				{/each}
			</div>
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
		background: var(--accent-light);
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
		white-space: nowrap;
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

	.facet-panel {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		min-width: 200px;
		max-height: 320px;
		overflow-y: auto;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
		z-index: 100;
		padding: 6px 0;
	}
	.facet-search {
		display: block;
		width: calc(100% - 12px);
		margin: 2px 6px 6px;
		padding: 5px 8px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.85rem;
	}
	.facet-options label {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 4px 12px;
		font-size: 0.95rem;
		cursor: pointer;
		white-space: nowrap;
	}
	.facet-options label:hover {
		background: #f5f5f2;
	}
	.facet-options input[type='checkbox'] {
		margin: 0;
		flex-shrink: 0;
	}
	.facet-count {
		font-size: 0.8rem;
		color: #888;
		margin-left: auto;
		padding-left: 12px;
	}
</style>
