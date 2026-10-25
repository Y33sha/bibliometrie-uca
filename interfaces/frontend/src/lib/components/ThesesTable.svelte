<script lang="ts">
	import { asset, resolve } from '$app/paths';
	import { titleCase } from '#lib/utils.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import type { components, operations } from '#lib/api/schema.js';

	// Ligne servie par `/api/publications` (mode thèses) : le sous-ensemble de `PublicationListItem` que ce tableau consomme.
	export type ThesisRow = Pick<
		components['schemas']['PublicationListItem'],
		| 'id'
		| 'title'
		| 'doc_type'
		| 'oa_status'
		| 'hal_id'
		| 'openalex_id'
		| 'scanr_id'
		| 'theses_id'
		| 'record_urls'
		| 'date_soutenance'
		| 'date_inscription'
		| 'thesis_author_name'
		| 'thesis_author_person_id'
		| 'lab_items'
	>;

	// Tri accepté par `/api/publications`.
	export type PublicationSort = NonNullable<
		NonNullable<operations['list_publications_api_publications_get']['parameters']['query']>['sort']
	>;

	let {
		items,
		loading = false,
		sort,
		onToggleSort,
		showLabsColumn = false,
	}: {
		items: ThesisRow[];
		loading?: boolean;
		sort: PublicationSort;
		onToggleSort: (asc: PublicationSort, desc: PublicationSort) => void;
		showLabsColumn?: boolean;
	} = $props();

	const MONTHS = [
		'janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin',
		'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.',
	];

	function formatDate(iso: string | null): { month: string; year: string } | null {
		if (!iso) return null;
		const [y, m] = iso.split('-');
		return { month: MONTHS[parseInt(m, 10) - 1] || '', year: y };
	}

	function sortArrow(asc: PublicationSort, desc: PublicationSort): string {
		return sort === asc ? '▲' : sort === desc ? '▼' : '';
	}
	function sortActive(asc: PublicationSort, desc: PublicationSort): boolean {
		return sort === asc || sort === desc;
	}

	const inscrArrow = $derived(sortArrow('inscription_asc', 'inscription_desc'));
	const inscrActive = $derived(sortActive('inscription_asc', 'inscription_desc'));
	const soutArrow = $derived(sortArrow('soutenance_asc', 'soutenance_desc'));
	const soutActive = $derived(sortActive('soutenance_asc', 'soutenance_desc'));
	const titleArrow = $derived(sortArrow('title_asc', 'title_desc'));
	const titleActive = $derived(sortActive('title_asc', 'title_desc'));
</script>

<div class="table-scroll">
<table class="data-table theses-table">
	<thead>
		<tr>
			<th
				class="col-date sortable"
				class:active={inscrActive}
				onclick={() => onToggleSort('inscription_asc', 'inscription_desc')}
			>Inscription {inscrArrow}</th>
			<th
				class="col-date sortable"
				class:active={soutActive}
				onclick={() => onToggleSort('soutenance_asc', 'soutenance_desc')}
			>Soutenance {soutArrow}</th>
			<th class="col-author">Auteur</th>
			<th
				class="col-title sortable"
				class:active={titleActive}
				onclick={() => onToggleSort('title_asc', 'title_desc')}
			>Titre {titleArrow}</th>
			<th class="col-status">Statut</th>
			{#if showLabsColumn}
				<th class="col-labs">Laboratoire(s)</th>
			{/if}
			<th class="col-oa">OA</th>
			<th class="col-sources">Sources</th>
		</tr>
	</thead>
	<tbody>
		{#if items.length === 0}
			<TableStatusRow {loading} colspan={showLabsColumn ? 8 : 7} emptyText="Aucune thèse" />
		{/if}
		{#each items as t (t.id)}
			{@const insc = formatDate(t.date_inscription)}
			{@const sout = formatDate(t.date_soutenance)}
			<tr>
				<td class="col-date">
					{#if insc}<span class="date-month">{insc.month}</span> {insc.year}{/if}
				</td>
				<td class="col-date">
					{#if sout}<span class="date-month">{sout.month}</span> {sout.year}{/if}
				</td>
				<td class="col-author">
					{#if t.thesis_author_person_id}
						<a href={resolve(`persons/${t.thesis_author_person_id}`)}>{titleCase(t.thesis_author_name)}</a>
					{:else if t.thesis_author_name}
						{titleCase(t.thesis_author_name)}
					{/if}
				</td>
				<td class="col-title">
					<a href={resolve(`publications/${t.id}`)}><PublicationTitle titre={t.title} /></a>
				</td>
				<td class="col-status">
					{#if t.doc_type === 'thesis'}
						<span class="status-badge soutenue">Soutenue</span>
					{:else if t.doc_type === 'ongoing_thesis'}
						<span class="status-badge en-cours">En cours</span>
					{/if}
				</td>
				{#if showLabsColumn}
					<td class="col-labs">
						{#each t.lab_items || [] as lab}
							<a href={resolve(`laboratories/${lab.id}?tab=theses`)} class="lab-tag">{lab.label}</a>
						{/each}
					</td>
				{/if}
				<td class="oa-lock-cell">
					{#if t.doc_type === 'ongoing_thesis'}
						<span class="oa-lock-badge oa-lock-ongoing">
							<img src={asset('hourglass.svg')} alt="En cours" class="oa-lock" title="Thèse en cours" />
							<span class="oa-lock-label">en cours</span>
						</span>
					{:else if t.oa_status && !['unknown', 'closed'].includes(t.oa_status)}
						<span class="oa-lock-badge oa-lock-open">
							<img src={asset('lock-open.svg')} alt="Open Access" class="oa-lock" title="Open Access ({t.oa_status})" />
							<span class="oa-lock-label">ouvert</span>
						</span>
					{:else}
						<span class="oa-lock-badge oa-lock-closed">
							<img src={asset('lock-closed.svg')} alt="Closed" class="oa-lock" title="Accès fermé" />
							<span class="oa-lock-label">fermé</span>
						</span>
					{/if}
				</td>
				<td class="links-cell">
					{#if t.hal_id}
						<a
							href={t.record_urls.hal}
							target="_blank"
							rel="noopener"
							class="source-tag source-hal"
							title="HAL: {t.hal_id}"
						>
							<img src={asset('icons/hal.ico')} alt="HAL" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
					{#if t.openalex_id}
						<a
							href={t.record_urls.openalex}
							target="_blank"
							rel="noopener"
							class="source-tag source-openalex"
							title="OpenAlex: {t.openalex_id}"
						>
							<img src={asset('icons/openalex.png')} alt="OA" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
					{#if t.scanr_id}
						<a
							href={t.record_urls.scanr}
							target="_blank"
							rel="noopener"
							class="source-tag source-scanr"
							title="ScanR: {t.scanr_id}"
						>
							<img src={asset('scanr-icon.svg')} alt="ScanR" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
					{#if t.theses_id}
						<a
							href={t.record_urls.theses}
							target="_blank"
							rel="noopener"
							class="source-tag source-theses"
							title="theses.fr: {t.theses_id}"
						>
							<img src={asset('icons/theses.ico')} alt="theses.fr" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
				</td>
			</tr>
		{/each}
	</tbody>
</table>
</div>

<style>
	.theses-table {
		min-width: 720px;
		font-size: 0.9rem;
	}

	.col-author {
		width: 160px;
		font-size: 0.9rem;
	}
	.col-date {
		width: 85px;
		text-align: center;
		font-size: 0.85rem;
		white-space: nowrap;
	}
	.col-date .date-month {
		font-size: 0.75rem;
		color: var(--muted);
	}
	.col-title {
		min-width: 300px;
	}
	.col-status {
		width: 90px;
		text-align: center;
	}
	.col-labs {
		width: 180px;
	}
	.col-oa {
		width: 75px;
	}
	.col-sources {
		width: 120px;
		text-align: center;
	}

	.status-badge {
		font-size: 0.75rem;
		padding: 2px 6px;
		border-radius: var(--radius);
	}
	.status-badge.soutenue {
		background: var(--success-light);
		color: var(--success);
	}
	.status-badge.en-cours {
		background: var(--attention-light);
		color: var(--attention);
	}
</style>
