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
		<button class="btn btn-sm" onclick={onOpen} title="Colonnes affichées" aria-label="Colonnes affichées" aria-expanded={showMenu}>⋯</button>
		{#if showMenu}
			<div class="column-menu popover" use:anchored={{ align: 'end' }}>
				{#each columns as c}
					<label class="option-row" class:disabled={c.fixed}>
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
	.column-menu {
		padding: 6px 0;
		min-width: 150px;
	}
	.column-menu label { white-space: nowrap; }
	.column-menu label.disabled { opacity: 0.5; cursor: default; }
</style>
