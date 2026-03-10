<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import { esc } from '$lib/utils';
	import Pagination from '$lib/components/Pagination.svelte';

	// ---------- Types ----------

	interface FeedbackStats {
		detection_rate: number | null;
		total_reviewed: number;
		false_negatives: number;
		false_positives: number;
		concordant_valid: number;
		pending: number;
	}

	interface LabDetected {
		id: number;
		name: string;
		acronym: string | null;
		structure_id: number;
	}

	interface MatchedForm {
		form_id: number;
		form_text: string;
		structure_name: string;
		requires_context_of: (string | number)[] | null;
	}

	interface FeedbackAddress {
		id: number;
		raw_text: string;
		pub_count: number;
		labs: LabDetected[];
		matched_forms?: MatchedForm[];
	}

	interface FeedbackPage {
		total: number;
		page: number;
		pages: number;
		addresses: FeedbackAddress[];
	}

	interface Lab {
		id: number;
		code: string;
		name: string;
		acronym: string | null;
	}

	interface Structure {
		id: number;
		code: string;
		name: string;
		acronym: string | null;
		type: string;
	}

	interface NameForm {
		id: number;
		requires_context_of: (string | number)[];
	}

	interface RerunResult {
		success: boolean;
		summary: string[];
	}

	// ---------- State ----------

	type Tab = 'fn' | 'fp';

	let stats: FeedbackStats | null = $state(null);
	let currentTab: Tab = $state('fn');
	let currentPage = $state(1);
	let pages = $state(0);
	let total = $state(0);
	let addresses: FeedbackAddress[] = $state([]);
	let search = $state('');
	let searchTimeout: ReturnType<typeof setTimeout> | null = $state(null);
	let allLabs: Lab[] = $state([]);
	let allStructures: Structure[] = $state([]);
	let rerunState: 'idle' | 'running' | 'done' = $state('idle');

	// Lab assignment: per-address selected structure id
	let assignSelections: Record<number, string> = $state({});

	// Context picker state
	let ctxPicker: { formId: number; x: number; y: number } | null = $state(null);
	let ctxSearch = $state('');

	const ctxFilteredStructures = $derived.by(() => {
		const q = ctxSearch.toLowerCase();
		return allStructures
			.filter(
				(s) =>
					s.name.toLowerCase().includes(q) ||
					(s.acronym || '').toLowerCase().includes(q) ||
					s.code.toLowerCase().includes(q)
			)
			.slice(0, 8);
	});

	const helpText = $derived.by(() => {
		if (currentTab === 'fn') {
			return {
				title: 'Faux négatifs',
				body: 'Adresses marquées UCA manuellement mais non détectées par le script. Ajouter des formes de nom et relancer la détection.'
			};
		}
		return {
			title: 'Faux positifs',
			body: 'Adresses détectées UCA par le script mais rejetées manuellement. La forme ayant matché est affichée \u2014 vous pouvez la supprimer ou lui ajouter un contexte contraignant, puis relancer la détection.'
		};
	});

	const rerunLabel = $derived(
		rerunState === 'running'
			? '\u23F3 Detection en cours\u2026'
			: rerunState === 'done'
				? '\u2713 Termine'
				: '\u25B6 Relancer la detection'
	);

	// ---------- Data loading ----------

	async function loadStats() {
		stats = await api<FeedbackStats>('/api/feedback/stats');
	}

	async function loadTable() {
		const endpoint =
			currentTab === 'fn' ? '/api/feedback/false-negatives' : '/api/feedback/false-positives';
		const params = new URLSearchParams({
			page: String(currentPage),
			per_page: '50'
		});
		if (search) params.set('search', search);

		const data = await api<FeedbackPage>(endpoint + '?' + params);
		addresses = data.addresses;
		total = data.total;
		pages = data.pages;
		currentPage = data.page;
	}

	function switchTab(tab: Tab) {
		currentTab = tab;
		currentPage = 1;
		search = '';
		loadTable();
	}

	function onSearchInput() {
		if (searchTimeout) clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			currentPage = 1;
			loadTable();
		}, 400);
	}

	function onPageChange(p: number) {
		currentPage = p;
		loadTable();
		window.scrollTo(0, 0);
	}

	// ---------- Assign structure (FN) ----------

	async function assignLab(addressId: number) {
		const structId = assignSelections[addressId];
		if (!structId) return;

		await fetch(base + '/api/addresses/' + addressId + '/assign-structure', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ structure_id: parseInt(structId) })
		});

		loadStats();
		loadTable();
	}

	function labOptions(address: FeedbackAddress): Lab[] {
		const assignedIds = (address.labs || []).map((l) => l.structure_id);
		return allLabs.filter((l) => !assignedIds.includes(l.id));
	}

	// ---------- Form actions (FP) ----------

	async function deleteForm(formId: number) {
		if (!confirm('Supprimer cette forme de nom ? Cela affectera la detection apres relance.'))
			return;
		try {
			await fetch(base + '/api/name-forms/' + formId, { method: 'DELETE' });
			loadTable();
		} catch (e: unknown) {
			const msg = e instanceof Error ? e.message : String(e);
			alert('Erreur: ' + msg);
		}
	}

	function openCtxPicker(formId: number, event: MouseEvent) {
		event.stopPropagation();
		const btn = event.target as HTMLElement;
		const rect = btn.getBoundingClientRect();
		ctxSearch = '';
		ctxPicker = {
			formId,
			x: Math.min(rect.left, window.innerWidth - 340),
			y: rect.bottom + 4
		};
	}

	function closeCtxPicker() {
		ctxPicker = null;
	}

	async function addCtxToForm(item: string | number) {
		if (!ctxPicker) return;
		const formId = ctxPicker.formId;
		closeCtxPicker();

		try {
			const formData = await api<NameForm>('/api/name-forms/' + formId);
			const ctx = formData.requires_context_of || [];
			if (!ctx.includes(item)) ctx.push(item);

			await fetch(base + '/api/name-forms/' + formId, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ requires_context_of: ctx })
			});
			loadTable();
		} catch (e: unknown) {
			const msg = e instanceof Error ? e.message : String(e);
			alert('Erreur: ' + msg);
		}
	}

	function handleOutsideClick(event: MouseEvent) {
		if (!ctxPicker) return;
		const target = event.target as HTMLElement;
		const picker = document.getElementById('form-ctx-picker');
		if (picker && !picker.contains(target) && !target.classList.contains('form-action')) {
			closeCtxPicker();
		}
	}

	// ---------- Rerun ----------

	async function launchRerun() {
		rerunState = 'running';
		try {
			const res = await fetch(base + '/api/feedback/rerun', { method: 'POST' });
			if (!res.ok) throw new Error('API error: ' + res.status);
			const result: RerunResult = await res.json();
			if (result.success) {
				rerunState = 'done';
				loadStats();
				loadTable();
				setTimeout(() => {
					rerunState = 'idle';
				}, 3000);
			} else {
				alert('Erreur:\n' + result.summary.join('\n'));
				rerunState = 'idle';
			}
		} catch (e: unknown) {
			const msg = e instanceof Error ? e.message : String(e);
			alert('Erreur: ' + msg);
			rerunState = 'idle';
		}
	}

	// ---------- Unique forms helper ----------

	function uniqueForms(forms: MatchedForm[]): MatchedForm[] {
		const seen = new Set<number>();
		return forms.filter((f) => {
			if (seen.has(f.form_id)) return false;
			seen.add(f.form_id);
			return true;
		});
	}

	function formatCtx(ctx: (string | number)[]): string {
		return ctx
			.map((x) => (x === 'tutelles' ? '\uD83D\uDD17tut.' : String(x)))
			.join(', ');
	}

	// ---------- Init ----------

	onMount(async () => {
		allLabs = await api<Lab[]>('/api/laboratories');
		allStructures = await api<Structure[]>('/api/structures');
		loadStats();
		loadTable();
	});
</script>

<svelte:head>
	<title>Admin - Qualite detection - Bibliometrie UCA</title>
</svelte:head>

<svelte:window onclick={handleOutsideClick} />

<h2>Qualite de la detection</h2>

<!-- Stats row -->
{#if stats}
	<div class="stats-row">
		<div class="stat-card highlight-success">
			<div class="value val-success">
				{stats.detection_rate !== null ? stats.detection_rate + '%' : '\u2014'}
			</div>
			<div class="label">Taux de concordance</div>
		</div>
		<div class="stat-card">
			<div class="value">{stats.total_reviewed}</div>
			<div class="label">Adresses examinées</div>
		</div>
		<div class="stat-card highlight-warning">
			<div class="value val-warning">{stats.false_negatives}</div>
			<div class="label">Faux négatifs</div>
		</div>
		<div class="stat-card highlight-danger">
			<div class="value val-danger">{stats.false_positives}</div>
			<div class="label">Faux positifs</div>
		</div>
		<div class="stat-card">
			<div class="value">{stats.concordant_valid}</div>
			<div class="label">Vrais positifs</div>
		</div>
		<div class="stat-card">
			<div class="value">{stats.pending}</div>
			<div class="label">En attente</div>
		</div>
	</div>
{/if}

<!-- Help text -->
<div class="help-text">
	<strong>{helpText.title}</strong> &mdash; {helpText.body}
</div>

<!-- Toolbar -->
<div class="toolbar">
	<div class="tab-group">
		<button class="tab-btn" class:active={currentTab === 'fn'} onclick={() => switchTab('fn')}>
			Faux négatifs
		</button>
		<button class="tab-btn" class:active={currentTab === 'fp'} onclick={() => switchTab('fp')}>
			Faux positifs
		</button>
	</div>
	<input
		type="text"
		placeholder="Rechercher dans les adresses\u2026"
		bind:value={search}
		oninput={onSearchInput}
	/>
	<span class="count">{total} adresses</span>
	<button class="rerun-btn" disabled={rerunState !== 'idle'} onclick={launchRerun}>
		{rerunLabel}
	</button>
</div>

<!-- Table -->
{#if addresses.length === 0}
	<div class="empty">Aucune adresse trouvée &mdash; la détection est parfaite pour ce cas !</div>
{:else}
	<table class="data-table">
		<thead>
			<tr>
				<th>Adresse</th>
				<th class="num" style="width:60px">Publis</th>
				<th style="width:200px">Labo(s) détectés</th>
				{#if currentTab === 'fn'}
					<th style="width:250px">Assigner un labo</th>
				{:else}
					<th style="width:280px">Forme ayant matché</th>
				{/if}
			</tr>
		</thead>
		<tbody>
			{#each addresses as a (a.id)}
				<tr>
					<td class="addr-text">{a.raw_text}</td>
					<td class="num">{a.pub_count}</td>
					<td>
						{#if a.labs && a.labs.length > 0}
							{#each a.labs as l}
								<span class="lab-tag auto" title={l.name}>
									{l.acronym || l.name}
								</span>
							{/each}
						{:else}
							<span class="muted-small">aucun</span>
						{/if}
					</td>

					{#if currentTab === 'fn'}
						<!-- FN: assign structure -->
						<td>
							<div class="assign-row">
								<select bind:value={assignSelections[a.id]}>
									<option value="">Choisir\u2026</option>
									{#each labOptions(a) as lab}
										<option value={String(lab.id)}>
											{lab.acronym || lab.name}
										</option>
									{/each}
								</select>
								<button class="assign-btn" onclick={() => assignLab(a.id)}>
									Assigner
								</button>
							</div>
						</td>
					{:else}
						<!-- FP: matched forms -->
						<td>
							{#if a.matched_forms && a.matched_forms.length > 0}
								{#each uniqueForms(a.matched_forms) as f (f.form_id)}
									<div class="form-info">
										<span class="form-struct">{f.structure_name} &rarr;</span>
										<span class="form-text">{f.form_text}</span>
										{#if f.requires_context_of && f.requires_context_of.length}
											<span class="form-ctx">
												(ctx: {formatCtx(f.requires_context_of)})
											</span>
										{/if}
										<button
											class="form-action"
											title="Ajouter un contexte contraignant"
											onclick={(e) => openCtxPicker(f.form_id, e)}
										>
											+ ctx
										</button>
										<button
											class="form-action danger"
											title="Supprimer cette forme"
											onclick={() => deleteForm(f.form_id)}
										>
											suppr.
										</button>
									</div>
								{/each}
							{:else}
								<span class="muted-small">forme inconnue</span>
							{/if}
						</td>
					{/if}
				</tr>
			{/each}
		</tbody>
	</table>

	<Pagination page={currentPage} {pages} onchange={onPageChange} />
{/if}

<!-- Context picker (fixed position, rendered at body level) -->
{#if ctxPicker}
	<div
		class="ctx-picker-inline"
		id="form-ctx-picker"
		style="top:{ctxPicker.y}px;left:{ctxPicker.x}px"
		onclick={(e) => e.stopPropagation()}
		onkeydown={() => {}}
		role="dialog"
	>
		<div class="picker-shortcuts">
			<button onclick={() => addCtxToForm('tutelles')}>{'\uD83D\uDD17'} tutelles</button>
		</div>
		<input
			type="text"
			placeholder="Rechercher une structure\u2026"
			bind:value={ctxSearch}
		/>
		<div class="picker-results">
			{#each ctxFilteredStructures as s (s.id)}
				<button class="picker-item" onclick={() => addCtxToForm(s.id)}>
					<span class="picker-type">{s.type}</span>
					{s.acronym ? s.acronym + ' \u2014 ' : ''}{s.name}
				</button>
			{/each}
			{#if ctxFilteredStructures.length === 0}
				<div class="picker-item-empty">Aucun resultat</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	/* -- Local CSS variables -- */
	:root {
		--danger: #c0392b;
		--danger-light: #fbeaea;
		--success: #2a7d4f;
		--success-light: #e6f4ec;
		--warning: #d4a017;
		--warning-light: #fef8e8;
		--accent-light: #e8f0f8;
	}

	h2 {
		font-size: 1.2rem;
		font-weight: 600;
		margin: 0 0 16px;
	}

	/* Stats row */
	.stats-row {
		display: flex;
		gap: 10px;
		margin-bottom: 20px;
		flex-wrap: wrap;
	}

	.stat-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 12px 18px;
		text-align: center;
		flex: 1;
		min-width: 120px;
	}

	.stat-card .value {
		font-size: 1.55rem;
		font-weight: 700;
		line-height: 1.2;
	}

	.stat-card .label {
		font-size: 0.8rem;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.stat-card.highlight-danger {
		border-left: 3px solid var(--danger);
	}

	.stat-card.highlight-warning {
		border-left: 3px solid var(--warning);
	}

	.stat-card.highlight-success {
		border-left: 3px solid var(--success);
	}

	.val-danger {
		color: var(--danger);
	}

	.val-warning {
		color: var(--warning);
	}

	.val-success {
		color: var(--success);
	}

	/* Help text */
	.help-text {
		background: var(--accent-light);
		border: 1px solid #c4d8ed;
		border-radius: 5px;
		padding: 10px 14px;
		margin-bottom: 16px;
		font-size: 0.95rem;
		color: #2c3e50;
		line-height: 1.5;
	}

	/* Toolbar */
	.toolbar {
		display: flex;
		gap: 8px;
		margin-bottom: 16px;
		align-items: center;
		flex-wrap: wrap;
	}

	.tab-group {
		display: flex;
		gap: 0;
		margin-right: 12px;
	}

	.tab-btn {
		padding: 6px 14px;
		border: 1px solid var(--border);
		background: white;
		font-size: 0.95rem;
		cursor: pointer;
		font-family: inherit;
	}

	.tab-btn:first-child {
		border-radius: 4px 0 0 4px;
	}

	.tab-btn:last-child {
		border-radius: 0 4px 4px 0;
	}

	.tab-btn:not(:first-child) {
		border-left: none;
	}

	.tab-btn.active {
		background: var(--accent);
		color: white;
		border-color: var(--accent);
	}

	.toolbar input[type='text'] {
		padding: 6px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.95rem;
		background: white;
		width: 280px;
	}

	.count {
		margin-left: auto;
		color: var(--muted);
		font-size: 0.85rem;
	}

	.rerun-btn {
		padding: 6px 14px;
		border: 1px solid var(--accent);
		border-radius: 4px;
		background: white;
		color: var(--accent);
		font-size: 0.95rem;
		font-weight: 600;
		cursor: pointer;
		font-family: inherit;
	}

	.rerun-btn:hover:not(:disabled) {
		background: var(--accent);
		color: white;
	}

	.rerun-btn:disabled {
		opacity: 0.5;
		cursor: wait;
	}

	/* Table */
	.data-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}

	.data-table th {
		text-align: left;
		padding: 8px 10px;
		font-size: 0.8rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		background: #fafaf8;
	}

	.data-table td {
		padding: 7px 10px;
		font-size: 0.95rem;
		border-bottom: 1px solid #f0efec;
		vertical-align: top;
	}

	.data-table tr:last-child td {
		border-bottom: none;
	}

	.data-table tr:hover td {
		background: #fafaf8;
	}

	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.addr-text {
		font-family: 'SF Mono', 'Consolas', monospace;
		font-size: 0.85rem;
		line-height: 1.4;
		word-break: break-word;
		max-width: 600px;
	}

	.empty {
		text-align: center;
		padding: 40px;
		color: var(--muted);
	}

	.muted-small {
		color: var(--muted);
		font-size: 0.8rem;
	}

	/* Lab tags */
	.lab-tag {
		display: inline-block;
		font-size: 0.8rem;
		padding: 1px 7px;
		border-radius: 10px;
		font-weight: 500;
		margin: 1px 2px;
	}

	.lab-tag.auto {
		background: var(--warning-light);
		color: #8a6d10;
	}

	/* Assign row */
	.assign-row {
		display: flex;
		gap: 4px;
		align-items: center;
		margin-top: 4px;
	}

	.assign-row select {
		padding: 3px 6px;
		border: 1px solid var(--border);
		border-radius: 3px;
		font-size: 0.85rem;
		background: white;
		max-width: 200px;
	}

	.assign-btn {
		padding: 3px 8px;
		border: 1px solid var(--success);
		border-radius: 3px;
		background: var(--success-light);
		color: var(--success);
		font-size: 0.8rem;
		font-weight: 600;
		cursor: pointer;
		font-family: inherit;
	}

	.assign-btn:hover {
		background: var(--success);
		color: white;
	}

	/* Form info (FP tab) */
	.form-info {
		font-size: 0.8rem;
		margin-top: 4px;
		padding: 4px 8px;
		background: #fef8e8;
		border: 1px solid #f0e4b8;
		border-radius: 4px;
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
	}

	.form-struct {
		color: var(--muted);
	}

	.form-text {
		font-family: 'SF Mono', 'Consolas', monospace;
		font-weight: 600;
		color: #8a6d10;
	}

	.form-ctx {
		color: var(--muted);
	}

	.form-action {
		padding: 1px 6px;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: white;
		font-size: 0.7rem;
		cursor: pointer;
		font-weight: 500;
		font-family: inherit;
	}

	.form-action:hover {
		background: var(--accent-light);
	}

	.form-action.danger {
		border-color: var(--danger);
		color: var(--danger);
	}

	.form-action.danger:hover {
		background: var(--danger-light);
	}

	/* Context picker */
	.ctx-picker-inline {
		position: fixed;
		z-index: 100;
		background: white;
		border: 1px solid var(--accent);
		border-radius: 5px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
		width: 320px;
	}

	.ctx-picker-inline input {
		width: 100%;
		padding: 6px 10px;
		border: none;
		border-bottom: 1px solid var(--border);
		border-radius: 0;
		font-size: 0.85rem;
		outline: none;
	}

	.picker-results {
		max-height: 180px;
		overflow-y: auto;
	}

	.picker-item {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 5px 10px;
		font-size: 0.85rem;
		cursor: pointer;
		background: none;
		border: none;
		width: 100%;
		text-align: left;
		font-family: inherit;
	}

	.picker-item:hover {
		background: var(--accent-light);
	}

	.picker-type {
		font-size: 0.65rem;
		color: var(--muted);
	}

	.picker-item-empty {
		padding: 5px 10px;
		font-size: 0.85rem;
		color: var(--muted);
	}

	.picker-shortcuts {
		padding: 4px 8px;
		border-bottom: 1px solid var(--border);
		display: flex;
		gap: 4px;
	}

	.picker-shortcuts button {
		padding: 2px 8px;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: white;
		font-size: 0.8rem;
		cursor: pointer;
		font-family: inherit;
	}

	.picker-shortcuts button:hover {
		background: var(--accent-light);
	}
</style>
