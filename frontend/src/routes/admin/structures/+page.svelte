<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import { base } from "$app/paths";
	import { api } from "$lib/api";

	/* ── Types ── */

	interface Structure {
		id: number;
		code: string;
		name: string;
		acronym: string | null;
		type: string;
		ror_id: string | null;
		rnsr_id: string | null;
		hal_collection: string | null;
	}

	interface RelatedStructure {
		id: number;
		code: string;
		name: string;
		acronym: string | null;
		type: string;
		relation_id: number;
		relation_type: string;
	}

	interface NameForm {
		id: number;
		form_text: string;
		is_word_boundary: boolean;
		is_active: boolean;
		requires_context_of: (number | string)[] | null;
	}

	interface StructureDetail {
		structure: Structure;
		parents: RelatedStructure[];
		children: RelatedStructure[];
		forms: NameForm[];
	}

	/* ── State ── */

	let allStructures: Structure[] = $state([]);
	let allStructuresCache: Structure[] = $state([]);
	let selectedId: number | null = $state(null);

	let search = $state("");
	let typeFilter = $state("");
	let searchTimeout: ReturnType<typeof setTimeout> | null = null;

	// Detail state
	let detail: StructureDetail | null = $state(null);

	// Relation picker state
	let relationPickerOpen = $state(false);
	let relationPickerSearch = $state("");
	let pickerRelType = $state("");
	let pickerDirection = $state("");
	let pickerStructId: number | null = $state(null);
	let relationPickerEl: HTMLDivElement | undefined = $state();

	// Context picker state
	let ctxPickerOpen = $state(false);
	let ctxPickerSearch = $state("");
	let ctxPickerFormId: number | null = $state(null);
	let ctxPickerCurrentCtx: (number | string)[] = $state([]);
	let ctxPickerEl: HTMLDivElement | undefined = $state();

	// New form state
	let addFormText = $state("");
	let addFormWordBoundary = $state(false);
	let editFormModal: { id: number; form_text: string; is_word_boundary: boolean } | null = $state(null);
	let newFormCtx: (number | string)[] = $state([]);

	// HAL mappings
	interface HalMapping {
		hal_struct_id: number;
		name: string;
		acronym: string | null;
		type: string;
		doc_count: number;
		valid: string | null;
		country: string | null;
		start_date: string | null;
		end_date: string | null;
	}
	let halMappings: HalMapping[] = $state([]);
	let halHelpOpen = $state(false);
	let formsHelpOpen = $state(false);
	let halSearchOpen = $state(false);
	let halSearch = $state("");
	let halSearchResults: any[] = $state([]);
	let halPickerEl: HTMLDivElement | undefined = $state();

	// Create/Edit modal state
	let editMode = $state(false);
	let createModalOpen = $state(false);
	let mCode = $state("");
	let mName = $state("");
	let mAcronym = $state("");
	let mType = $state("labo");
	let mRor = $state("");
	let mHal = $state("");

	// Forms data lookup (for context editing)
	let formsData: Record<number, (number | string)[]> = $state({});

	// Related IDs set for picker exclusion
	let pickerExclude: Set<number> = $state(new Set());

	/* ── Derived ── */

	const structLookup = $derived.by(() => {
		const lookup: Record<number, string> = {};
		for (const s of allStructuresCache) {
			lookup[s.id] = s.acronym || s.code || s.name;
		}
		return lookup;
	});

	const relationPickerResults = $derived.by(() => {
		const q = relationPickerSearch.toLowerCase();
		return allStructuresCache
			.filter((s) => !pickerExclude.has(s.id) && (s.name.toLowerCase().includes(q) || (s.acronym || "").toLowerCase().includes(q) || s.code.toLowerCase().includes(q)))
			.slice(0, 12);
	});

	const ctxPickerResults = $derived.by(() => {
		const q = ctxPickerSearch.toLowerCase();
		const existing = new Set(ctxPickerCurrentCtx.map((x) => String(x)));
		return allStructuresCache
			.filter((s) => !existing.has(String(s.id)) && (s.name.toLowerCase().includes(q) || (s.acronym || "").toLowerCase().includes(q) || s.code.toLowerCase().includes(q)))
			.slice(0, 10);
	});

	const tutelles = $derived(detail ? detail.parents.filter((p) => p.relation_type === "est_tutelle_de") : []);
	const tutellesDe = $derived(detail ? detail.children.filter((c) => c.relation_type === "est_tutelle_de") : []);
	const partenaires = $derived.by(() => {
		if (!detail) return [];
		return [
			...detail.parents.filter((p) => p.relation_type === "est_partenaire_de").map((p) => ({ ...p, id_struct: p.id })),
			...detail.children.filter((c) => c.relation_type === "est_partenaire_de").map((c) => ({ ...c, id_struct: c.id })),
		];
	});

	function rorShortId(rorId: string): string {
		return rorId.replace("https://ror.org/", "");
	}

	function rorFullUrl(rorId: string): string {
		if (rorId.startsWith("http")) return rorId;
		return "https://ror.org/" + rorId;
	}

	function halCollectionUrl(code: string): string {
		return `https://hal.science/search/index/?qa%5BcollCode_s%5D%5B%5D=${code}`;
	}

	/* ── Data loading ── */

	async function loadList() {
		const params = new URLSearchParams();
		if (typeFilter) params.set("type", typeFilter);
		if (search) params.set("search", search);
		allStructures = await api<Structure[]>("/api/structures?" + params);
	}

	async function refreshCache() {
		allStructuresCache = await api<Structure[]>("/api/structures");
	}

	async function selectStructure(id: number) {
		selectedId = id;
		localStorage.setItem("admin_structure_id", String(id));
		const sp = new URLSearchParams(window.location.search);
		sp.set("id", String(id));
		history.replaceState(null, "", "?" + sp.toString());
		const data = await api<StructureDetail>("/api/structures/" + id);
		detail = data;

		// Build forms data lookup
		const fd: Record<number, (number | string)[]> = {};
		for (const f of data.forms) {
			fd[f.id] = f.requires_context_of || [];
		}
		formsData = fd;

		// Build exclusion set for relation picker
		const exclude = new Set<number>([...data.parents.map((p) => p.id), ...data.children.map((c) => c.id), data.structure.id]);
		pickerExclude = exclude;

		// HAL mappings
		halMappings = await api<HalMapping[]>("/api/structures/" + id + "/hal-mappings");

		// Reset pickers et help
		relationPickerOpen = false;
		ctxPickerOpen = false;
		halSearchOpen = false;
		halHelpOpen = false;
		formsHelpOpen = false;
		newFormCtx = [];
	}

	function handleSearch() {
		if (searchTimeout) clearTimeout(searchTimeout);
		searchTimeout = setTimeout(loadList, 300);
	}

	/* ── Relation picker ── */

	function openPicker(relType: string, direction: string, structId: number) {
		pickerRelType = relType;
		pickerDirection = direction;
		pickerStructId = structId;
		relationPickerSearch = "";
		relationPickerOpen = true;
		ctxPickerOpen = false;
	}

	async function pickStructure(otherId: number) {
		const parentId = pickerDirection === "parent" ? otherId : pickerStructId!;
		const childId = pickerDirection === "parent" ? pickerStructId! : otherId;
		await fetch(base + "/api/structure-relations", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				parent_id: parentId,
				child_id: childId,
				relation_type: pickerRelType,
			}),
		});
		relationPickerOpen = false;
		await selectStructure(pickerStructId!);
		loadList();
		refreshCache();
	}

	async function deleteRelation(relId: number) {
		await fetch(base + "/api/structure-relations/" + relId, {
			method: "DELETE",
		});
		if (selectedId) await selectStructure(selectedId);
		loadList();
		refreshCache();
	}

	/* ── Forms ── */

	async function addForm(structId: number) {
		const text = addFormText.trim();
		if (!text) return;
		const ctx = newFormCtx.length ? newFormCtx : null;

		const resp = await fetch(base + "/api/name-forms", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				structure_id: structId,
				form_text: text,
				is_word_boundary: addFormWordBoundary || text.length <= 6,
				requires_context_of: ctx,
			}),
		});
		if (!resp.ok) {
			const err = await resp.json().catch(() => ({ detail: `Erreur ${resp.status}` }));
			alert(err.detail || `Erreur ${resp.status}`);
			return;
		}
		addFormText = "";
		addFormWordBoundary = false;
		newFormCtx = [];
		await selectStructure(structId);
		loadList();
	}

	async function toggleForm(formId: number, active: boolean) {
		await fetch(base + "/api/name-forms/" + formId, {
			method: "PUT",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ is_active: active }),
		});
		if (selectedId) await selectStructure(selectedId);
	}

	async function deleteForm(formId: number) {
		if (!confirm("Supprimer cette forme ?")) return;
		const res = await fetch(base + "/api/name-forms/" + formId, {
			method: "DELETE",
		});
		if (!res.ok) {
			alert("Erreur suppression: " + (await res.text()));
			return;
		}
		if (selectedId) await selectStructure(selectedId);
		loadList();
	}

	function openEditFormModal(f: NameForm) {
		editFormModal = { id: f.id, form_text: f.form_text, is_word_boundary: f.is_word_boundary };
	}

	async function saveEditForm() {
		if (!editFormModal) return;
		const text = editFormModal.form_text.trim();
		await fetch(base + "/api/name-forms/" + editFormModal.id, {
			method: "PUT",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				form_text: text,
				is_word_boundary: editFormModal.is_word_boundary || text.length <= 6,
			}),
		});
		editFormModal = null;
		if (selectedId) await selectStructure(selectedId);
	}

	/* ── Context picker ── */

	function openCtxPicker(formId: number | null) {
		const currentCtx = formId === null ? [...newFormCtx] : [...(formsData[formId] || [])];
		ctxPickerFormId = formId;
		ctxPickerCurrentCtx = currentCtx;
		ctxPickerSearch = "";
		ctxPickerOpen = true;
		relationPickerOpen = false;
	}

	async function pickCtx(item: number | string) {
		if (!ctxPickerCurrentCtx.includes(item)) {
			ctxPickerCurrentCtx = [...ctxPickerCurrentCtx, item];
		}
		ctxPickerOpen = false;

		if (ctxPickerFormId === null) {
			newFormCtx = [...ctxPickerCurrentCtx];
		} else {
			await fetch(base + "/api/name-forms/" + ctxPickerFormId, {
				method: "PUT",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					requires_context_of: ctxPickerCurrentCtx,
				}),
			});
			if (selectedId) await selectStructure(selectedId);
		}
	}

	async function pickCtxClear() {
		ctxPickerOpen = false;

		if (ctxPickerFormId === null) {
			newFormCtx = [];
		} else {
			await fetch(base + "/api/name-forms/" + ctxPickerFormId, {
				method: "PUT",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ requires_context_of: [] }),
			});
			if (selectedId) await selectStructure(selectedId);
		}
	}

	async function removeCtx(formId: number, itemToRemove: number | string) {
		const currentCtx = formsData[formId] || [];
		const newCtx = currentCtx.filter((x) => x !== itemToRemove);
		await fetch(base + "/api/name-forms/" + formId, {
			method: "PUT",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ requires_context_of: newCtx }),
		});
		if (selectedId) await selectStructure(selectedId);
	}

	function removeNewCtx(item: number | string) {
		newFormCtx = newFormCtx.filter((x) => x !== item);
	}

	function ctxLabel(x: number | string): string {
		if (x === "tutelles") return "tutelles";
		return structLookup[x as number] || "id:" + x;
	}

	/* ── Delete structure ── */

	async function deleteStructure(id: number) {
		if (!confirm("Supprimer cette structure et toutes ses formes/relations ?")) return;
		await fetch(base + "/api/structures/" + id, { method: "DELETE" });
		selectedId = null;
		detail = null;
		loadList();
		refreshCache();
	}

	/* ── HAL mapping ── */

	async function searchHalStructures() {
		if (halSearch.length < 2) {
			halSearchResults = [];
			return;
		}
		halSearchResults = await api<any[]>(`/api/hal-structures?unmapped=true&search=${encodeURIComponent(halSearch)}&limit=15`);
	}

	async function mapHalStructure(halStructId: number) {
		if (!selectedId) return;
		await fetch(base + "/api/hal-structures/" + halStructId + "/map", {
			method: "PUT",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ structure_id: selectedId }),
		});
		halSearchOpen = false;
		halSearch = "";
		halSearchResults = [];
		await selectStructure(selectedId);
	}

	async function unmapHalStructure(halStructId: number) {
		await fetch(base + "/api/hal-structures/" + halStructId + "/map", {
			method: "DELETE",
		});
		if (selectedId) await selectStructure(selectedId);
	}

	function normalizeRor(): boolean {
		let ror = mRor.trim();
		if (!ror) return true;
		// Compléter l'URL si juste l'identifiant
		if (/^0[a-z0-9]{8}$/.test(ror)) ror = "https://ror.org/" + ror;
		// Valider le format
		if (!/^https:\/\/ror\.org\/0[a-z0-9]{8}$/.test(ror)) {
			alert("Format ROR invalide. Attendu : https://ror.org/0xxxxxxxxx");
			return false;
		}
		mRor = ror;
		return true;
	}

	/* ── Edit modal ── */

	function openEditModal() {
		if (!detail) return;
		const s = detail.structure;
		mCode = s.code || "";
		mName = s.name || "";
		mAcronym = s.acronym || "";
		mType = s.type || "labo";
		mRor = s.ror_id || "";
		mHal = s.hal_collection || "";
		editMode = true;
		createModalOpen = true;
	}

	async function submitEdit() {
		if (!selectedId) return;
		if (!normalizeRor()) return;
		const data: Record<string, any> = {};
		if (mName.trim()) data.name = mName.trim();
		if (mAcronym.trim() !== (detail?.structure.acronym || "")) data.acronym = mAcronym.trim() || null;
		if (mType) data.type = mType;
		if (mRor.trim() !== (detail?.structure.ror_id || "")) data.ror_id = mRor.trim() || null;
		if (mHal.trim() !== (detail?.structure.hal_collection || "")) data.hal_collection = mHal.trim() || null;

		try {
			const res = await fetch(base + "/api/structures/" + selectedId, {
				method: "PUT",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(data),
			});
			if (!res.ok) throw new Error(await res.text());
			createModalOpen = false;
			editMode = false;
			await selectStructure(selectedId);
			loadList();
			refreshCache();
		} catch (e: any) {
			alert("Erreur: " + e.message);
		}
	}

	/* ── Create modal ── */

	function openCreateModal() {
		editMode = false;
		mCode = "";
		mName = "";
		mAcronym = "";
		mType = "labo";
		mRor = "";
		mHal = "";
		createModalOpen = true;
	}

	async function submitCreate() {
		if (!normalizeRor()) return;
		const data = {
			code: mCode.trim(),
			name: mName.trim(),
			acronym: mAcronym.trim() || null,
			type: mType,
			ror_id: mRor.trim() || null,
			hal_collection: mHal.trim() || null,
		};
		if (!data.code || !data.name) {
			alert("Code et nom requis");
			return;
		}

		try {
			const res = await fetch(base + "/api/structures", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(data),
			});
			if (!res.ok) throw new Error(await res.text());
			const created = await res.json();
			createModalOpen = false;
			await loadList();
			refreshCache();
			selectStructure(created.id);
		} catch (e: any) {
			alert("Erreur: " + e.message);
		}
	}

	/* ── Click-outside handling ── */

	function handleDocumentClick(e: MouseEvent) {
		const target = e.target as HTMLElement;
		if (relationPickerOpen && relationPickerEl && !relationPickerEl.contains(target) && !target.classList.contains("btn-add")) {
			relationPickerOpen = false;
		}
		if (ctxPickerOpen && ctxPickerEl && !ctxPickerEl.contains(target) && !target.classList.contains("btn-add-tiny")) {
			ctxPickerOpen = false;
		}
		if (halSearchOpen && halPickerEl && !halPickerEl.contains(target) && !target.closest(".btn-hal-add")) {
			halSearchOpen = false;
		}
	}

	/* ── Lifecycle ── */

	onMount(() => {
		document.querySelector(".container")?.classList.add("full-width");
		loadList();
		refreshCache();
		document.addEventListener("click", handleDocumentClick);
		// Lire structure_id depuis l'URL ou localStorage
		const sp = new URLSearchParams(window.location.search);
		const urlId = sp.get("id") || localStorage.getItem("admin_structure_id");
		if (urlId) {
			const id = parseInt(urlId);
			if (id) selectStructure(id);
		}
		return () => document.removeEventListener("click", handleDocumentClick);
	});

	onDestroy(() => {
		document.querySelector(".container")?.classList.remove("full-width");
	});
</script>

<svelte:window onkeydown={(e) => {
	if (e.key === "Escape") {
		if (editFormModal) { editFormModal = null; e.preventDefault(); }
		else if (createModalOpen) { createModalOpen = false; e.preventDefault(); }
	}
	if (e.key === "Enter" && !e.shiftKey) {
		if (editFormModal) { e.preventDefault(); saveEditForm(); }
		else if (createModalOpen) { e.preventDefault(); editMode ? submitEdit() : submitCreate(); }
	}
}} />

<svelte:head>
	<title>Admin - Structures - Bibliometrie UCA</title>
</svelte:head>

<div class="layout">
	<!-- LIST PANEL -->
	<div class="list-panel">
		<div class="toolbar">
			<input type="text" placeholder="Rechercher..." bind:value={search} oninput={handleSearch} />
			<select bind:value={typeFilter} onchange={() => loadList()}>
				<option value="">Tous types</option>
				<option value="labo">Laboratoires</option>
				<option value="universite">Universités</option>
				<option value="onr">ONR</option>
				<option value="chu">CHU</option>
				<option value="ecole">Écoles</option>
				<option value="site">Sites</option>
			</select>
		</div>
		<div class="list-header">
			<span class="list-count">{allStructures.length} structures</span>
			<button class="btn btn-primary btn-sm" onclick={openCreateModal}>+ Nouvelle</button>
		</div>
		<div class="panel struct-list">
			{#if allStructures.length === 0}
				<div class="empty-list">Aucune structure</div>
			{:else}
				{#each allStructures as s (s.id)}
					<button class="struct-item" class:active={s.id === selectedId} onclick={() => selectStructure(s.id)}>
						<span class="type-badge type-{s.type}">{s.type}</span>
						<div class="info">
							<div class="name">
								{#if s.acronym}<strong>{s.acronym}</strong> · {s.name}{:else}{s.name}{/if}
							</div>
						</div>
					</button>
				{/each}
			{/if}
		</div>
	</div>

	<!-- DETAIL PANEL -->
	<div class="detail-panel">
		{#if !detail}
			<div class="panel detail-empty">Selectionnez une structure pour voir le detail.</div>
		{:else}
			{@const s = detail.structure}
			<div class="panel">
				<!-- Header -->
				<div class="detail-header">
					<span class="type-badge type-{s.type}">{s.type}</span>
					<h2>
						{#if s.acronym}<strong>{s.acronym}</strong> · {s.name}{:else}{s.name}{/if}
					</h2>
					<button class="btn btn-sm" onclick={openEditModal}> Éditer </button>
					<button class="btn btn-danger btn-sm" onclick={() => deleteStructure(s.id)}> Supprimer </button>
				</div>

				<!-- ═══ SECTION DÉTAILS ═══ -->
				<h3 class="section-title">Détails</h3>
				<div class="details-inline">
					{#if s.ror_id}
						<span class="detail-item">
							<span class="detail-label">ROR</span>
							<a href={rorFullUrl(s.ror_id)} target="_blank" rel="noopener" class="id-badge">{rorShortId(s.ror_id)}</a>
						</span>
					{/if}
					{#if s.rnsr_id}
						<span class="detail-item">
							<span class="detail-label">RNSR</span>
							<span>{s.rnsr_id}</span>
						</span>
					{/if}
					{#if s.hal_collection}
						<span class="detail-item">
							<span class="detail-label">Collection HAL</span>
							<a href={halCollectionUrl(s.hal_collection)} target="_blank" rel="noopener" class="id-badge">{s.hal_collection}</a>
						</span>
					{/if}
				</div>

				<!-- ═══ SECTION RELATIONS ═══ -->
				<h3 class="section-title">Relations</h3>

				<!-- Tutelles -->
				<h3>
					Tutelle{tutelles.length > 1 ? "s" : ""}
					<button class="btn-add" onclick={() => openPicker("est_tutelle_de", "parent", s.id)}>+</button>
				</h3>
				<div>
					{#if tutelles.length === 0}
						<span class="none-text">Aucune</span>
					{:else}
						{#each tutelles as p (p.relation_id)}
							<span class="tag tutelle">
								<button class="tag-name" onclick={() => selectStructure(p.id)}>
									{p.acronym || p.name}
								</button>
								<button class="remove" onclick={() => deleteRelation(p.relation_id)} title="Supprimer">x</button>
							</span>
						{/each}
					{/if}
				</div>

				<!-- Est tutelle de -->
				<h3>
					Est tutelle de
					<button class="btn-add" onclick={() => openPicker("est_tutelle_de", "child", s.id)}>+</button>
				</h3>
				<div>
					{#if tutellesDe.length === 0}
						<span class="none-text">Aucun</span>
					{:else}
						{#each tutellesDe as c (c.relation_id)}
							<span class="tag tutelle">
								<button class="tag-name" onclick={() => selectStructure(c.id)}>
									{c.acronym || c.name}
								</button>
								<button class="remove" onclick={() => deleteRelation(c.relation_id)} title="Supprimer">x</button>
							</span>
						{/each}
					{/if}
				</div>

				<!-- Partenaires -->
				<h3>
					Partenaire{partenaires.length > 1 ? "s" : ""}
					<button class="btn-add" onclick={() => openPicker("est_partenaire_de", "parent", s.id)}>+</button>
				</h3>
				<div>
					{#if partenaires.length === 0}
						<span class="none-text">Aucun</span>
					{:else}
						{#each partenaires as p (p.relation_id)}
							<span class="tag partenaire">
								<button class="tag-name" onclick={() => selectStructure(p.id_struct)}>
									{p.acronym || p.name}
								</button>
								<button class="remove" onclick={() => deleteRelation(p.relation_id)} title="Supprimer">x</button>
							</span>
						{/each}
					{/if}
				</div>

				<!-- Relation picker -->
				{#if relationPickerOpen}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div class="picker-container" bind:this={relationPickerEl} onclick={(e) => e.stopPropagation()}>
						<input type="text" placeholder="Rechercher une structure..." bind:value={relationPickerSearch} autocomplete="off" />
						<div class="picker-results">
							{#if relationPickerResults.length === 0}
								<div class="picker-item disabled">Aucun résultat</div>
							{:else}
								{#each relationPickerResults as rs (rs.id)}
									<button class="picker-item" onclick={() => pickStructure(rs.id)}>
										<span class="type-badge type-{rs.type}" style="font-size: 0.65rem;padding:0 5px">
											{rs.type}
										</span>
										{rs.acronym ? rs.acronym + " \u2014 " : ""}{rs.name}
									</button>
								{/each}
							{/if}
						</div>
					</div>
				{/if}

				<!-- ═══ SECTION IDENTIFICATION DANS LES PUBLICATIONS ═══ -->
				<h3 class="section-title">Identification dans les publications</h3>

				<!-- HAL structures mappées -->
				<h3>
					Structures HAL ({halMappings.length})
					<button
						class="btn-help-icon"
						onclick={() => {
							halHelpOpen = !halHelpOpen;
						}}
						title="Aide"
						><svg
							xmlns="http://www.w3.org/2000/svg"
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg
						></button
					>
				</h3>
				{#if halHelpOpen}
					<p class="help-text">
						Le mapping avec les structures HAL permet d'identifier les affiliations des publications issues de HAL. Les changements seront pris en compte à la prochaine exécution du
						pipeline. Pour une prise en compte immédiate, relancer le pipeline à partir de l'étape `affiliations` : <code>python run_pipeline.py --from affiliations</code>
					</p>
				{/if}
				{#if halMappings.length === 0 && !halSearchOpen}
					<span class="none-text">Aucune structure HAL mappée</span>
				{:else}
					<table class="hal-table">
						<thead>
							<tr>
								<th>ID HAL</th>
								<th>Nom</th>
								<th>Sigle</th>
								<th>Type</th>
								<th>Début</th>
								<th>Fin</th>
								<th>Publis</th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							{#each halMappings as hm (hm.hal_struct_id)}
								<tr class:hal-valid={hm.valid === "VALID"} class:hal-old={hm.valid === "OLD"} class:hal-incoming={hm.valid === "INCOMING"}>
									<td><a href="https://aurehal.archives-ouvertes.fr/structure/read/id/{hm.hal_struct_id}" target="_blank" rel="noopener" class="id-badge">{hm.hal_struct_id}</a></td>
									<td>{hm.name || ""}</td>
									<td>{hm.acronym || ""}</td>
									<td>{hm.type || ""}</td>
									<td>{hm.start_date || ""}</td>
									<td>{hm.end_date || ""}</td>
									<td>{hm.doc_count || 0}</td>
									<td>
										<button class="btn btn-sm btn-danger-outline" onclick={() => unmapHalStructure(hm.hal_struct_id)} title="Supprimer le mapping">x</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
				<button
					class="btn btn-sm btn-hal-add"
					style="margin-top: 6px;"
					onclick={() => {
						halSearchOpen = !halSearchOpen;
						halSearch = "";
						halSearchResults = [];
					}}>{halSearchOpen ? "Annuler" : "Ajouter"}</button
				>
				{#if halSearchOpen}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div class="picker-container" style="margin-top: 8px;" bind:this={halPickerEl} onclick={(e) => e.stopPropagation()}>
						<input type="text" placeholder="Rechercher une structure HAL non mappée..." bind:value={halSearch} oninput={searchHalStructures} autocomplete="off" />
						<div class="picker-results">
							{#if halSearchResults.length === 0}
								<div class="picker-item disabled">
									{halSearch.length < 2 ? "Tapez au moins 2 caractères" : "Aucun résultat"}
								</div>
							{:else}
								{#each halSearchResults as hs (hs.hal_struct_id)}
									<button class="picker-item" onclick={() => mapHalStructure(hs.hal_struct_id)}>
										{hs.acronym ? hs.acronym + " — " : ""}{hs.name}
										<span style="color: var(--muted); font-size: 0.8rem; margin-left: auto;">
											{hs.type} · {hs.doc_count || 0} docs
										</span>
									</button>
								{/each}
							{/if}
						</div>
					</div>
				{/if}

				<!-- Forms table -->
				<h3>
					Formes de noms ({detail.forms.length})
					<button
						class="btn-help-icon"
						onclick={() => {
							formsHelpOpen = !formsHelpOpen;
						}}
						title="Aide"
						><svg
							xmlns="http://www.w3.org/2000/svg"
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg
						></button
					>
				</h3>
				{#if formsHelpOpen}
					<p class="help-text">
						Les formes de nom servent à identifier les affiliations des publications issues d'OpenAlex et WoS, via les adresses associées aux publications. Les changements seront pris en compte à la prochaine exécution du pipeline. Pour une prise en compte immédiate, relancer à partir de l'étape `addresses` : <code>python run_pipeline.py --from addresses</code>
					</p>
				{/if}
				<table class="forms-table">
					<thead>
						<tr><th class="col-badge"></th><th>Forme</th><th>Contexte requis</th><th></th></tr>
					</thead>
					<tbody>
						{#if detail.forms.length === 0}
							<tr>
								<td colspan="4" style="text-align:center;color:var(--text-muted)"> Aucune forme </td>
							</tr>
						{:else}
							{#each detail.forms as f (f.id)}
								<tr class:inactive={!f.is_active}>
									<td class="col-badge">{#if f.is_word_boundary || f.form_text.length <= 6}<span class="match-badge word" title="Mot entier">mot entier</span>{:else}<span class="match-badge substr" title="Sous-chaîne">sous-chaîne</span>{/if}</td>
									<td class="form-text">{f.form_text}</td>
									<td>
										{#if f.requires_context_of?.length}
											{#each f.requires_context_of as x}
												<span class="ctx-tag">
													{#if x === "tutelles"}tutelles{:else}{ctxLabel(x)}{/if}
													<button class="ctx-remove" onclick={() => removeCtx(f.id, x)}>x</button>
												</span>
											{/each}
											<button class="btn-add-tiny" onclick={() => openCtxPicker(f.id)}> + </button>
										{:else}
											<span class="sufficient-label">suffisant</span>
											<button class="btn-add-tiny" onclick={() => openCtxPicker(f.id)}> + </button>
										{/if}
									</td>
									<td style="white-space:nowrap">
										<button class="btn btn-sm" onclick={() => openEditFormModal(f)} title="Modifier">✎</button>
										<button class="btn btn-sm btn-danger-outline" onclick={() => deleteForm(f.id)} title="Supprimer">x</button>
									</td>
								</tr>
							{/each}
						{/if}
					</tbody>
				</table>

				<!-- Add form row -->
				<div class="add-row">
					<input placeholder="Nouvelle forme..." bind:value={addFormText} />
					<label class="regex-label">
						<input type="checkbox" checked={addFormWordBoundary || addFormText.length <= 6} disabled={addFormText.length <= 6} onchange={(e) => { addFormWordBoundary = (e.target as HTMLInputElement).checked; }} /> mot entier
					</label>
					<button class="btn btn-sm btn-primary" onclick={() => addForm(s.id)}> Ajouter </button>
				</div>

				<!-- New form context tags -->
				<div class="new-form-ctx">
					<span class="ctx-label-text">Contexte :</span>
					{#each newFormCtx as x}
						<span class="ctx-tag">
							{#if x === "tutelles"}tutelles{:else}{ctxLabel(x)}{/if}
							<button class="ctx-remove" onclick={() => removeNewCtx(x)}>x</button>
						</span>
					{/each}
					<button class="btn-add-tiny" onclick={() => openCtxPicker(null)}>+</button>
					{#if newFormCtx.length === 0}
						<span class="ctx-hint">(suffisant)</span>
					{/if}
				</div>

				<!-- Context picker -->
				{#if ctxPickerOpen}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div class="picker-container ctx-picker" bind:this={ctxPickerEl} onclick={(e) => e.stopPropagation()}>
						<div class="ctx-picker-shortcuts">
							<button class="btn btn-sm" onclick={() => pickCtx("tutelles")}> tutelles </button>
							<button class="btn btn-sm" onclick={pickCtxClear}> &#x2715; suffisant </button>
						</div>
						<input type="text" placeholder="Rechercher une structure..." bind:value={ctxPickerSearch} autocomplete="off" />
						<div class="picker-results">
							{#if ctxPickerResults.length === 0}
								<div class="picker-item disabled">Aucun résultat</div>
							{:else}
								{#each ctxPickerResults as cs (cs.id)}
									<button class="picker-item" onclick={() => pickCtx(cs.id)}>
										<span class="type-badge type-{cs.type}" style="font-size: 0.65rem;padding:0 5px">
											{cs.type}
										</span>
										{cs.acronym ? cs.acronym + " \u2014 " : ""}{cs.name}
									</button>
								{/each}
							{/if}
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>

<!-- EDIT FORM MODAL -->
{#if editFormModal}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="modal-bg" onclick={() => (editFormModal = null)}>
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="modal" onclick={(e) => e.stopPropagation()}>
			<h3>Modifier la forme de nom</h3>
			<label>Texte</label>
			<input bind:value={editFormModal.form_text} />
			<div class="modal-options">
				<label>
					<input type="checkbox" checked={editFormModal.is_word_boundary || editFormModal.form_text.length <= 6} disabled={editFormModal.form_text.length <= 6} onchange={(e) => { if (editFormModal) editFormModal.is_word_boundary = (e.target as HTMLInputElement).checked; }} /> Mot entier
				</label>
			</div>
			<div class="actions">
				<button class="btn" onclick={() => (editFormModal = null)}>Annuler</button>
				<button class="btn btn-primary" onclick={saveEditForm}>Enregistrer</button>
			</div>
		</div>
	</div>
{/if}

<!-- CREATE MODAL -->
{#if createModalOpen}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="modal-bg" onclick={() => (createModalOpen = false)}>
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="modal" onclick={(e) => e.stopPropagation()}>
			<h3>{editMode ? "Modifier la structure" : "Nouvelle structure"}</h3>
			<label>Code (unique)</label>
			<input placeholder="ex: lpc, chu_clermont, site_cezeaux" bind:value={mCode} disabled={editMode} />
			<label>Nom complet</label>
			<input placeholder="ex: Laboratoire de Physique de Clermont" bind:value={mName} />
			<label>Acronyme</label>
			<input placeholder="ex: LPC" bind:value={mAcronym} />
			<label>Type</label>
			<select bind:value={mType}>
				<option value="labo">Laboratoire</option>
				<option value="universite">Université</option>
				<option value="onr">ONR</option>
				<option value="chu">CHU</option>
				<option value="ecole">École</option>
				<option value="site">Site</option>
				<option value="autre">Autre</option>
			</select>
			<label>ROR ID</label>
			<input placeholder="https://ror.org/0xxxxxxxxx" bind:value={mRor} />
			<label>Collection HAL</label>
			<input placeholder="ex: INSTITUT_PASCAL" bind:value={mHal} />
			<div class="actions">
				<button class="btn" onclick={() => (createModalOpen = false)}>Annuler</button>
				<button class="btn btn-primary" onclick={editMode ? submitEdit : submitCreate}>
					{editMode ? "Enregistrer" : "Créer"}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	/* Sortir du conteneur pour utiliser toute la largeur */
	:global(.container.full-width) {
		max-width: none;
		padding: 0 !important;
	}

	/* ── Layout ── */
	.layout {
		display: flex;
		gap: 0;
		min-height: calc(100vh - 120px);
	}
	.list-panel {
		width: 550px;
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 16px;
		border-right: 1px solid var(--border);
		background: #fafaf8;
	}
	.detail-panel {
		flex: 1;
		min-width: 0;
		padding: 16px 24px;
	}

	.panel {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 14px;
	}
	.panel h2 {
		margin: 0 0 10px;
		font-size: 1.05rem;
		font-weight: 600;
	}
	.panel h3 {
		margin: 12px 0 6px;
		font-size: 0.95rem;
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}
	.section-title {
		margin: 20px -14px 10px !important;
		padding: 6px 14px !important;
		background: #5b9ea0;
		color: white !important;
		font-size: 0.75rem !important;
		border-radius: 3px;
	}
	.details-inline {
		display: flex;
		flex-wrap: wrap;
		gap: 16px;
		margin-bottom: 8px;
		font-size: 0.9rem;
	}
	.detail-item {
		display: flex;
		align-items: center;
		gap: 5px;
	}
	.detail-label {
		color: var(--muted);
		font-weight: 500;
		font-size: 0.8rem;
	}
	.btn-help-icon {
		background: none;
		border: none;
		color: var(--muted);
		cursor: pointer;
		padding: 0;
		margin-left: 4px;
		vertical-align: middle;
		line-height: 1;
	}
	.btn-help-icon:hover {
		color: var(--accent);
	}
	.help-text {
		background: var(--accent-light);
		border: 1px solid #c4d8ed;
		border-radius: 5px;
		padding: 8px 12px;
		margin: 4px 0 8px;
		font-size: 0.85rem;
		color: #2c3e50;
		line-height: 1.5;
	}

	/* ── Toolbar ── */
	.toolbar {
		display: flex;
		gap: 6px;
		margin-bottom: 8px;
	}
	.toolbar input,
	.toolbar select {
		padding: 5px 8px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.95rem;
		background: white;
		font-family: inherit;
	}
	.toolbar input {
		flex: 1;
	}

	/* ── List header ── */
	.list-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 4px;
	}
	.list-count {
		font-size: 0.85rem;
		color: var(--text-muted);
	}

	/* ── Structure list ── */
	.struct-list {
		overflow-y: auto;
		max-height: calc(100vh - 240px);
		padding: 0;
	}
	.empty-list {
		padding: 20px;
		text-align: center;
		color: var(--text-muted);
	}
	.struct-item {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 8px 10px;
		border: none;
		border-bottom: 1px solid #f0efec;
		cursor: pointer;
		background: none;
		text-align: left;
		font-family: inherit;
		font-size: inherit;
		color: inherit;
	}
	.struct-item:hover {
		background: #fafaf8;
	}
	.struct-item.active {
		background: var(--accent-light);
		border-left: 3px solid var(--accent);
	}
	.struct-item .info {
		flex: 1;
		min-width: 0;
	}
	.struct-item .name {
		font-weight: 500;
		font-size: 0.95rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* ── Type badges ── */
	.type-badge {
		font-size: 0.7rem;
		padding: 1px 6px;
		border-radius: 8px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.3px;
		white-space: nowrap;
	}
	:global(.type-universite) {
		background: #e8d4f0;
		color: #6b2e8a;
	}
	:global(.type-onr) {
		background: #d4e8f0;
		color: #2e6b8a;
	}
	:global(.type-chu) {
		background: #f0d4d4;
		color: #8a2e2e;
	}
	:global(.type-ecole) {
		background: #f0e8d4;
		color: #8a6b2e;
	}
	:global(.type-labo) {
		background: var(--accent-light);
		color: var(--accent);
	}
	:global(.type-site) {
		background: var(--success-light);
		color: var(--success);
	}
	:global(.type-autre) {
		background: #f0f0f0;
		color: #555;
	}

	/* ── Detail ── */
	.detail-empty {
		text-align: center;
		padding: 60px 20px;
		color: var(--text-muted);
	}
	.detail-header {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 14px;
	}
	.detail-header h2 {
		flex: 1;
		margin: 0;
		font-size: 1.3rem;
	}

	/* ── Tags ── */
	.tag {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 0.85rem;
		padding: 2px 8px;
		border-radius: 10px;
		margin: 2px;
		background: #f0f0f0;
	}
	.tag .tag-name {
		cursor: pointer;
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		color: inherit;
	}
	.tag .tag-name:hover {
		text-decoration: underline;
	}
	.tag .remove {
		cursor: pointer;
		color: var(--danger);
		font-weight: bold;
		font-size: 1rem;
		line-height: 1;
		background: none;
		border: none;
		padding: 0;
		font-family: inherit;
	}
	.tag .remove:hover {
		color: #e74c3c;
	}
	.tag.tutelle {
		background: #d4e8f0;
		color: #2e6b8a;
	}
	.tag.partenaire {
		background: #f0e8d4;
		color: #8a6b2e;
	}
	.hal-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
		margin-bottom: 8px;
	}
	.hal-table th {
		text-align: left;
		padding: 4px 8px;
		font-size: 0.75rem;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		font-weight: 600;
	}
	.hal-table td {
		padding: 4px 8px;
		border-bottom: 1px solid #f0efec;
		vertical-align: middle;
	}
	.hal-table tr.hal-valid td {
		background: #dff0d8;
	}
	.hal-table tr.hal-old td {
		background: #fcf8e3;
	}
	.hal-table tr.hal-incoming td {
		background: #f2dede;
	}
	.hal-table tr:hover td {
		filter: brightness(0.97);
	}
	.none-text {
		font-size: 0.85rem;
		color: var(--text-muted);
	}

	/* ── Forms table ── */
	.forms-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.95rem;
	}
	.forms-table th {
		text-align: left;
		padding: 5px 8px;
		font-size: 0.8rem;
		color: var(--text-muted);
		border-bottom: 2px solid var(--border);
		font-weight: 600;
	}
	.forms-table td {
		padding: 5px 8px;
		border-bottom: 1px solid #f0efec;
		vertical-align: middle;
	}
	.forms-table tr:hover td {
		background: #fafaf8;
	}
	.forms-table td:last-child,
	.hal-table td:last-child {
		width: 36px;
		text-align: right;
	}
	.forms-table .inactive {
		opacity: 0.45;
	}
	.modal-options {
		display: flex;
		gap: 16px;
		margin: 10px 0;
		font-size: 0.9rem;
	}
	.modal-options label {
		display: flex;
		align-items: center;
		gap: 4px;
		cursor: pointer;
		font-weight: normal;
		margin: 0;
	}
	.edit-form-input {
		width: 100%;
		padding: 2px 4px;
		font-family: "SF Mono", Consolas, monospace;
		font-size: 0.85rem;
		border: 1px solid var(--accent);
		border-radius: 3px;
	}
	.form-text {
		font-family: "SF Mono", Consolas, monospace;
		font-size: 0.85rem;
	}
	.col-badge {
		width: 1px;
		white-space: nowrap;
		padding-right: 0 !important;
	}
	.match-badge {
		font-size: 0.65rem;
		padding: 1px 5px;
		border-radius: 8px;
		font-weight: 500;
		white-space: nowrap;
	}
	.match-badge.word {
		background: #e8f0e8;
		color: #2e6b2e;
	}
	.match-badge.substr {
		background: #f0f0f0;
		color: #888;
	}
	.match-badge.regex {
		background: #fcf8e3;
		color: #8a6d10;
	}
	.ctx-tag {
		font-size: 0.7rem;
		padding: 1px 5px;
		border-radius: 6px;
		background: var(--warning-light);
		color: #8a6d10;
		display: inline-flex;
		align-items: center;
		gap: 3px;
	}
	.ctx-remove {
		cursor: pointer;
		color: var(--danger);
		font-weight: bold;
		font-size: 0.85rem;
		line-height: 1;
		background: none;
		border: none;
		padding: 0;
		font-family: inherit;
	}
	.ctx-remove:hover {
		color: #e74c3c;
	}
	.sufficient-label {
		color: var(--success);
		font-size: 0.8rem;
	}

	/* ── Buttons (page-specific) ── */
	.btn-add {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		border: 1px solid var(--border);
		background: white;
		color: var(--accent);
		font-size: 0.85rem;
		font-weight: bold;
		cursor: pointer;
		margin-left: 6px;
		vertical-align: middle;
		line-height: 1;
		padding: 0 0 1px 0;
	}
	.btn-add:hover {
		background: var(--accent);
		color: white;
		border-color: var(--accent);
	}
	.btn-add-tiny {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		border-radius: 50%;
		border: 1px solid var(--border);
		background: white;
		color: var(--accent);
		font-size: 0.8rem;
		font-weight: bold;
		cursor: pointer;
		vertical-align: middle;
		line-height: 1;
		padding: 0;
	}
	.btn-add-tiny:hover {
		background: var(--accent);
		color: white;
		border-color: var(--accent);
	}

	/* ── Add form row ── */
	.add-row {
		display: flex;
		gap: 4px;
		margin-top: 8px;
		align-items: center;
	}
	.add-row input[type="text"],
	.add-row input:not([type]) {
		flex: 1;
		padding: 4px 6px;
		border: 1px solid var(--border);
		border-radius: 3px;
		font-size: 0.85rem;
		font-family: inherit;
	}
	.regex-label {
		font-size: 0.8rem;
		display: flex;
		align-items: center;
		gap: 3px;
		margin: 0;
		cursor: pointer;
	}

	/* ── New form context ── */
	.new-form-ctx {
		margin-top: 4px;
		font-size: 0.85rem;
	}
	.ctx-label-text {
		color: var(--text-muted);
	}
	.ctx-hint {
		color: var(--text-muted);
		font-size: 0.8rem;
		margin-left: 4px;
	}

	/* ── Picker ── */
	.picker-container {
		position: relative;
		margin: 8px 0;
		background: white;
		border: 1px solid var(--accent);
		border-radius: 5px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
		max-width: 380px;
		z-index: 50;
	}
	.picker-container input {
		width: 100%;
		padding: 7px 10px;
		border: none;
		border-bottom: 1px solid var(--border);
		border-radius: 5px 5px 0 0;
		font-size: 0.95rem;
		outline: none;
		font-family: inherit;
	}
	.picker-results {
		max-height: 200px;
		overflow-y: auto;
	}
	.picker-item {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		padding: 6px 10px;
		font-size: 0.95rem;
		cursor: pointer;
		background: none;
		border: none;
		text-align: left;
		font-family: inherit;
		color: inherit;
	}
	.picker-item:hover {
		background: var(--accent-light);
	}
	.picker-item.disabled {
		color: var(--text-muted);
		cursor: default;
	}

	.ctx-picker {
		max-width: 380px;
	}
	.ctx-picker-shortcuts {
		padding: 6px 10px;
		border-bottom: 1px solid var(--border);
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}

	/* ── Modal ── */
	.modal-bg {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.3);
		z-index: 200;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.modal {
		background: white;
		border-radius: 8px;
		padding: 20px;
		width: 420px;
		max-width: 90vw;
		box-shadow: 0 8px 30px rgba(0, 0, 0, 0.2);
	}
	.modal h3 {
		margin: 0 0 14px;
		font-size: 1.15rem;
		color: var(--text);
		text-transform: none;
		letter-spacing: normal;
	}
	.modal label {
		display: block;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--text-muted);
		margin: 8px 0 3px;
	}
	.modal input,
	.modal select {
		width: 100%;
		padding: 6px 8px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.95rem;
		font-family: inherit;
	}
	.modal .actions {
		display: flex;
		gap: 8px;
		justify-content: flex-end;
		margin-top: 16px;
	}
</style>
