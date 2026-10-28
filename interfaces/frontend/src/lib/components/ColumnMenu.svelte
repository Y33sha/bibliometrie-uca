<script lang="ts">
	import type { ColumnDef } from '#lib/composables/useColumnVisibility.svelte.js';
	import { anchored } from '#lib/actions/anchored.js';
	import { dismissable } from '#lib/actions/dismissable.js';

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
	<div class="column-menu-wrapper" use:dismissable={() => showMenu && onClose()}>
		<button class="column-menu-btn" onclick={onOpen} title="Colonnes affichées" aria-label="Colonnes affichées" aria-expanded={showMenu}>⋯</button>
		{#if showMenu}
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
		padding: 2px 8px; font-size: var(--fs-lg); cursor: pointer; color: var(--muted);
		letter-spacing: 2px;
	}
	.column-menu-btn:hover { background: var(--hover); color: var(--text); }
	.column-menu {
		background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
		box-shadow: 0 4px 12px rgba(0,0,0,0.1); padding: 6px 0;
		min-width: 150px;
	}
	.column-menu label {
		display: flex; align-items: center; gap: 6px;
		padding: 4px 12px; font-size: var(--fs-sm); cursor: pointer; white-space: nowrap;
	}
	.column-menu label:hover { background: var(--hover); }
	.column-menu label.disabled { opacity: 0.5; cursor: default; }
</style>
