<script lang="ts">
	import { base } from '$app/paths';
	import { sanitizeTitle, halDocUrl, scanrPubUrl } from '$lib/utils';

	export type ThesisRow = {
		id: number;
		title: string;
		doc_type: string | null;
		oa_status: string | null;
		hal_id: string | null;
		openalex_id: string | null;
		scanr_id: string | null;
		theses_id: string | null;
		date_soutenance: string | null;
		date_inscription: string | null;
		thesis_author_name: string | null;
		thesis_author_person_id: number | null;
		lab_items?: { id: number; label: string }[] | null;
	};

	let {
		items,
		sort,
		onToggleSort,
		showLabsColumn = false,
	}: {
		items: ThesisRow[];
		sort: string;
		onToggleSort: (asc: string, desc: string) => void;
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

	function sortArrow(asc: string, desc: string): string {
		return sort === asc ? '↑' : sort === desc ? '↓' : '';
	}
	function sortActive(asc: string, desc: string): boolean {
		return sort === asc || sort === desc;
	}

	const inscrArrow = $derived(sortArrow('inscription_asc', 'inscription_desc'));
	const inscrActive = $derived(sortActive('inscription_asc', 'inscription_desc'));
	const soutArrow = $derived(sortArrow('soutenance_asc', 'soutenance_desc'));
	const soutActive = $derived(sortActive('soutenance_asc', 'soutenance_desc'));
	const titleArrow = $derived(sortArrow('title', 'title_desc'));
	const titleActive = $derived(sortActive('title', 'title_desc'));
</script>

<table class="theses-table">
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
				onclick={() => onToggleSort('title', 'title_desc')}
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
						<a href="{base}/persons/{t.thesis_author_person_id}">{t.thesis_author_name}</a>
					{:else if t.thesis_author_name}
						{t.thesis_author_name}
					{/if}
				</td>
				<td class="col-title">
					<a href="{base}/publications/{t.id}">{@html sanitizeTitle(t.title)}</a>
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
							<a href="{base}/laboratories/{lab.id}?tab=theses" class="lab-tag">{lab.label}</a>
						{/each}
					</td>
				{/if}
				<td class="oa-lock-cell">
					{#if t.doc_type === 'ongoing_thesis'}
						<span class="oa-lock-badge oa-lock-ongoing">
							<img src="{base}/hourglass.svg" alt="En cours" class="oa-lock" title="Thèse en cours" />
							<span class="oa-lock-label">en cours</span>
						</span>
					{:else if t.oa_status && !['unknown', 'closed'].includes(t.oa_status)}
						<span class="oa-lock-badge oa-lock-open">
							<img src="{base}/lock-open.svg" alt="Open Access" class="oa-lock" title="Open Access ({t.oa_status})" />
							<span class="oa-lock-label">ouvert</span>
						</span>
					{:else}
						<span class="oa-lock-badge oa-lock-closed">
							<img src="{base}/lock-closed.svg" alt="Closed" class="oa-lock" title="Accès fermé" />
							<span class="oa-lock-label">fermé</span>
						</span>
					{/if}
				</td>
				<td class="links-cell">
					{#if t.hal_id}
						<a
							href={halDocUrl(t.hal_id, t.oa_status)}
							target="_blank"
							rel="noopener"
							class="source-tag source-hal"
							title="HAL: {t.hal_id}"
						>
							<img src="{base}/icons/hal.ico" alt="HAL" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
					{#if t.openalex_id}
						<a
							href="https://openalex.org/{t.openalex_id}"
							target="_blank"
							rel="noopener"
							class="source-tag source-oa"
							title="OpenAlex: {t.openalex_id}"
						>
							<img src="{base}/icons/openalex.png" alt="OA" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
					{#if t.scanr_id}
						<a
							href={scanrPubUrl(t.scanr_id)}
							target="_blank"
							rel="noopener"
							class="source-tag source-scanr"
							title="ScanR: {t.scanr_id}"
						>
							<img src="{base}/scanr-icon.svg" alt="ScanR" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
					{#if t.theses_id}
						<a
							href="https://theses.fr/{t.theses_id}"
							target="_blank"
							rel="noopener"
							class="source-tag source-theses"
							title="theses.fr: {t.theses_id}"
						>
							<img src="https://theses.fr/favicon.ico" alt="theses.fr" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
				</td>
			</tr>
		{/each}
	</tbody>
</table>

<style>
	.theses-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.9rem;
	}
	.theses-table th {
		text-align: left;
		padding: 6px 8px;
		border-bottom: 2px solid var(--border);
		font-size: 0.8rem;
		color: var(--muted);
		text-transform: uppercase;
		background: #f5f4f1;
		white-space: nowrap;
	}
	.theses-table td {
		padding: 5px 8px;
		border-bottom: 1px solid var(--border);
		vertical-align: top;
	}
	.theses-table tbody tr:hover {
		background: var(--hover, #fafaf8);
	}
	.theses-table td a:not(.lab-tag, .source-tag) {
		color: var(--accent);
		text-decoration: none;
	}
	.theses-table td a:not(.lab-tag, .source-tag):hover {
		text-decoration: underline;
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

	.sortable {
		cursor: pointer;
		user-select: none;
	}
	.sortable.active {
		color: var(--accent);
	}

	.status-badge {
		font-size: 0.75rem;
		padding: 2px 6px;
		border-radius: 8px;
	}
	.status-badge.soutenue {
		background: #e8f5e9;
		color: #2e7d32;
	}
	.status-badge.en-cours {
		background: #fff3e0;
		color: #e65100;
	}
</style>
