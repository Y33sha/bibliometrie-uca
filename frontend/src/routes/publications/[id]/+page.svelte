<script lang="ts">
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { titleCase, sanitizeTitle } from '$lib/utils';
	import { typeLabels as baseTypeLabels } from '$lib/labels';
	import Tooltip from '$lib/components/Tooltip.svelte';

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
		countries: string[] | null;
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
		source_wos: boolean;
	}
	interface SourceAuthorship {
		id: number;
		author_position: number;
		full_name: string;
		person_id: number | null;
		is_uca: boolean;
		structure_ids: number[] | null;
		raw_affiliation: string | null;
		excluded: boolean;
		countries: string[] | null;
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
		hal_authorships: SourceAuthorship[];
		openalex_authorships: SourceAuthorship[];
		wos_authorships: SourceAuthorship[];
		structures: Record<string, StructInfo>;
	}

	// --- Source comparison ---
	interface SourceRow {
		position: number;
		hal: SourceAuthorship | null;
		oa: SourceAuthorship | null;
		wos: SourceAuthorship | null;
		conflict: boolean;
	}

	// --- State ---
	let data: PubResponse | null = $state(null);
	let error = $state(false);
	let isAdmin = $state(false);

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

	async function toggleExclude(source: string, a: SourceAuthorship) {
		const newExcluded = !a.excluded;
		await fetch(`${base}/api/source-authorships/${source}/${a.id}/exclude`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ excluded: newExcluded })
		});
		// Recharger la page
		await loadData();
	}

	function structsTooltip(a: SourceAuthorship): string {
		const parts: string[] = [];
		if (a.structure_ids) {
			parts.push(a.structure_ids.map(sid => structLabel(sid)).join(', '));
		}
		if (a.raw_affiliation) {
			parts.push(a.raw_affiliation);
		}
		return parts.join('\n') || '';
	}

	const halSource = $derived(data?.sources.find(s => s.source === 'hal'));
	const oaSource = $derived(data?.sources.find(s => s.source === 'openalex'));
	const wosSource = $derived(data?.sources.find(s => s.source === 'wos'));

	// Nombre de sources présentes
	const sourceCount = $derived(
		(data?.hal_authorships.length ? 1 : 0) +
		(data?.openalex_authorships.length ? 1 : 0) +
		(data?.wos_authorships.length ? 1 : 0)
	);

	// Grille alignée par position
	const sourceRows = $derived.by(() => {
		if (!data) return [];
		const halMap = new Map<number, SourceAuthorship>();
		const oaMap = new Map<number, SourceAuthorship>();
		const wosMap = new Map<number, SourceAuthorship>();
		for (const a of data.hal_authorships) halMap.set(a.author_position, a);
		for (const a of data.openalex_authorships) oaMap.set(a.author_position, a);
		for (const a of data.wos_authorships) wosMap.set(a.author_position, a);

		const allPos = new Set([...halMap.keys(), ...oaMap.keys(), ...wosMap.keys()]);
		const rows: SourceRow[] = [];
		for (const pos of [...allPos].sort((a, b) => a - b)) {
			const hal = halMap.get(pos) ?? null;
			const oa = oaMap.get(pos) ?? null;
			const wos = wosMap.get(pos) ?? null;
			const entries = [hal, oa, wos].filter((x): x is SourceAuthorship => x !== null);
			const activeEntries = entries.filter(e => !e.excluded);

			let conflict = false;
			// Conflit : auteur UCA dans une source mais absent d'une autre source présente
			const ucaEntries = activeEntries.filter(e => e.is_uca);
			if (ucaEntries.length > 0) {
				if ((hal === null || hal.excluded) && data.hal_authorships.some(a => !a.excluded) && ucaEntries.length > 0) conflict = true;
				if ((oa === null || oa.excluded) && data.openalex_authorships.some(a => !a.excluded) && ucaEntries.length > 0) conflict = true;
				if ((wos === null || wos.excluded) && data.wos_authorships.some(a => !a.excluded) && ucaEntries.length > 0) conflict = true;
			}
			// Conflit : deux personnes résolues différentes
			const personIds = activeEntries.filter(e => e.person_id !== null).map(e => e.person_id!);
			if (new Set(personIds).size > 1) conflict = true;
			// Conflit : auteur UCA résolu aligné avec auteur non résolu
			if (ucaEntries.some(e => e.person_id !== null) && activeEntries.some(e => e.person_id === null)) conflict = true;

			rows.push({ position: pos, hal, oa, wos, conflict });
		}
		return rows;
	});

	const hasSourceConflict = $derived(sourceRows.some(r => r.conflict));

	async function loadData() {
		data = await api<PubResponse>(`/api/publications/${pubId}`);
	}

	onMount(async () => {
		canGoBack = (window.navigation?.canGoBack ?? document.referrer.startsWith(window.location.origin));
		fetch(base + '/api/auth/check').then(r => r.json()).then(d => { isAdmin = !!d.authenticated; }).catch(() => {});
		try {
			await loadData();
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
			{#if wosSource}
				<a href="https://www.webofscience.com/wos/woscc/full-record/{wosSource.source_id}" target="_blank" rel="noopener" class="source-link source-wos-link">
					WoS : {wosSource.source_id}
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
					{#each data.authorships as a, i (i)}
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
								{#if a.source_wos}
									<span class="source-tag-label source-wos-label">W</span>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	<!-- Source comparison -->
	{#if sourceCount > 1}
		<details class="source-details">
			<summary class:source-conflict={hasSourceConflict} class:source-ok={!hasSourceConflict}>
				{#if hasSourceConflict}
					<span class="status-icon conflict-icon">!</span> Conflit entre sources
				{:else}
					<span class="status-icon ok-icon">&#10003;</span> Sources cohérentes
				{/if}
				<span class="source-summary-count">
					({sourceRows.length} auteurs &mdash;
					{#if halSource}H{/if}{#if oaSource}{halSource ? '/' : ''}OA{/if}{#if wosSource}{halSource || oaSource ? '/' : ''}W{/if})
				</span>
			</summary>
			<div class="source-grid-wrap">
				<table class="source-grid">
					<thead>
						<tr>
							{#if halSource}
								<th class="sg-pos">#</th>
								<th class="sg-name">HAL</th>
							{/if}
							{#if oaSource}
								<th class="sg-pos">#</th>
								<th class="sg-name">OpenAlex</th>
							{/if}
							{#if wosSource}
								<th class="sg-pos">#</th>
								<th class="sg-name">WoS</th>
							{/if}
						</tr>
					</thead>
					<tbody>
						<!-- Ligne pays -->
						<tr class="countries-row">
							{#if halSource}
								<td class="sg-pos-cell"></td>
								<td class="sg-name-cell countries-cell">{(halSource.countries || []).map(c => c.toUpperCase()).join(' ')}</td>
							{/if}
							{#if oaSource}
								<td class="sg-pos-cell"></td>
								<td class="sg-name-cell countries-cell">{(oaSource.countries || []).map(c => c.toUpperCase()).join(' ')}</td>
							{/if}
							{#if wosSource}
								<td class="sg-pos-cell"></td>
								<td class="sg-name-cell countries-cell">{(wosSource.countries || []).map(c => c.toUpperCase()).join(' ')}</td>
							{/if}
						</tr>
						{#each sourceRows as row, i (row.position)}
							<tr class:conflict-row={row.conflict}>
								{#if halSource}
									<td class="sg-pos-cell">{#if row.hal}{row.position + 1}{/if}</td>
									<td class="sg-name-cell" class:sg-excluded={row.hal?.excluded}>
										{#if row.hal}
											{#if isAdmin}<button class="exclude-btn" title={row.hal.excluded ? 'Rétablir' : 'Marquer comme faux'} onclick={() => toggleExclude('hal', row.hal!)}>{row.hal.excluded ? '↩' : '×'}</button>{/if}
											{#if row.hal.person_id}
												<a href="{base}/persons/{row.hal.person_id}" class="sg-author-link" class:sg-uca={row.hal.is_uca}>
													{row.hal.full_name}
												</a>
											{:else}
												<span class="sg-author" class:sg-uca={row.hal.is_uca}>
													{row.hal.full_name}
												</span>
											{/if}
											{#if structsTooltip(row.hal)}
												<Tooltip text={structsTooltip(row.hal)}><span class="info-icon">&#9432;</span></Tooltip>
											{/if}
											{#if row.hal.countries}
												<span class="author-countries">{row.hal.countries.map(c => c.toUpperCase()).join(' ')}</span>
											{/if}
										{/if}
									</td>
								{/if}
								{#if oaSource}
									<td class="sg-pos-cell">{#if row.oa}{row.position + 1}{/if}</td>
									<td class="sg-name-cell" class:sg-excluded={row.oa?.excluded}>
										{#if row.oa}
											{#if isAdmin}<button class="exclude-btn" title={row.oa.excluded ? 'Rétablir' : 'Marquer comme faux'} onclick={() => toggleExclude('openalex', row.oa!)}>{row.oa.excluded ? '↩' : '×'}</button>{/if}
											{#if row.oa.person_id}
												<a href="{base}/persons/{row.oa.person_id}" class="sg-author-link" class:sg-uca={row.oa.is_uca}>
													{row.oa.full_name}
												</a>
											{:else}
												<span class="sg-author" class:sg-uca={row.oa.is_uca}>
													{row.oa.full_name}
												</span>
											{/if}
											{#if structsTooltip(row.oa)}
												<Tooltip text={structsTooltip(row.oa)}><span class="info-icon">&#9432;</span></Tooltip>
											{/if}
											{#if row.oa.countries}
												<span class="author-countries">{row.oa.countries.map(c => c.toUpperCase()).join(' ')}</span>
											{/if}
										{/if}
									</td>
								{/if}
								{#if wosSource}
									<td class="sg-pos-cell">{#if row.wos}{row.position + 1}{/if}</td>
									<td class="sg-name-cell" class:sg-excluded={row.wos?.excluded}>
										{#if row.wos}
											{#if isAdmin}<button class="exclude-btn" title={row.wos.excluded ? 'Rétablir' : 'Marquer comme faux'} onclick={() => toggleExclude('wos', row.wos!)}>{row.wos.excluded ? '↩' : '×'}</button>{/if}
											{#if row.wos.person_id}
												<a href="{base}/persons/{row.wos.person_id}" class="sg-author-link" class:sg-uca={row.wos.is_uca}>
													{row.wos.full_name}
												</a>
											{:else}
												<span class="sg-author" class:sg-uca={row.wos.is_uca}>
													{row.wos.full_name}
												</span>
											{/if}
											{#if structsTooltip(row.wos)}
												<Tooltip text={structsTooltip(row.wos)}><span class="info-icon">&#9432;</span></Tooltip>
											{/if}
											{#if row.wos.countries}
												<span class="author-countries">{row.wos.countries.map(c => c.toUpperCase()).join(' ')}</span>
											{/if}
										{/if}
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</details>
	{:else if sourceCount === 1}
		{@const singleSource = halSource ? 'hal' : oaSource ? 'openalex' : 'wos'}
		{@const singleRows = halSource ? data!.hal_authorships : oaSource ? data!.openalex_authorships : data!.wos_authorships}
		{@const singleLabel = halSource ? 'HAL' : oaSource ? 'OpenAlex' : 'WoS'}
		<div class="section">
			<h2 class="section-title">Auteurs — source {singleLabel} ({singleRows.filter(a => !a.excluded).length})</h2>
			<table class="auth-table">
				<thead>
					<tr>
						<th style="width:30px">#</th>
						<th>Auteur</th>
						<th>Affiliations</th>
					</tr>
				</thead>
				<tbody>
					{#each singleRows as a}
						<tr class:uca-row={a.is_uca && !a.excluded} class:sg-excluded={a.excluded}>
							<td class="pos-cell">{(a.author_position ?? 0) + 1}</td>
							<td>
								{#if isAdmin}<button class="exclude-btn" title={a.excluded ? 'Rétablir' : 'Marquer comme faux'} onclick={() => toggleExclude(singleSource, a)}>{a.excluded ? '↩' : '×'}</button>{/if}
								{#if a.person_id}
									<a href="{base}/persons/{a.person_id}" class="author-link">
										{a.full_name}
									</a>
								{:else}
									<span>{a.full_name}</span>
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
								{#if a.raw_affiliation}
									<span class="raw-affil">{a.raw_affiliation}</span>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
{/if}

<style>
	.back-link {
		display: inline-block;
		margin-bottom: 12px;
		font-size: 0.95rem;
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
		font-size: 1.3rem;
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
		font-size: 0.85rem;
		color: var(--muted);
		font-weight: 500;
	}
	.type-badge { background: #e8f0f8; color: var(--accent); }
	.lang-badge { background: #f5f0fa; color: #7c5ca7; }

	.oa-tag {
		display: inline-block;
		font-size: 0.8rem;
		padding: 2px 8px;
		border-radius: 8px;
		font-weight: 600;
	}
	:global(.oa-gold) { background: #fef3e0; color: #d4a017; }
	:global(.oa-diamond) { background: #e0f2f7; color: #0288a8; }
	:global(.oa-hybrid) { background: #f3eef9; color: #8e6bbf; }
	:global(.oa-green) { background: #e6f4ec; color: #2a7d4f; }
	:global(.oa-bronze) { background: #fdf0e6; color: #b8733e; }
	:global(.oa-closed) { background: #e0e0e0; color: #555; }

	.pub-journal-line {
		display: flex;
		gap: 10px;
		align-items: center;
		flex-wrap: wrap;
		font-size: 0.95rem;
		margin-bottom: 8px;
	}
	.journal-name { font-weight: 500; color: var(--text); }
	.issn { font-size: 0.85rem; color: var(--muted); }
	.publisher-name { font-size: 0.85rem; color: var(--muted); }
	.predatory-badge {
		display: inline-block;
		padding: 2px 8px;
		background: #fde8e8;
		border-radius: 3px;
		font-size: 0.8rem;
		font-weight: 600;
		color: #c0392b;
	}
	.pub-doi {
		display: flex;
		gap: 6px;
		align-items: center;
		font-size: 0.95rem;
		margin-bottom: 8px;
	}
	.doi-label { font-weight: 500; color: var(--muted); font-size: 0.85rem; }
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
		font-size: 0.85rem;
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
		font-size: 0.85rem;
		margin-top: 6px;
	}
	.collections-label { color: var(--muted); font-weight: 500; }
	.collection-tag {
		display: inline-block;
		padding: 1px 6px;
		background: #f0efec;
		border-radius: 3px;
		font-size: 0.8rem;
		color: var(--muted);
	}

	/* Sections */
	.section {
		margin-bottom: 16px;
	}
	.section-title {
		font-size: 1.05rem;
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
		font-size: 0.85rem;
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
		font-size: 0.95rem;
		vertical-align: middle;
	}

	.pos-cell { text-align: center; color: var(--muted); font-size: 0.85rem; }
	.center-cell { text-align: center; }

	.author-link { color: var(--accent); text-decoration: none; }
	.author-link:hover { text-decoration: underline; }

	.struct-tag {
		display: inline-block;
		padding: 1px 6px;
		background: #e8f0f8;
		border-radius: 3px;
		font-size: 0.8rem;
		color: var(--accent);
		font-weight: 500;
		margin-right: 3px;
		text-decoration: none;
	}
	a.struct-tag:hover { background: #d0e3f4; }

	.uca-dot { color: #2a7d4f; font-size: 0.7rem; }
	.uca-row { background: #f8fcf9; }

	.sources-cell { white-space: nowrap; }
	.source-tag-label {
		display: inline-block;
		padding: 1px 5px;
		border-radius: 3px;
		font-size: 0.7rem;
		font-weight: 600;
		margin-right: 2px;
	}
	.source-hal-label { background: #e8f0f8; color: #3b6b9e; }
	.source-oa-label { background: #fef3e0; color: #b8733e; }
	.source-wos-label { background: #f0e8f5; color: #6b4c8a; }

	/* Source details / comparison */
	.source-details {
		margin-bottom: 16px;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}
	.source-details summary {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 14px;
		font-size: 0.95rem;
		font-weight: 500;
		cursor: pointer;
		background: #f5f4f1;
		border-bottom: 1px solid var(--border);
		user-select: none;
	}
	.source-details summary:hover { background: #eae9e5; }
	.source-details[open] > summary { margin-bottom: 0; }

	.source-ok { color: #2a7d4f; }
	.source-conflict { color: #c0392b; }

	.status-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		font-size: 0.75rem;
		font-weight: 700;
	}
	.ok-icon { background: #e6f4ec; color: #2a7d4f; }
	.conflict-icon { background: #fde8e8; color: #c0392b; }

	.source-summary-count {
		font-size: 0.85rem;
		color: var(--muted);
		font-weight: 400;
	}

	.source-wos-link { background: #f0e8f5; color: #6b4c8a; }
	.source-wos-link:hover { background: #e4d8f0; }

	/* Source grid */
	.source-grid-wrap { overflow-x: auto; }
	.source-grid {
		width: 100%;
		border-collapse: collapse;
	}
	.source-grid thead th {
		background: #f5f4f1;
		padding: 6px 10px;
		text-align: left;
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.source-grid tbody tr { border-bottom: 1px solid #f0efec; }
	.source-grid tbody tr:last-child { border-bottom: none; }

	.raw-affil {
		font-size: 0.8rem;
		color: var(--muted);
		font-style: italic;
	}

	.sg-pos { width: 28px; text-align: center; }
	.sg-name { min-width: 120px; }

	.sg-pos-cell {
		text-align: center;
		color: var(--muted);
		font-size: 0.8rem;
		padding: 4px 6px;
		vertical-align: middle;
	}
	.sg-name-cell {
		padding: 4px 10px;
		font-size: 0.88rem;
		vertical-align: middle;
		white-space: nowrap;
	}
	.countries-row { border-bottom: 2px solid var(--border) !important; }
	.countries-cell {
		font-size: 0.75rem;
		color: var(--muted);
		letter-spacing: 1px;
		padding: 3px 10px !important;
	}
	.author-countries {
		font-size: 0.7rem;
		color: #888;
		margin-left: 4px;
		letter-spacing: 0.5px;
	}
	.sg-author { }
	.sg-author-link { text-decoration: none; color: var(--text); }
	.sg-author-link:hover { text-decoration: underline; }
	.sg-uca { font-weight: 600; color: #2a7d4f; }
	.sg-excluded { opacity: 0.4; }
	.sg-excluded a, .sg-excluded span { text-decoration: line-through; }
	.exclude-btn {
		background: none; border: none; cursor: pointer; padding: 0 4px 0 0;
		font-size: 0.85rem; line-height: 1; color: #999; vertical-align: middle;
	}
	.exclude-btn:hover { color: #c0392b; }

	.conflict-row { background: #fff8f0; }
	.conflict-row:hover { background: #fef0e0; }

	.info-icon {
		cursor: help;
		color: var(--muted);
		font-size: 0.8rem;
		margin-left: 4px;
	}
	.info-icon:hover { color: var(--accent); }

	.no-results { text-align: center; padding: 40px; color: var(--muted); }
	.loading { text-align: center; padding: 40px; color: var(--muted); }
</style>
