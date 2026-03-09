<script lang="ts">
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { titleCase, sanitizeTitle } from '$lib/utils';
	import { typeLabels as baseTypeLabels } from '$lib/labels';

	const pubId = $derived($page.params.id);
	let canGoBack = $state(false);

	// --- Types ---
	interface PubDetail {
		id: number;
		title: string;
		pub_year: number | null;
		doi: string | null;
		doc_type: string | null;
		oa_status: string | null;
		language: string | null;
		container_title: string | null;
		journal_id: number | null;
		journal_title: string | null;
		issn: string | null;
		eissn: string | null;
		journal_predatory: boolean | null;
		apc_amount: number | null;
		apc_currency: string | null;
		oa_model: string | null;
		publisher_id: number | null;
		publisher_name: string | null;
		publisher_predatory: boolean | null;
	}
	interface Source {
		source: string;
		source_id: string;
		doi: string | null;
		collections: string[] | null;
	}
	interface Authorship {
		author_position: number;
		person_id: number;
		last_name: string;
		first_name: string;
		is_uca: boolean;
		is_corresponding: boolean | null;
		structure_ids: number[] | null;
		source_hal: boolean;
		source_openalex: boolean;
	}
	interface HalAuthorship {
		author_position: number;
		full_name: string;
		person_id: number | null;
		is_uca: boolean;
		structure_ids: number[] | null;
		excluded: boolean;
	}
	interface OaAuthorship {
		author_position: number;
		full_name: string;
		person_id: number | null;
		is_uca: boolean;
		structure_ids: number[] | null;
		raw_affiliation: string | null;
		excluded: boolean;
	}
	interface StructInfo {
		acronym: string | null;
		name: string;
		type: string;
	}
	interface PubResponse {
		publication: PubDetail;
		sources: Source[];
		authorships: Authorship[];
		hal_authorships: HalAuthorship[];
		openalex_authorships: OaAuthorship[];
		structures: Record<string, StructInfo>;
	}

	// --- State ---
	let data: PubResponse | null = $state(null);
	let error = $state(false);

	const pub = $derived(data?.publication);
	const hasTruthTable = $derived((data?.authorships.length ?? 0) > 0);

	const typeLabels: Record<string, string> = { ...baseTypeLabels, conference_paper: 'Communication' };

	const langLabels: Record<string, string> = {
		en: 'anglais', fr: 'français', de: 'allemand', es: 'espagnol', it: 'italien', pt: 'portugais'
	};

	function structLabel(id: number): string {
		const s = data?.structures[String(id)];
		return s ? (s.acronym || s.name) : `#${id}`;
	}

	function structIsLabo(id: number): boolean {
		return data?.structures[String(id)]?.type === 'labo';
	}

	function personName(last: string, first: string): string {
		return `${titleCase(first)} ${titleCase(last)}`;
	}

	const halSource = $derived(data?.sources.find(s => s.source === 'hal'));
	const oaSource = $derived(data?.sources.find(s => s.source === 'openalex'));

	onMount(async () => {
		canGoBack = (window.navigation?.canGoBack ?? document.referrer.startsWith(window.location.origin));
		try {
			data = await api<PubResponse>(`/api/publications/${pubId}`);
		} catch {
			error = true;
		}
	});
</script>

<svelte:head>
	<title>{pub?.title ? pub.title.slice(0, 80) : 'Publication'} — Bibliométrie UCA</title>
</svelte:head>

{#if canGoBack}
<!-- svelte-ignore a11y_invalid_attribute -->
<a href="#" class="back-link" onclick={(e) => { e.preventDefault(); history.back(); }}>&larr; Retour</a>
{/if}

{#if error}
	<div class="pub-header"><div class="no-results">Publication introuvable</div></div>
{:else if !pub}
	<div class="pub-header"><div class="loading">Chargement...</div></div>
{:else}
	<!-- Header -->
	<div class="pub-header">
		<h1 class="pub-title-main">{@html sanitizeTitle(pub.title)}</h1>
		<div class="pub-meta">
			{#if pub.pub_year}<span class="meta-badge">{pub.pub_year}</span>{/if}
			{#if pub.doc_type}
				<span class="meta-badge type-badge">{typeLabels[pub.doc_type] || pub.doc_type}</span>
			{/if}
			{#if pub.oa_status && pub.oa_status !== 'unknown'}
				<span class="oa-tag oa-{pub.oa_status}">{pub.oa_status}</span>
			{/if}
			{#if pub.language}
				<span class="meta-badge lang-badge">{langLabels[pub.language] || pub.language}</span>
			{/if}
		</div>

		<!-- Journal / Publisher -->
		{#if pub.journal_title || pub.container_title}
			<div class="pub-journal-line">
				<span class="journal-name">{pub.journal_title || pub.container_title}</span>
				{#if pub.issn}
					<span class="issn">ISSN {pub.issn}</span>
				{/if}
				{#if pub.publisher_name}
					<span class="publisher-name">— {pub.publisher_name}</span>
				{/if}
				{#if pub.journal_predatory}
					<span class="predatory-badge">Revue prédatrice</span>
				{/if}
				{#if pub.publisher_predatory && !pub.journal_predatory}
					<span class="predatory-badge">Éditeur prédateur</span>
				{/if}
				{#if pub.oa_model}
					<span class="meta-badge">{pub.oa_model}</span>
				{/if}
			</div>
		{/if}

		<!-- DOI -->
		{#if pub.doi}
			<div class="pub-doi">
				<span class="doi-label">DOI</span>
				<a href="https://doi.org/{pub.doi}" target="_blank" rel="noopener">{pub.doi}</a>
			</div>
		{/if}

		<!-- Sources -->
		<div class="pub-sources">
			{#if halSource}
				<a href="https://hal.science/{halSource.source_id}" target="_blank" rel="noopener" class="source-link source-hal-link">
					<img src="https://hal.science/favicon.ico" alt="" class="source-ico" />
					HAL : {halSource.source_id}
				</a>
			{/if}
			{#if oaSource}
				<a href="https://openalex.org/{oaSource.source_id}" target="_blank" rel="noopener" class="source-link source-oa-link">
					<img src="https://raw.githubusercontent.com/ourresearch/openalex-gui/refs/heads/master/public/favicon.png" alt="" class="source-ico" />
					OpenAlex : {oaSource.source_id}
				</a>
			{/if}
		</div>

		<!-- HAL Collections -->
		{#if halSource?.collections && halSource.collections.length > 0}
			<div class="collections-line">
				<span class="collections-label">Collections HAL :</span>
				{#each halSource.collections as col}
					<span class="collection-tag">{col}</span>
				{/each}
			</div>
		{/if}
	</div>

	<!-- Authorships - Truth table -->
	{#if hasTruthTable}
		<div class="section">
			<h2 class="section-title">Auteurs ({data.authorships.length})</h2>
			<table class="auth-table">
				<thead>
					<tr>
						<th style="width:30px">#</th>
						<th>Auteur</th>
						<th>Structures</th>
						<th style="width:50px">Corr.</th>
						<th style="width:70px">Sources</th>
					</tr>
				</thead>
				<tbody>
					{#each data.authorships as a (a.author_position)}
						<tr class:uca-row={a.is_uca}>
							<td class="pos-cell">{(a.author_position ?? 0) + 1}</td>
							<td>
								<a href="{base}/persons/{a.person_id}" class="author-link">
									{personName(a.last_name, a.first_name)}
								</a>
							</td>
							<td>
								{#if a.structure_ids}
									{#each a.structure_ids as sid}
										{#if structIsLabo(sid)}
											<a href="{base}/laboratories/{sid}" class="struct-tag">{structLabel(sid)}</a>
										{:else}
											<span class="struct-tag">{structLabel(sid)}</span>
										{/if}
									{/each}
								{/if}
							</td>
							<td class="center-cell">
								{#if a.is_corresponding}
									<span title="Auteur correspondant">✉</span>
								{/if}
							</td>
							<td class="sources-cell">
								{#if a.source_hal}
									<span class="source-tag-label source-hal-label">H</span>
								{/if}
								{#if a.source_openalex}
									<span class="source-tag-label source-oa-label">OA</span>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	<!-- Source details -->
	{#if data.hal_authorships.length > 0}
		<details class="source-details" open={!hasTruthTable}>
			<summary>Auteurs HAL ({data.hal_authorships.length})</summary>
			<table class="auth-table">
				<thead>
					<tr>
						<th style="width:30px">#</th>
						<th>Auteur</th>
						<th style="width:40px">UCA</th>
						<th>Structures</th>
					</tr>
				</thead>
				<tbody>
					{#each data.hal_authorships as a (a.author_position)}
						<tr class:excluded-row={a.excluded} class:uca-row={a.is_uca && !a.excluded}>
							<td class="pos-cell">{(a.author_position ?? 0) + 1}</td>
							<td>
								{#if a.person_id}
									<a href="{base}/persons/{a.person_id}" class="author-link">{a.full_name}</a>
								{:else}
									<span class:excluded-text={a.excluded}>{a.full_name}</span>
								{/if}
							</td>
							<td class="center-cell">
								{#if a.is_uca}
									<span class="uca-dot" title="UCA">●</span>
								{/if}
							</td>
							<td>
								{#if a.structure_ids}
									{#each a.structure_ids as sid}
										{#if structIsLabo(sid)}
											<a href="{base}/laboratories/{sid}" class="struct-tag">{structLabel(sid)}</a>
										{:else}
											<span class="struct-tag">{structLabel(sid)}</span>
										{/if}
									{/each}
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</details>
	{/if}

	{#if data.openalex_authorships.length > 0}
		<details class="source-details" open={!hasTruthTable}>
			<summary>Auteurs OpenAlex ({data.openalex_authorships.length})</summary>
			<table class="auth-table">
				<thead>
					<tr>
						<th style="width:30px">#</th>
						<th>Auteur</th>
						<th style="width:40px">UCA</th>
						<th>Structures</th>
						<th>Affiliation brute</th>
					</tr>
				</thead>
				<tbody>
					{#each data.openalex_authorships as a (a.author_position)}
						<tr class:excluded-row={a.excluded} class:uca-row={a.is_uca && !a.excluded}>
							<td class="pos-cell">{(a.author_position ?? 0) + 1}</td>
							<td>
								{#if a.person_id}
									<a href="{base}/persons/{a.person_id}" class="author-link">{a.full_name}</a>
								{:else}
									<span class:excluded-text={a.excluded}>{a.full_name}</span>
								{/if}
							</td>
							<td class="center-cell">
								{#if a.is_uca}
									<span class="uca-dot" title="UCA">●</span>
								{/if}
							</td>
							<td>
								{#if a.structure_ids}
									{#each a.structure_ids as sid}
										{#if structIsLabo(sid)}
											<a href="{base}/laboratories/{sid}" class="struct-tag">{structLabel(sid)}</a>
										{:else}
											<span class="struct-tag">{structLabel(sid)}</span>
										{/if}
									{/each}
								{/if}
							</td>
							<td class="affiliation-cell">{a.raw_affiliation || ''}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</details>
	{/if}
{/if}

<style>
	.back-link {
		display: inline-block;
		margin-bottom: 12px;
		font-size: 13px;
		color: var(--accent);
		text-decoration: none;
	}
	.back-link:hover { text-decoration: underline; }

	/* Header */
	.pub-header {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 20px 24px;
		margin-bottom: 16px;
	}
	.pub-title-main {
		font-size: 18px;
		font-weight: 600;
		margin: 0 0 10px;
		line-height: 1.4;
	}
	.pub-meta {
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
		margin-bottom: 10px;
	}
	.meta-badge {
		display: inline-block;
		padding: 2px 8px;
		background: #f0efec;
		border-radius: 3px;
		font-size: 12px;
		color: var(--muted);
		font-weight: 500;
	}
	.type-badge { background: #e8f0f8; color: var(--accent); }
	.lang-badge { background: #f5f0fa; color: #7c5ca7; }

	.oa-tag {
		display: inline-block;
		font-size: 11px;
		padding: 2px 8px;
		border-radius: 8px;
		font-weight: 600;
	}
	:global(.oa-gold) { background: #fef3e0; color: #d4a017; }
	:global(.oa-hybrid) { background: #f3eef9; color: #8e6bbf; }
	:global(.oa-green) { background: #e6f4ec; color: #2a7d4f; }
	:global(.oa-bronze) { background: #fdf0e6; color: #b8733e; }
	:global(.oa-closed) { background: #e0e0e0; color: #555; }

	.pub-journal-line {
		display: flex;
		gap: 10px;
		align-items: center;
		flex-wrap: wrap;
		font-size: 13px;
		margin-bottom: 8px;
	}
	.journal-name { font-weight: 500; color: var(--text); }
	.issn { font-size: 12px; color: var(--muted); }
	.publisher-name { font-size: 12px; color: var(--muted); }
	.predatory-badge {
		display: inline-block;
		padding: 2px 8px;
		background: #fde8e8;
		border-radius: 3px;
		font-size: 11px;
		font-weight: 600;
		color: #c0392b;
	}
	.pub-doi {
		display: flex;
		gap: 6px;
		align-items: center;
		font-size: 13px;
		margin-bottom: 8px;
	}
	.doi-label { font-weight: 500; color: var(--muted); font-size: 12px; }
	.pub-doi a { color: var(--accent); text-decoration: none; }
	.pub-doi a:hover { text-decoration: underline; }

	.pub-sources {
		display: flex;
		gap: 14px;
		flex-wrap: wrap;
		margin-bottom: 6px;
	}
	.source-link {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 3px 10px;
		border-radius: 4px;
		font-size: 12px;
		text-decoration: none;
		font-weight: 500;
	}
	.source-hal-link { background: #e8f0f8; color: #3b6b9e; }
	.source-hal-link:hover { background: #d0e3f4; }
	.source-oa-link { background: #fef3e0; color: #b8733e; }
	.source-oa-link:hover { background: #fde8c8; }
	.source-ico { width: 14px; height: 14px; }

	.collections-line {
		display: flex;
		gap: 6px;
		align-items: center;
		flex-wrap: wrap;
		font-size: 12px;
		margin-top: 6px;
	}
	.collections-label { color: var(--muted); font-weight: 500; }
	.collection-tag {
		display: inline-block;
		padding: 1px 6px;
		background: #f0efec;
		border-radius: 3px;
		font-size: 11px;
		color: var(--muted);
	}

	/* Sections */
	.section {
		margin-bottom: 16px;
	}
	.section-title {
		font-size: 15px;
		font-weight: 600;
		margin: 0 0 8px;
	}

	/* Auth tables */
	.auth-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}
	.auth-table thead th {
		background: #f5f4f1;
		padding: 8px 10px;
		text-align: left;
		font-size: 12px;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.auth-table tbody tr { border-bottom: 1px solid #f0efec; }
	.auth-table tbody tr:last-child { border-bottom: none; }
	.auth-table tbody tr:hover { background: #fafaf8; }
	.auth-table td {
		padding: 6px 10px;
		font-size: 13px;
		vertical-align: middle;
	}

	.pos-cell { text-align: center; color: var(--muted); font-size: 12px; }
	.center-cell { text-align: center; }

	.author-link { color: var(--accent); text-decoration: none; }
	.author-link:hover { text-decoration: underline; }

	.struct-tag {
		display: inline-block;
		padding: 1px 6px;
		background: #e8f0f8;
		border-radius: 3px;
		font-size: 11px;
		color: var(--accent);
		font-weight: 500;
		margin-right: 3px;
		text-decoration: none;
	}
	a.struct-tag:hover { background: #d0e3f4; }

	.uca-dot { color: #2a7d4f; font-size: 10px; }
	.uca-row { background: #f8fcf9; }

	.sources-cell { white-space: nowrap; }
	.source-tag-label {
		display: inline-block;
		padding: 1px 5px;
		border-radius: 3px;
		font-size: 10px;
		font-weight: 600;
		margin-right: 2px;
	}
	.source-hal-label { background: #e8f0f8; color: #3b6b9e; }
	.source-oa-label { background: #fef3e0; color: #b8733e; }

	.excluded-row { opacity: 0.5; }
	.excluded-text { text-decoration: line-through; }

	.affiliation-cell {
		font-size: 11px;
		color: var(--muted);
		max-width: 400px;
		word-break: break-word;
	}

	/* Source details */
	.source-details {
		margin-bottom: 16px;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}
	.source-details summary {
		padding: 10px 14px;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
		background: #f5f4f1;
		border-bottom: 1px solid var(--border);
		user-select: none;
	}
	.source-details summary:hover { background: #eae9e5; }
	.source-details[open] > summary { margin-bottom: 0; }
	.source-details .auth-table {
		border: none;
		border-radius: 0;
	}

	.no-results { text-align: center; padding: 40px; color: var(--muted); }
	.loading { text-align: center; padding: 40px; color: var(--muted); }
</style>
