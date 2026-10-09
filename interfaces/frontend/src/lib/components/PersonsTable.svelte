<script lang="ts">
	import { base } from '$app/paths';
	import { titleCase } from '$lib/utils';
	import IdentifiersCell from './IdentifiersCell.svelte';
	import TableStatusRow from '$lib/components/TableStatusRow.svelte';
	import type { components } from '$lib/api/schema';

	export type PersonRow = components['schemas']['PersonOut'];

	/** Colonne numérique triable, placée après les colonnes descriptives. */
	export interface CountColumn {
		label: string;
		sortKey: string;
		value: (p: PersonRow) => number | null | undefined;
	}

	const AUTHOR_PUBLICATIONS: CountColumn = {
		label: 'Publications',
		sortKey: 'signatures_as_author',
		value: (p) => p.signature_count_as_author
	};

	let {
		persons,
		loading = false,
		sort,
		onSortChange,
		countColumns = [AUTHOR_PUBLICATIONS],
		onopen,
		activeId = null,
	}: {
		persons: PersonRow[];
		loading?: boolean;
		sort: string;
		onSortChange: (newSort: string) => void;
		countColumns?: CountColumn[];
		/** Si fourni, le nom ouvre la personne via ce callback au lieu de lier vers sa fiche. */
		onopen?: (personId: number) => void;
		activeId?: number | null;
	} = $props();

	function toggleSort(col: string) {
		onSortChange(sort === `${col}_asc` ? `${col}_desc` : `${col}_asc`);
	}

	function sortIndicator(col: string): string {
		if (sort === `${col}_asc`) return ' ▲';
		if (sort === `${col}_desc`) return ' ▼';
		return '';
	}
</script>

<div class="table-scroll">
<table>
	<thead>
		<tr>
			<th
				class="sortable"
				class:active={sort === 'name_asc' || sort === 'name_desc'}
				onclick={() => toggleSort('name')}>Nom{sortIndicator('name')}</th
			>
			<th>Identifiants</th>
			<th
				class="sortable"
				class:active={sort === 'role_asc' || sort === 'role_desc'}
				onclick={() => toggleSort('role')}>Fonction{sortIndicator('role')}</th
			>
			<th
				class="sortable"
				class:active={sort === 'dept_asc' || sort === 'dept_desc'}
				onclick={() => toggleSort('dept')}>Département{sortIndicator('dept')}</th
			>
			{#each countColumns as col (col.sortKey)}
				<th
					class="sortable num-col"
					style="width:80px"
					class:active={sort === `${col.sortKey}_asc` || sort === `${col.sortKey}_desc`}
					onclick={() => toggleSort(col.sortKey)}>{col.label}{sortIndicator(col.sortKey)}</th
				>
			{/each}
		</tr>
	</thead>
	<tbody>
		{#if persons.length === 0}
			<TableStatusRow {loading} colspan={4 + countColumns.length} emptyText="Aucune personne trouvée" />
		{:else}
			{#each persons as p (p.id)}
				<tr class:excluded={!!p.exclusion}>
					<td>
						{#if onopen}
							<button
								type="button"
								class="person-link"
								class:active={activeId === p.id}
								onclick={() => onopen(p.id)}
							>
								<span class="person-last">{titleCase(p.last_name)}</span>
								{titleCase(p.first_name)}
							</button>
						{:else}
							<a href="{base}/persons/{p.id}" class="person-link">
								<span class="person-last">{titleCase(p.last_name)}</span>
								{titleCase(p.first_name)}
							</a>
						{/if}
						{#if p.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
					</td>
					<td>
						<IdentifiersCell identifiers={p.identifiers} />
					</td>
					<td>
						{#if p.role_title}
							<span class="role-tag">{p.role_title}</span>
						{/if}
					</td>
					<td class="muted-cell">{p.department_name || ''}</td>
					{#each countColumns as col (col.sortKey)}
						<td class="num-col">{col.value(p) ?? 0}</td>
					{/each}
				</tr>
			{/each}
		{/if}
	</tbody>
</table>
</div>

<style>
	table {
		width: 100%;
		min-width: 620px;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}
	thead th {
		background: var(--surface);
		padding: 9px 12px;
		text-align: left;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
	}
	thead th.sortable { cursor: pointer; user-select: none; }
	thead th.sortable:hover { color: var(--accent); }
	thead th.sortable.active { color: var(--accent); }
	tbody tr { border-bottom: 1px solid var(--border-subtle); }
	tbody tr:last-child { border-bottom: none; }
	tbody tr:hover { background: var(--surface-hover); }
	td { padding: 10px 12px; font-size: 0.95rem; vertical-align: middle; }
	.person-link { color: var(--accent); text-decoration: none; font-weight: 500; }
	.person-link:hover { text-decoration: underline; }
	button.person-link { background: none; border: none; padding: 0; font: inherit; font-weight: 500; text-align: left; cursor: pointer; }
	button.person-link.active { text-decoration: underline; }
	tr.excluded { opacity: 0.45; }
	tr.excluded:hover { opacity: 0.7; }
	tr.excluded .person-link { text-decoration: line-through; }
	.person-last { font-weight: 600; }
	.muted-cell { font-size: 0.9rem; color: var(--muted); }
	.num-col { text-align: right; }
	thead th.num-col { padding-right: 16px; }
</style>
