<script lang="ts">
	import { api } from '$lib/api';
	import { base } from '$app/paths';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';

	interface PubDetail {
		id: number;
		title: string;
		title_normalized: string;
		doi: string | null;
		pub_year: number;
		doc_type: string | null;
		container_title: string | null;
		oa_status: string | null;
		language: string | null;
		journal: { id: number; title: string; issn: string | null; eissn: string | null } | null;
		sources: { source: string; source_id: string }[];
		authors: { author_position: number | null; is_uca: boolean; person_id: number | null; last_name: string | null; first_name: string | null; full_name: string | null }[];
	}
	interface NextResponse {
		total: number;
		offset: number;
		pair: { pub_a: PubDetail; pub_b: PubDetail } | null;
	}

	// Restore state from URL
	const params = new URLSearchParams($page.url.search);
	let total = $state(0);
	let offset = $state(parseInt(params.get('offset') ?? '0') || 0);
	let pair = $state<{ pub_a: PubDetail; pub_b: PubDetail } | null>(null);
	let loading = $state(false);
	let acting = $state(false);
	let mergedCount = $state(0);
	let distinctCount = $state(0);
	let error = $state('');

	function syncUrl() {
		const p = new URLSearchParams();
		if (offset > 0) p.set('offset', String(offset));
		const qs = p.toString();
		history.replaceState(history.state, '', `${base}/admin/duplicates${qs ? '?' + qs : ''}`);
	}

	async function loadAt(pos: number) {
		loading = true;
		error = '';
		try {
			const data = await api<NextResponse>(`/api/admin/duplicates/next?offset=${pos}`);
			total = data.total;
			offset = data.offset;
			pair = data.pair;
			// Si l'offset dépasse le total (fin de liste), revenir au début
			if (!pair && total > 0 && pos > 0) {
				offset = 0;
				const data2 = await api<NextResponse>(`/api/admin/duplicates/next?offset=0`);
				total = data2.total;
				offset = data2.offset;
				pair = data2.pair;
			}
			syncUrl();
		} catch (e: any) {
			error = e.message || 'Erreur de chargement';
			console.error(e);
		}
		loading = false;
	}

	async function mergePair(targetId: number, sourceId: number) {
		acting = true;
		try {
			await fetch(`${base}/api/admin/duplicates/merge`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ target_id: targetId, source_id: sourceId }),
			});
			mergedCount++;
			// Après fusion, la paire disparaît : même offset = paire suivante
			await loadAt(offset);
		} catch (e: any) {
			error = e.message || 'Erreur de fusion';
			console.error(e);
		}
		acting = false;
	}

	async function markDistinct(pubIdA: number, pubIdB: number) {
		acting = true;
		try {
			await fetch(`${base}/api/admin/duplicates/mark-distinct`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ pub_id_a: pubIdA, pub_id_b: pubIdB }),
			});
			distinctCount++;
			// Après marquage, la paire disparaît : même offset = paire suivante
			await loadAt(offset);
		} catch (e: any) {
			error = e.message || 'Erreur';
			console.error(e);
		}
		acting = false;
	}

	function sourceBadgeClass(src: string): string {
		if (src === 'hal') return 'badge-hal';
		if (src === 'openalex') return 'badge-oa';
		if (src === 'wos') return 'badge-wos';
		return '';
	}
	function sourceBadgeLabel(src: string): string {
		if (src === 'hal') return 'HAL';
		if (src === 'openalex') return 'OpenAlex';
		if (src === 'wos') return 'WoS';
		return src;
	}
	function sourceUrl(src: string, sourceId: string): string {
		if (src === 'hal') return `https://hal.science/${sourceId}`;
		if (src === 'openalex') return `https://openalex.org/${sourceId}`;
		if (src === 'wos') return `https://www.webofscience.com/wos/woscc/full-record/${sourceId}`;
		return '#';
	}

	onMount(() => { loadAt(offset); });
</script>

<svelte:head><title>Doublons publications — Admin</title></svelte:head>

<div class="container">
	<h1>Doublons de publications</h1>

	<div class="stats-bar">
		<div class="nav-group">
			<button class="btn-nav" onclick={() => loadAt(Math.max(0, offset - 1))} disabled={loading || offset === 0}
				title="Paire précédente">&lsaquo;</button>
			<span class="stat stat-position">{total > 0 ? offset + 1 : 0} / {total}</span>
			<button class="btn-nav" onclick={() => loadAt(offset + 1)} disabled={loading || !pair}
				title="Paire suivante">&rsaquo;</button>
		</div>
		{#if mergedCount}<span class="stat stat-merged">{mergedCount} fusionnée{mergedCount !== 1 ? 's' : ''}</span>{/if}
		{#if distinctCount}<span class="stat stat-distinct">{distinctCount} distincte{distinctCount !== 1 ? 's' : ''}</span>{/if}
	</div>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if loading}
		<p class="loading">Chargement...</p>
	{:else if !pair}
		<p class="empty">Aucun candidat doublon restant (titres normalisés identiques, &gt; 30 caractères).</p>
	{:else}
		{@const a = pair.pub_a}
		{@const b = pair.pub_b}

		<div class="pair-card">
			<!-- Titre normalisé commun -->
			<div class="shared-title">
				<span class="label">Titre normalisé :</span> {a.title_normalized}
			</div>

			<!-- Actions -->
			<div class="pair-actions">
				<button class="btn-merge" onclick={() => mergePair(a.id, b.id)} disabled={acting}
					title="Garder la publication de gauche, absorber celle de droite">
					&larr; Garder gauche
				</button>
				<button class="btn-distinct" onclick={() => markDistinct(a.id, b.id)} disabled={acting}
					title="Ces deux publications sont bien distinctes">
					Marquer distincts
				</button>
				<button class="btn-skip" onclick={() => loadAt(offset + 1)} disabled={acting}
					title="Passer cette paire pour y revenir plus tard">
					Passer &rsaquo;
				</button>
				<button class="btn-merge" onclick={() => mergePair(b.id, a.id)} disabled={acting}
					title="Garder la publication de droite, absorber celle de gauche">
					Garder droite &rarr;
				</button>
			</div>

			<!-- Deux colonnes -->
			<div class="pair-columns">
				{#each [a, b] as pub}
					<div class="pub-col">
						<div class="pub-sources">
							{#each pub.sources as src}
								<a href={sourceUrl(src.source, src.source_id)} target="_blank" rel="noopener"
									class="source-badge {sourceBadgeClass(src.source)}">{sourceBadgeLabel(src.source)}</a>
							{/each}
						</div>
						<div class="pub-meta">
							<span class="pub-type">{pub.doc_type ?? '?'}</span>
							<span class="pub-year">{pub.pub_year}</span>
							{#if pub.language}<span class="pub-lang">{pub.language}</span>{/if}
						</div>
						<div class="pub-title">
							<a href="{base}/publications/{pub.id}">{@html pub.title}</a>
						</div>
						{#if pub.doi}
							<div class="pub-doi">DOI: {pub.doi}</div>
						{/if}
						<div class="pub-journal">{pub.container_title ?? '—'}</div>
						{#if pub.journal}
							<div class="pub-journal-detail">
								{pub.journal.title}
								{#if pub.journal.issn}· ISSN {pub.journal.issn}{/if}
								{#if pub.journal.eissn}· eISSN {pub.journal.eissn}{/if}
							</div>
						{/if}
						<div class="pub-oa">OA : {pub.oa_status ?? '?'}</div>

						<h4>Auteurs ({pub.authors.length})</h4>
						<div class="author-list">
							{#each pub.authors as au}
								<div class="author-item" class:uca={au.is_uca}>
									<span class="author-pos">{(au.author_position ?? 0) + 1}.</span>
									{#if au.person_id}
										<a href="{base}/persons/{au.person_id}" class="person-link-name">
											{au.first_name ?? ''} {au.last_name ?? '?'}
										</a>
									{:else}
										<span>{au.full_name ?? au.first_name ?? ''} {au.last_name ?? '?'}</span>
									{/if}
								</div>
							{/each}
						</div>

						<div class="source-ids">
							{#each pub.sources as src}
								<span class="source-detail">{src.source}: {src.source_id}</span>
							{/each}
						</div>
					</div>
				{/each}
			</div>

		</div>
	{/if}
</div>

<style>
	.container {
		max-width: 1100px;
		margin: 0 auto;
		padding: 24px;
	}
	h1 {
		font-size: 1.5rem;
		margin-bottom: 16px;
	}

	.stats-bar {
		display: flex;
		gap: 12px;
		margin-bottom: 20px;
		align-items: center;
	}
	.stat {
		font-size: 0.9rem;
		padding: 4px 10px;
		background: #f5f5f5;
		border-radius: 4px;
		color: var(--muted, #666);
	}
	.stat-position { background: #e2e6ea; color: #333; font-weight: 600; }
	.stat-merged { background: #d4edda; color: #155724; }
	.stat-distinct { background: #fff3cd; color: #856404; }
	.stat-skipped { background: #e8e8e8; color: #666; }
	.nav-group {
		display: flex;
		gap: 4px;
		align-items: center;
	}
	.btn-nav {
		padding: 4px 10px;
		border: 1px solid var(--border, #ccc);
		border-radius: 4px;
		background: var(--card, #fff);
		cursor: pointer;
		font-size: 1rem;
		line-height: 1;
	}
	.btn-nav:hover:not(:disabled) { background: #f0f0f0; }
	.btn-nav:disabled { opacity: 0.3; cursor: default; }

	.pair-card {
		background: var(--card, #fff);
		border: 1px solid var(--border, #e0e0e0);
		border-radius: 8px;
		overflow: hidden;
	}
	.shared-title {
		padding: 10px 16px;
		background: #f0f4f8;
		border-bottom: 1px solid var(--border, #e0e0e0);
		font-size: 0.9rem;
	}
	.shared-title .label {
		font-weight: 600;
		color: var(--muted, #666);
	}

	.pair-columns {
		display: grid;
		grid-template-columns: 1fr 1fr;
	}
	.pub-col {
		padding: 14px 16px;
	}
	.pub-col:first-child {
		border-right: 1px solid var(--border, #e0e0e0);
	}
	.pub-sources {
		display: flex;
		gap: 4px;
		margin-bottom: 6px;
	}
	.source-badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 10px;
		font-size: 0.75rem;
		font-weight: 600;
		color: white;
		text-decoration: none;
	}
	.source-badge:hover {
		opacity: 0.85;
	}
	.badge-hal { background: #28a745; }
	.badge-oa { background: #fd7e14; }
	.badge-wos { background: #3b6b9e; }
	.pub-meta {
		display: flex;
		gap: 8px;
		font-size: 0.8rem;
		color: var(--muted, #666);
		margin-bottom: 4px;
	}
	.pub-title {
		font-size: 0.95rem;
		margin-bottom: 4px;
	}
	.pub-title a { color: inherit; text-decoration: none; }
	.pub-title a:hover { text-decoration: underline; }
	.pub-doi {
		font-size: 0.8rem;
		color: var(--muted, #666);
		font-family: 'SF Mono', SFMono-Regular, Consolas, monospace;
	}
	.pub-journal {
		font-size: 0.85rem;
		font-style: italic;
		color: var(--muted, #666);
		margin-top: 2px;
	}
	.pub-journal-detail {
		font-size: 0.75rem;
		color: var(--muted, #999);
	}
	.pub-oa {
		font-size: 0.8rem;
		color: var(--muted, #666);
		margin-top: 2px;
	}
	h4 {
		font-size: 0.85rem;
		margin: 10px 0 4px 0;
		color: var(--muted, #666);
	}
	.author-list {
		margin: 0 0 8px 0;
		font-size: 0.85rem;
	}
	.author-item {
		padding: 1px 0;
	}
	.author-item.uca { font-weight: 600; }
	.author-pos {
		display: inline-block;
		width: 24px;
		text-align: right;
		margin-right: 4px;
		color: var(--muted, #999);
		font-size: 0.8rem;
	}
	.person-link-name {
		color: var(--accent, #3b6b9e);
		text-decoration: none;
		font-size: 0.85rem;
	}
	.person-link-name:hover { text-decoration: underline; }
	.source-ids { margin-top: 6px; }
	.source-detail {
		display: block;
		font-size: 0.75rem;
		color: var(--muted, #999);
		font-family: monospace;
	}

	.pair-actions {
		display: flex;
		gap: 8px;
		padding: 12px 16px;
		border-bottom: 1px solid var(--border, #e0e0e0);
		background: #fafafa;
		justify-content: center;
	}
	.btn-merge {
		padding: 8px 18px;
		border: 1px solid #28a745;
		border-radius: 4px;
		background: white;
		color: #28a745;
		cursor: pointer;
		font-size: 0.9rem;
		font-weight: 500;
	}
	.btn-merge:hover:not(:disabled) { background: #d4edda; }
	.btn-merge:disabled { opacity: 0.5; cursor: default; }
	.btn-distinct {
		padding: 8px 18px;
		border: 1px solid var(--border, #ccc);
		border-radius: 4px;
		background: white;
		color: var(--muted, #666);
		cursor: pointer;
		font-size: 0.9rem;
	}
	.btn-distinct:hover:not(:disabled) { background: #fff3cd; }
	.btn-skip {
		padding: 8px 18px;
		border: 1px solid var(--border, #ccc);
		border-radius: 4px;
		background: white;
		color: var(--muted, #666);
		cursor: pointer;
		font-size: 0.9rem;
	}
	.btn-skip:hover:not(:disabled) { background: #f0f0f0; }
	.btn-skip:disabled, .btn-distinct:disabled { opacity: 0.5; cursor: default; }

	.loading, .empty {
		text-align: center;
		color: var(--muted, #666);
		padding: 40px;
	}
	.error {
		color: #dc3545;
		padding: 8px 12px;
		background: #f8d7da;
		border-radius: 4px;
		margin-bottom: 12px;
	}
</style>
