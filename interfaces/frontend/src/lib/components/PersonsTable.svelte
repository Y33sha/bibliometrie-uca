<script lang="ts">
	import { base } from '$app/paths';
	import { titleCase } from '$lib/utils';
	import IdentifiersCell from './IdentifiersCell.svelte';
	import TableStatusRow from '$lib/components/TableStatusRow.svelte';
	import type { components } from '$lib/api/schema';

	export type PersonRow = components['schemas']['PersonOut'];

	let {
		persons,
		loading = false,
		sort,
		onSortChange,
	}: {
		persons: PersonRow[];
		loading?: boolean;
		sort: string;
		onSortChange: (newSort: string) => void;
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
			<th
				class="sortable num-col"
				style="width:80px"
				class:active={sort === 'signatures_as_author_asc' || sort === 'signatures_as_author_desc'}
				onclick={() => toggleSort('signatures_as_author')}
				>Publications{sortIndicator('signatures_as_author')}</th
			>
		</tr>
	</thead>
	<tbody>
		{#if persons.length === 0}
			<TableStatusRow {loading} colspan={5} emptyText="Aucune personne trouvée" />
		{:else}
			{#each persons as p (p.id)}
				<tr>
					<td>
						<a href="{base}/persons/{p.id}" class="person-link">
							<span class="person-last">{titleCase(p.last_name)}</span>
							{titleCase(p.first_name)}
						</a>
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
					<td class="num-col">{p.signature_count_as_author}</td>
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
	.person-last { font-weight: 600; }
	.muted-cell { font-size: 0.9rem; color: var(--muted); }
	.num-col { text-align: right; }
	thead th.num-col { padding-right: 16px; }
</style>
