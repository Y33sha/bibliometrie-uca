<script lang="ts">
	import type { ColumnDef } from '$lib/composables/useColumnVisibility.svelte';

	interface Props {
		columns: ColumnDef[];
		visibleColumns: string[];
		showMenu: boolean;
		onToggle: (key: string) => void;
		onClose: () => void;
		onOpen: () => void;
	}

	let { columns, visibleColumns, showMenu, onToggle, onClose, onOpen }: Props = $props();

	// Le tableau vit dans un conteneur `.table-scroll` en `overflow-x: auto` : son
	// `overflow-y` calculé vaut `auto`, ce qui rognerait un dropdown en position
	// absolue. On l'ancre donc en position fixe sur le bouton (recalculée à chaque
	// ouverture), pour qu'il déborde librement sous le tableau.
	let btnEl: HTMLButtonElement | undefined = $state();
	let menuPos = $state({ top: 0, right: 0 });

	$effect(() => {
		if (showMenu && btnEl) {
			const r = btnEl.getBoundingClientRect();
			menuPos = { top: r.bottom + 4, right: window.innerWidth - r.right };
		}
	});
</script>

<div class="col-menu-inner">
	<span>Liens</span>
	<div class="column-menu-wrapper">
		<button bind:this={btnEl} class="column-menu-btn" onclick={onOpen} title="Colonnes affichées">⋯</button>
		{#if showMenu}
			<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
			<div class="column-menu-backdrop" onclick={onClose}></div>
			<div class="column-menu" style="top: {menuPos.top}px; right: {menuPos.right}px;">
				{#each columns as c}
					<label class:disabled={c.fixed}>
						<input type="checkbox" checked={visibleColumns.includes(c.key)}
							disabled={c.fixed}
							onchange={() => onToggle(c.key)} />
						{c.label}
					</label>
				{/each}
			</div>
		{/if}
	</div>
</div>

<style>
	.col-menu-inner { display: flex; align-items: center; justify-content: space-between; gap: 4px; }
	.column-menu-wrapper { position: relative; }
	.column-menu-btn {
		background: none; border: 1px solid var(--border); border-radius: 4px;
		padding: 2px 8px; font-size: 1.1rem; cursor: pointer; color: var(--muted);
		letter-spacing: 2px;
	}
	.column-menu-btn:hover { background: var(--hover); color: var(--fg); }
	.column-menu-backdrop { position: fixed; inset: 0; z-index: 9; }
	.column-menu {
		position: fixed;
		background: var(--card); border: 1px solid var(--border); border-radius: 6px;
		box-shadow: 0 4px 12px rgba(0,0,0,0.1); padding: 6px 0; z-index: 11;
		min-width: 150px;
	}
	.column-menu label {
		display: flex; align-items: center; gap: 6px;
		padding: 4px 12px; font-size: 0.85rem; cursor: pointer; white-space: nowrap;
	}
	.column-menu label:hover { background: var(--hover); }
	.column-menu label.disabled { opacity: 0.5; cursor: default; }
</style>
