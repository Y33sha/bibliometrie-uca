<script lang="ts">
	import { api } from '$lib/api';
	import { base } from '$app/paths';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';

	interface Identifier {
		id: number;
		id_type: string;
		id_value: string;
		source: string;
		status: string;
	}
	interface Publication {
		id: number;
		title: string;
		pub_year: number | null;
		doi: string | null;
		doc_type: string | null;
		sources: string[];
	}
	interface Lab {
		id: number;
		acronym: string | null;
		name: string;
	}
	interface PersonDetail {
		id: number;
		last_name: string;
		first_name: string;
		last_name_normalized: string;
		first_name_normalized: string;
		has_rh: boolean;
		role_title: string | null;
		department_name: string | null;
		identifiers: Identifier[];
		publications: Publication[];
		pub_count: number;
		labs: Lab[];
	}
	interface ConflictPub {
		id: number;
		title: string;
		pub_year: number | null;
		doc_type: string | null;
		position: number;
	}
	interface NextResponse {
		pair: { person_a: PersonDetail; person_b: PersonDetail; conflict_pubs?: ConflictPub[] } | null;
	}

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
		history.replaceState(history.state, '', `${base}/admin/duplicates-persons${qs ? '?' + qs : ''}`);
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
			const res = await fetch(`${base}/api/persons/${targetId}/merge`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ source_id: sourceId }),
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => ({}));
				throw new Error(detail.detail || `Erreur ${res.status}`);
			}
			mergedCount++;
			// Après fusion, la paire disparaît : même offset = paire suivante
			await loadAt(offset);
		} catch (e: any) {
			error = e.message || 'Erreur de fusion';
			console.error(e);
		}
		acting = false;
	}

	async function markDistinct(idA: number, idB: number) {
		acting = true;
		try {
			await fetch(`${base}/api/admin/person-duplicates/mark-distinct`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ person_id_a: idA, person_id_b: idB }),
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

	function statusClass(status: string): string {
		if (status === 'confirmed') return 'id-confirmed';
		if (status === 'rejected') return 'id-rejected';
		return 'id-pending';
	}

	function sourceBadgeClass(src: string): string {
		if (src === 'HAL') return 'badge-hal';
		if (src === 'OpenAlex') return 'badge-oa';
		if (src === 'WoS') return 'badge-wos';
		return '';
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
			<button class="btn-nav" onclick={() => loadAt(Math.max(0, offset - 1))} disabled={loading || offset === 0}
				title="Paire précédente">&lsaquo;</button>
			<span class="stat stat-position">
				{total !== null ? `${offset + 1} / ${total}` : '...'}
			</span>
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
				<button class="btn-merge" onclick={() => mergePair(a.id, b.id)} disabled={acting}
					title="Garder la personne de gauche, absorber celle de droite">
					&larr; Garder gauche
				</button>
				<button class="btn-distinct" onclick={() => markDistinct(a.id, b.id)} disabled={acting}
					title="Ces deux personnes sont bien distinctes">
					Marquer distincts
				</button>
				<button class="btn-skip" onclick={() => loadAt(offset + 1)} disabled={acting}
					title="Passer cette paire pour y revenir plus tard">
					Passer &rsaquo;
				</button>
				<button class="btn-merge" onclick={() => mergePair(b.id, a.id)} disabled={acting}
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
							<a href="{base}/publications/{cp.id}" class="pub-link">{@html cp.title}</a>
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
									<span class="ident-tag {statusClass(ident.status)}">
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
											<span class="source-mini {sourceBadgeClass(src)}">{src}</span>
										{/each}
									</div>
									<a href="{base}/publications/{pub.id}" class="pub-link">
										{@html pub.title}
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
		background: var(--accent, #3b6b9e);
		color: white;
		border-color: var(--accent, #3b6b9e);
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
		color: #b8733e;
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
	.stat-merged { background: #d4edda; color: #155724; }
	.stat-distinct { background: #fff3cd; color: #856404; }
	.stat-skipped { background: #e8e8e8; color: #666; }
	.nav-buttons { display: flex; gap: 4px; margin-left: auto; }
	.nav-group { display: flex; gap: 4px; align-items: center; }
	.btn-nav {
		padding: 4px 10px; border: 1px solid var(--border, #ccc);
		border-radius: 4px; background: var(--card, #fff);
		cursor: pointer; font-size: 1rem; line-height: 1;
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
		color: #3b6b9e;
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
	.rh-check {
		color: #3b6b9e;
		font-size: 0.85rem;
		margin-left: 4px;
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
	.id-confirmed .ident-value { background: #d4edda; }
	.id-rejected .ident-value { background: #f8d7da; text-decoration: line-through; opacity: 0.6; }
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
	.source-mini {
		display: inline-block;
		padding: 1px 5px;
		border-radius: 8px;
		font-size: 0.65rem;
		font-weight: 600;
		color: white;
	}
	.badge-hal { background: #28a745; }
	.badge-oa { background: #fd7e14; }
	.badge-wos { background: #3b6b9e; }
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
	.btn-merge {
		padding: 8px 18px; border: 1px solid #28a745; border-radius: 4px;
		background: white; color: #28a745; cursor: pointer;
		font-size: 0.9rem; font-weight: 500;
	}
	.btn-merge:hover:not(:disabled) { background: #d4edda; }
	.btn-merge:disabled { opacity: 0.5; cursor: default; }
	.btn-distinct {
		padding: 8px 18px; border: 1px solid var(--border, #ccc); border-radius: 4px;
		background: white; color: var(--muted, #666); cursor: pointer; font-size: 0.9rem;
	}
	.btn-distinct:hover:not(:disabled) { background: #fff3cd; }
	.btn-skip {
		padding: 8px 18px; border: 1px solid var(--border, #ccc); border-radius: 4px;
		background: white; color: var(--muted, #666); cursor: pointer; font-size: 0.9rem;
	}
	.btn-skip:hover:not(:disabled) { background: #f0f0f0; }
	.btn-skip:disabled, .btn-distinct:disabled { opacity: 0.5; cursor: default; }

	.loading, .empty {
		text-align: center; color: var(--muted, #666); padding: 40px;
	}
	.error {
		color: #dc3545; padding: 8px 12px;
		background: #f8d7da; border-radius: 4px; margin-bottom: 12px;
	}
</style>
