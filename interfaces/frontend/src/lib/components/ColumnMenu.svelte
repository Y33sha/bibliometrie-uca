<script lang="ts">
	import type { ColumnDef } from '#lib/composables/useColumnVisibility.svelte.js';
	import { anchored } from '#lib/actions/anchored.js';

	// En-tête de la dernière colonne d'un tableau : son libellé, puis le bouton du menu des colonnes affichées.
	interface Props {
		/** Libellé de la colonne qui accueille le menu. */
		label: string;
		columns: ColumnDef[];
		visibleColumns: string[];
		showMenu: boolean;
		onToggle: (key: string) => void;
		onClose: () => void;
		onOpen: () => void;
	}

	let { label, columns, visibleColumns, showMenu, onToggle, onClose, onOpen }: Props = $props();
</script>

<div class="col-menu-inner">
	<span class="col-menu-label">{label}</span>
	<div class="column-menu-wrapper">
		<button class="column-menu-btn" onclick={onOpen} title="Colonnes affichées">⋯</button>
		{#if showMenu}
			<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
			<div class="column-menu-backdrop" onclick={onClose}></div>
			<div class="column-menu" use:anchored={{ align: 'end' }}>
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
	.col-menu-label { white-space: nowrap; }
	.column-menu-wrapper { position: relative; }
	.column-menu-btn {
		background: none; border: 1px solid var(--border); border-radius: var(--radius);
		padding: 2px 8px; font-size: 1.1rem; cursor: pointer; color: var(--muted);
		letter-spacing: 2px;
	}
	.column-menu-btn:hover { background: var(--hover); color: var(--text); }
	/* Au niveau des autres menus de la page (100). */
	.column-menu-backdrop { position: fixed; inset: 0; z-index: 99; }
	.column-menu {
		background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
		box-shadow: 0 4px 12px rgba(0,0,0,0.1); padding: 6px 0; z-index: 100;
		min-width: 150px;
	}
	.column-menu label {
		display: flex; align-items: center; gap: 6px;
		padding: 4px 12px; font-size: 0.85rem; cursor: pointer; white-space: nowrap;
	}
	.column-menu label:hover { background: var(--hover); }
	.column-menu label.disabled { opacity: 0.5; cursor: default; }
</style>
