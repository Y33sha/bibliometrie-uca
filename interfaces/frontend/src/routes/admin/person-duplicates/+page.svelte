<script lang="ts">
	import { api, ApiError, persons as personsApi } from '$lib/api';
	import { base } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { sanitizeTitle } from '$lib/utils';
	import { identifierStatusClasses } from '$lib/labels';
	import SourceTag from '$lib/components/SourceTag.svelte';

	import type { components } from '$lib/api/schema';
	type PersonDetail = components['schemas']['PersonDedupDetail'];
	type ConflictPub = components['schemas']['PersonConflictPub'];
	// Réponse partagée pour /next et /conflicts/next : conflict_pubs présent
	// uniquement sur l'endpoint conflict (PersonConflictPair vs PersonDuplicatePair).
	type NextResponse = {
		pair: { person_a: PersonDetail; person_b: PersonDetail; conflict_pubs?: ConflictPub[] } | null;
	};

	type Mode = 'name' | 'conflict';

	// Restore state from URL
	const urlParams = new URLSearchParams($page.url.search);
	let mode: Mode = $state((urlParams.get('mode') === 'conflict' ? 'conflict' : 'name') as Mode);
	let total = $state<number | null>(null);
	let offset = $state(parseInt(urlParams.get('offset') ?? '0') || 0);
	let pair = $state<{ person_a: PersonDetail; person_b: PersonDetail; conflict_pubs?: ConflictPub[] } | null>(null);
	let loading = $state(false);
	let acting = $state(false);
	let mergedCount = $state(0);
	let distinctCount = $state(0);
	let error = $state('');

	function syncUrl() {
		const p = new URLSearchParams();
		if (mode !== 'name') p.set('mode', mode);
		if (offset > 0) p.set('offset', String(offset));
		const qs = p.toString();
		replaceState(`${base}/admin/person-duplicates${qs ? '?' + qs : ''}`, {});
	}

	async function loadTotal() {
		try {
			const endpoint = mode === 'conflict'
				? '/api/admin/person-duplicates/conflicts/count'
				: '/api/admin/person-duplicates/count';
			const data = await api<{ total: number }>(endpoint);
			total = data.total;
		} catch {}
	}

	async function loadAt(pos: number) {
		loading = true;
		error = '';
		try {
			const endpoint = mode === 'conflict'
				? '/api/admin/person-duplicates/conflicts/next'
				: '/api/admin/person-duplicates/next';
			const data = await api<NextResponse>(`${endpoint}?offset=${pos}`);
			pair = data.pair;
			offset = pos;
			// Si on dépasse la fin, revenir au début
			if (!pair && total && pos > 0) {
				offset = 0;
				const data2 = await api<NextResponse>(`${endpoint}?offset=0`);
				pair = data2.pair;
			}
		} catch (e: any) {
			error = e.message || 'Erreur de chargement';
			console.error(e);
		}
		loading = false;
		syncUrl();
	}

	function switchMode(m: Mode) {
		if (m === mode) return;
		mode = m;
		total = null;
		pair = null;
		offset = 0;
		mergedCount = 0;
		distinctCount = 0;
		syncUrl();
		loadAt(0).then(() => loadTotal());
	}

	async function mergePair(targetId: number, sourceId: number) {
		acting = true;
		try {
			await personsApi.merge(targetId, sourceId);
			mergedCount++;
			// Après fusion, la paire disparaît : même offset = paire suivante
			await loadAt(offset);
		} catch (e: any) {
			if (e instanceof ApiError) {
				const detail = (e.detail as { detail?: string })?.detail;
				error = detail || `Erreur ${e.status}`;
			} else {
				error = e.message || 'Erreur de fusion';
			}
			console.error(e);
		}
		acting = false;
	}

	async function markDistinct(idA: number, idB: number) {
		acting = true;
		try {
			await personsApi.markDistinct(idA, idB);
			distinctCount++;
			// Après marquage, la paire disparaît : même offset = paire suivante
			await loadAt(offset);
		} catch (e: any) {
			error = e.message || 'Erreur';
			console.error(e);
		}
		acting = false;
	}

	onMount(async () => {
		await loadAt(offset);
		loadTotal();
	});
</script>

<svelte:head><title>Doublons personnes — Admin</title></svelte:head>

<div class="container">
	<h1>Doublons de personnes</h1>

	<div class="mode-toggle">
		<button class="mode-btn" class:active={mode === 'name'} onclick={() => switchMode('name')}>Par nom</button>
		<button class="mode-btn" class:active={mode === 'conflict'} onclick={() => switchMode('conflict')}>Par conflit de sources</button>
	</div>

	<div class="stats-bar">
		<div class="nav-group">
			<button class="btn btn-nav" onclick={() => loadAt(Math.max(0, offset - 1))} disabled={loading || offset === 0}
				title="Paire précédente">&lsaquo;</button>
			<span class="stat stat-position">
				{total !== null ? `${offset + 1} / ${total}` : '...'}
			</span>
			<button class="btn btn-nav" onclick={() => loadAt(offset + 1)} disabled={loading || !pair}
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
		<p class="empty">Aucun candidat doublon de personne restant.</p>
	{:else}
		{@const a = pair.person_a}
		{@const b = pair.person_b}

		<div class="pair-card">
			<!-- En-tête : noms normalisés -->
			<div class="shared-title">
				<span class="label">Noms normalisés :</span>
				{a.last_name_normalized} {a.first_name_normalized}
				{#if a.last_name_normalized !== b.last_name_normalized || a.first_name_normalized !== b.first_name_normalized}
					<span class="vs">vs</span>
					{b.last_name_normalized} {b.first_name_normalized}
				{/if}
			</div>

			<!-- Actions -->
			<div class="pair-actions">
				<button class="btn btn-merge" onclick={() => mergePair(a.id, b.id)} disabled={acting}
					title="Garder la personne de gauche, absorber celle de droite">
					&larr; Garder gauche
				</button>
				<button class="btn btn-distinct" onclick={() => markDistinct(a.id, b.id)} disabled={acting}
					title="Ces deux personnes sont bien distinctes">
					Marquer distincts
				</button>
				<button class="btn btn-skip" onclick={() => loadAt(offset + 1)} disabled={acting}
					title="Passer cette paire pour y revenir plus tard">
					Passer &rsaquo;
				</button>
				<button class="btn btn-merge" onclick={() => mergePair(b.id, a.id)} disabled={acting}
					title="Garder la personne de droite, absorber celle de gauche">
					Garder droite &rarr;
				</button>
			</div>


			{#if pair.conflict_pubs?.length}
				<div class="conflict-pubs">
					<h4>Publications en conflit ({pair.conflict_pubs.length})</h4>
					{#each pair.conflict_pubs as cp}
						<div class="conflict-pub-item">
							<span class="conflict-pos" title="Position de l'auteur">pos. {(cp.position ?? 0) + 1}</span>
							<a href="{base}/publications/{cp.id}" class="pub-link">{@html sanitizeTitle(cp.title)}</a>
							<span class="pub-meta-mini">{cp.pub_year ?? '?'}{#if cp.doc_type} · {cp.doc_type}{/if}</span>
						</div>
					{/each}
				</div>
			{/if}

			<!-- Deux colonnes -->
			<div class="pair-columns">
				{#each [a, b] as person}
					<div class="pub-col">
						<!-- Laboratoires -->
						{#if person.labs.length > 0}
							<div class="person-labs">
								{#each person.labs as lab}
									<span class="lab-badge" title={lab.name}>{lab.acronym ?? lab.name}</span>
								{/each}
							</div>
						{/if}

						<!-- Nom -->
						<div class="person-name">
							<span class="person-label">Nom :</span> <span class="last-name">{person.last_name}</span>
							{#if person.has_rh}<span class="rh-check" title="Fichier RH">&#10003;</span>{/if}
						</div>
						<div class="person-firstname">
							<span class="person-label">Prénom :</span> {person.first_name}
						</div>

						<!-- RH info -->
						{#if person.department_name || person.role_title}
							<div class="person-rh">
								{#if person.department_name}<span>{person.department_name}</span>{/if}
								{#if person.role_title}<span class="role">{person.role_title}</span>{/if}
							</div>
						{/if}

						<!-- Identifiants -->
						{#if person.identifiers.length > 0}
							<div class="identifiers">
								{#each person.identifiers as ident}
									<span class="ident-tag {identifierStatusClasses[ident.status] ?? 'id-pending'}">
										<span class="ident-type">{ident.id_type}</span>
										<span class="ident-value">{ident.id_value}</span>
									</span>
								{/each}
							</div>
						{/if}

						<!-- Publications -->
						<h4>{person.pub_count} publication{person.pub_count !== 1 ? 's' : ''}</h4>
						<div class="pub-list">
							{#each person.publications as pub}
								<div class="pub-item">
									<div class="pub-sources-mini">
										{#each pub.sources as src}
											<SourceTag source={src} />
										{/each}
									</div>
									<a href="{base}/publications/{pub.id}" class="pub-link">
										{@html sanitizeTitle(pub.title)}
									</a>
									<span class="pub-meta-mini">
										{pub.pub_year ?? '?'}
										{#if pub.doc_type}· {pub.doc_type}{/if}
									</span>
								</div>
							{/each}
							{#if person.publications.length === 0}
								<p class="no-pubs">Aucune publication</p>
							{/if}
						</div>
					</div>
				{/each}
			</div>

		</div>
	{/if}
</div>

<style>
	.container { max-width: 1200px; margin: 0 auto; padding: 24px; }
	h1 { font-size: 1.5rem; margin-bottom: 16px; }

	.mode-toggle {
		display: flex;
		gap: 0;
		margin-bottom: 16px;
	}
	.mode-btn {
		padding: 6px 16px;
		border: 1px solid var(--border, #ccc);
		background: var(--card, #fff);
		font-size: 0.9rem;
		cursor: pointer;
		font-family: inherit;
		color: var(--muted, #666);
	}
	.mode-btn:first-child { border-radius: 4px 0 0 4px; }
	.mode-btn:last-child { border-radius: 0 4px 4px 0; border-left: none; }
	.mode-btn.active {
		background: var(--accent);
		color: white;
		border-color: var(--accent);
		font-weight: 600;
	}

	.conflict-pubs {
		background: #fff8f0;
		border: 1px solid #f0dcc0;
		border-radius: 6px;
		padding: 10px 14px;
		margin-bottom: 12px;
	}
	.conflict-pubs h4 {
		font-size: 0.9rem;
		margin: 0 0 6px;
		color: var(--bronze);
	}
	.conflict-pub-item {
		display: flex;
		align-items: baseline;
		gap: 8px;
		padding: 2px 0;
		font-size: 0.85rem;
	}
	.conflict-pos {
		flex-shrink: 0;
		font-size: 0.75rem;
		padding: 1px 6px;
		background: #f0dcc0;
		border-radius: 3px;
		color: #8a5e2c;
		font-weight: 600;
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
	.stat-merged { background: var(--success-light); color: var(--success); }
	.stat-distinct { background: #fff3cd; color: #856404; }
	.stat-skipped { background: #e8e8e8; color: #666; }
	.nav-buttons { display: flex; gap: 4px; margin-left: auto; }
	.nav-group { display: flex; gap: 4px; align-items: center; }

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
		color: var(--muted, #666);
	}
	.shared-title .label { font-weight: 600; }
	.shared-title .vs { margin: 0 8px; font-style: italic; color: #999; }

	.pair-columns { display: grid; grid-template-columns: 1fr 1fr; }
	.pub-col { padding: 14px 16px; }

	.person-labs {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-bottom: 6px;
	}
	.lab-badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 10px;
		font-size: 0.75rem;
		font-weight: 600;
		background: #e8eef4;
		color: var(--accent);
	}
	.pub-col:first-child { border-right: 1px solid var(--border, #e0e0e0); }

	.person-name {
		font-size: 1.1rem;
		margin-bottom: 2px;
	}
	.person-firstname {
		font-size: 1rem;
		margin-bottom: 4px;
	}
	.last-name { font-weight: 700; }
	.person-label {
		font-size: 0.75rem;
		color: var(--muted, #999);
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.person-rh {
		font-size: 0.85rem;
		color: var(--muted, #666);
		margin-bottom: 8px;
		display: flex;
		gap: 8px;
	}
	.role { font-style: italic; }

	.identifiers {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-bottom: 10px;
	}
	.ident-tag {
		display: inline-flex;
		align-items: center;
		border-radius: 4px;
		font-size: 0.8rem;
		overflow: hidden;
		border: 1px solid var(--border, #ddd);
	}
	.ident-type {
		padding: 2px 6px;
		background: #eee;
		font-weight: 600;
		text-transform: uppercase;
		font-size: 0.7rem;
	}
	.ident-value {
		padding: 2px 6px;
	}
	.id-confirmed .ident-value { background: var(--success-light); }
	.id-rejected .ident-value { background: var(--danger-light); text-decoration: line-through; opacity: 0.6; }
	.id-pending .ident-value { background: #e3f2fd; }

	h4 {
		font-size: 0.85rem;
		margin: 10px 0 6px;
		color: var(--muted, #666);
	}

	.pub-list {
	}
	.pub-item {
		padding: 4px 0;
		border-bottom: 1px solid #f5f5f5;
	}
	.pub-item:last-child { border-bottom: none; }
	.pub-sources-mini {
		display: inline-flex;
		gap: 3px;
		margin-right: 4px;
		vertical-align: middle;
	}
	.pub-link {
		font-size: 0.85rem;
		color: inherit;
		text-decoration: none;
	}
	.pub-link:hover { text-decoration: underline; }
	.pub-meta-mini {
		font-size: 0.75rem;
		color: var(--muted, #999);
		margin-left: 4px;
	}
	.no-pubs {
		font-size: 0.85rem;
		color: var(--muted, #999);
		font-style: italic;
	}

	.pair-actions {
		display: flex;
		gap: 8px;
		padding: 12px 16px;
		border-bottom: 1px solid var(--border, #e0e0e0);
		background: #fafafa;
		justify-content: center;
	}
	.btn-merge, .btn-distinct, .btn-skip { padding: 8px 18px; font-size: 0.9rem; }

	.loading, .empty {
		text-align: center; color: var(--muted, #666); padding: 40px;
	}
	.error {
		color: var(--danger); padding: 8px 12px;
		background: var(--danger-light); border-radius: 4px; margin-bottom: 12px;
	}
</style>
