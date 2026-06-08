<script lang="ts">
	import { base } from '$app/paths';
	import { titleCase } from '$lib/utils';
	import IdentifiersCell from './IdentifiersCell.svelte';

	type Identifier = { value: string; confirmed?: boolean };
	export type PersonRow = {
		id: number;
		first_name: string;
		last_name: string;
		has_rh: boolean;
		role_title: string | null;
		department_name: string | null;
		pub_count: number;
		orcids: Identifier[] | null;
		idhals: Identifier[] | null;
		idrefs: Identifier[] | null;
	};

	let {
		persons,
		sort,
		onSortChange,
	}: {
		persons: PersonRow[];
		sort: string;
		onSortChange: (newSort: string) => void;
	} = $props();

	function toggleSort(col: string) {
		if (sort === col) onSortChange('-' + col);
		else if (sort === '-' + col) onSortChange(col);
		else onSortChange(col);
	}

	function sortIndicator(col: string): string {
		if (sort === col) return ' ▲';
		if (sort === '-' + col) return ' ▼';
		return '';
	}
</script>

<div class="table-scroll">
<table>
	<thead>
		<tr>
			<th
				class="sortable"
				class:active={sort === 'name' || sort === '-name'}
				onclick={() => toggleSort('name')}>Nom{sortIndicator('name')}</th
			>
			<th>Identifiants</th>
			<th
				class="sortable"
				class:active={sort === 'role' || sort === '-role'}
				onclick={() => toggleSort('role')}>Fonction{sortIndicator('role')}</th
			>
			<th
				class="sortable"
				class:active={sort === 'dept' || sort === '-dept'}
				onclick={() => toggleSort('dept')}>Département{sortIndicator('dept')}</th
			>
			<th
				class="sortable num-col"
				style="width:80px"
				class:active={sort === 'pubs' || sort === '-pubs'}
				onclick={() => toggleSort('pubs')}
				>Publications{sortIndicator('pubs')}</th
			>
		</tr>
	</thead>
	<tbody>
		{#if persons.length === 0}
			<tr><td colspan="5" class="no-results">Aucune personne trouvée</td></tr>
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
						<IdentifiersCell
							orcids={p.orcids}
							idhals={p.idhals}
							idrefs={p.idrefs}
						/>
					</td>
					<td>
						{#if p.role_title}
							<span class="role-tag">{p.role_title}</span>
						{/if}
					</td>
					<td class="muted-cell">{p.department_name || ''}</td>
					<td class="num-col">{p.pub_count}</td>
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
		text-transform: uppercase;
		letter-spacing: 0.3px;
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
	.no-results { text-align: center; padding: 24px; color: var(--muted); }
	.person-link { color: var(--accent); text-decoration: none; font-weight: 500; }
	.person-link:hover { text-decoration: underline; }
	.person-last { font-weight: 600; }
	.muted-cell { font-size: 0.9rem; color: var(--muted); }
	.num-col { text-align: right; }
	thead th.num-col { padding-right: 16px; }
</style>
