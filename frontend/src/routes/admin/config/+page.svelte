<script lang="ts">
	import { onMount } from "svelte";
	import { base } from "$app/paths";
	import { api } from "$lib/api";

	interface ConfigItem { key: string; value: any; description: string | null; updated_at: string; }
	interface PerimeterStructure { id: number; name: string; acronym: string | null; code: string; }
	interface Perimeter { id: number; code: string; name: string; description: string | null; structure_ids: number[]; structures: PerimeterStructure[]; structure_count: number; }
	interface HalCollections { collections: Record<string, string>; count: number; }

	let configs: ConfigItem[] = $state([]);
	let perimeters: Perimeter[] = $state([]);
	let halCollections: HalCollections = $state({ collections: {}, count: 0 });
	let editingKey: string | null = $state(null);
	let editValue = $state("");
	let saving = $state(false);

	// Perimeter structure add
	let addStructPerimeterId: number | null = $state(null);
	let structSearch = $state("");
	let structResults: any[] = $state([]);

	function currentYear(): number { return new Date().getFullYear(); }

	function computeYears(offset: number): string {
		const y = currentYear();
		return Array.from({ length: offset + 1 }, (_, i) => y - offset + i).join(", ");
	}

	function configByKey(key: string): ConfigItem | undefined { return configs.find(c => c.key === key); }

	async function load() {
		configs = await api<ConfigItem[]>("/api/config");
		perimeters = await api<Perimeter[]>("/api/perimeters");
		halCollections = await api<HalCollections>("/api/config/hal-collections");
	}

	function startEdit(key: string) {
		const item = configByKey(key);
		if (!item) return;
		editingKey = key;
		if (typeof item.value === "string") {
			editValue = item.value;
		} else {
			editValue = JSON.stringify(item.value, null, typeof item.value === "object" ? 2 : undefined);
		}
	}

	async function save(key: string) {
		saving = true;
		try {
			let parsed;
			try { parsed = JSON.parse(editValue); } catch { parsed = editValue; }
			const res = await fetch(base + "/api/config/" + key, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: parsed }) });
			if (!res.ok) throw new Error(await res.text());
			editingKey = null;
			await load();
		} catch (e: any) { alert("Erreur : " + e.message); }
		saving = false;
	}

	async function searchStructures() {
		if (structSearch.length < 2) { structResults = []; return; }
		structResults = await api<any[]>(`/api/structures?search=${encodeURIComponent(structSearch)}`);
	}

	async function addPerimeterStructure(structureId: number) {
		if (!addStructPerimeterId) return;
		await fetch(base + `/api/perimeters/${addStructPerimeterId}/structures`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ structure_id: structureId }) });
		addStructPerimeterId = null;
		structSearch = "";
		structResults = [];
		await load();
	}

	async function removePerimeterStructure(perimeterId: number, structureId: number) {
		await fetch(base + `/api/perimeters/${perimeterId}/structures/${structureId}`, { method: "DELETE" });
		await load();
	}

	onMount(load);
</script>

<svelte:head><title>Configuration — Bibliométrie UCA</title></svelte:head>

<h2>Configuration du pipeline</h2>
<p class="subtitle">Les modifications prennent effet au prochain lancement du pipeline.</p>

<!-- ═══ API ═══ -->
<h3 class="section-title">API</h3>
<div class="config-grid">
	{#each ["openalex_email", "wos_api_key", "scanr_username", "scanr_password"] as key}
		{@const isSecret = key === "wos_api_key" || key === "scanr_password"}
		{#if configByKey(key)}
			<div class="config-row">
				<span class="config-label">{
					key === "openalex_email" ? "OpenAlex — Email (polite pool)" :
					key === "wos_api_key" ? "WoS — Clé API" :
					key === "scanr_username" ? "ScanR — Identifiant" :
					key === "scanr_password" ? "ScanR — Mot de passe" : key
				}</span>
				{#if editingKey === key}
					<input class="config-editor-inline" style="width: 300px;" bind:value={editValue} onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); save(key); }}} />
					<span class="config-actions-inline">
						<button class="btn btn-sm btn-primary" onclick={() => save(key)} disabled={saving}>OK</button>
						<button class="btn btn-sm" onclick={() => { editingKey = null; }}>Annuler</button>
					</span>
				{:else}
					<span class="config-value-inline">{isSecret ? "••••••••" : (configByKey(key)?.value || "(non défini)")}</span>
					<button class="btn btn-sm" onclick={() => startEdit(key)}>Modifier</button>
				{/if}
			</div>
		{/if}
	{/each}
</div>

<!-- ═══ ANNÉES ═══ -->
<h3 class="section-title">Années d'extraction</h3>
<div class="config-grid">
	{#each ["pipeline_years_full", "pipeline_years_weekly"] as key}
		{@const item = configByKey(key)}
		{#if item}
			<div class="config-row">
				<span class="config-label">{key === "pipeline_years_full" ? "Mode full / monthly" : "Mode weekly"}</span>
				{#if editingKey === key}
					<input class="config-editor-inline" bind:value={editValue} onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); save(key); }}} />
					<button class="btn btn-sm btn-primary" onclick={() => save(key)} disabled={saving}>OK</button>
					<button class="btn btn-sm" onclick={() => { editingKey = null; }}>Annuler</button>
				{:else}
					<span class="config-value-inline">{typeof item.value === "number" ? `Année en cours${item.value > 0 ? ` + ${item.value} an${item.value > 1 ? 's' : ''}` : ''} → ${computeYears(item.value)}` : item.value}</span>
					<button class="btn btn-sm" onclick={() => startEdit(key)}>Modifier</button>
				{/if}
			</div>
		{/if}
	{/each}
</div>

<!-- ═══ AFFILIATIONS ═══ -->
<h3 class="section-title">Affiliations par source</h3>
<div class="config-grid">
	{#if configByKey("openalex_institution_ids")}
		<div class="config-row">
			<span class="config-label">OpenAlex — Institutions</span>
			{#if editingKey === "openalex_institution_ids"}
				<textarea class="config-editor" bind:value={editValue} rows={3}></textarea>
				<div class="config-actions">
					<button class="btn btn-sm btn-primary" onclick={() => save("openalex_institution_ids")} disabled={saving}>OK</button>
					<button class="btn btn-sm" onclick={() => { editingKey = null; }}>Annuler</button>
				</div>
			{:else}
				<span class="config-value-inline">{Array.isArray(configByKey("openalex_institution_ids")?.value) ? configByKey("openalex_institution_ids")?.value.join(", ") : configByKey("openalex_institution_ids")?.value}</span>
				<button class="btn btn-sm" onclick={() => startEdit("openalex_institution_ids")}>Modifier</button>
			{/if}
		</div>
	{/if}
	{#if configByKey("wos_affiliations")}
		<div class="config-row">
			<span class="config-label">WoS — Affiliations OG</span>
			{#if editingKey === "wos_affiliations"}
				<textarea class="config-editor" bind:value={editValue} rows={4}></textarea>
				<div class="config-actions">
					<button class="btn btn-sm btn-primary" onclick={() => save("wos_affiliations")} disabled={saving}>OK</button>
					<button class="btn btn-sm" onclick={() => { editingKey = null; }}>Annuler</button>
				</div>
			{:else}
				<span class="config-value-inline">{Array.isArray(configByKey("wos_affiliations")?.value) ? configByKey("wos_affiliations")?.value.join(", ") : configByKey("wos_affiliations")?.value}</span>
				<button class="btn btn-sm" onclick={() => startEdit("wos_affiliations")}>Modifier</button>
			{/if}
		</div>
	{/if}
	{#if configByKey("scanr_affiliation_ids")}
		<div class="config-row">
			<span class="config-label">ScanR — Affiliations SIREN</span>
			{#if editingKey === "scanr_affiliation_ids"}
				<textarea class="config-editor" bind:value={editValue} rows={3}></textarea>
				<div class="config-actions">
					<button class="btn btn-sm btn-primary" onclick={() => save("scanr_affiliation_ids")} disabled={saving}>OK</button>
					<button class="btn btn-sm" onclick={() => { editingKey = null; }}>Annuler</button>
				</div>
			{:else}
				<span class="config-value-inline">{Array.isArray(configByKey("scanr_affiliation_ids")?.value) ? configByKey("scanr_affiliation_ids")?.value.join(", ") : configByKey("scanr_affiliation_ids")?.value}</span>
				<button class="btn btn-sm" onclick={() => startEdit("scanr_affiliation_ids")}>Modifier</button>
			{/if}
		</div>
	{/if}
	<div class="config-row" style="flex-wrap: wrap;">
		<span class="config-label">HAL — Collections</span>
		<div class="hal-coll-list">
			{#each Object.entries(halCollections.collections) as [code, label]}
				<span class="hal-coll-tag">{code} <span class="hal-coll-label">({label})</span></span>
			{/each}
			{#if Object.keys(halCollections.collections).length === 0}
				<span class="none-text">Aucune collection</span>
			{/if}
		</div>
		<span class="config-hint">Dérivées des structures du périmètre UCA ayant un champ "Collection HAL" renseigné (<a href="{base}/admin/structures">structures</a>).</span>
	</div>
</div>


<!-- ═══ PÉRIMÈTRES ═══ -->
<h3 class="section-title">Périmètres</h3>
<p class="help-text">Chaque périmètre est défini par une liste de structures racines. Les sous-structures en tutelle sont incluses récursivement.</p>
{#each perimeters as perim (perim.id)}
	<div class="perimeter-card">
		<div class="perimeter-header">
			<strong>{perim.name}</strong>
			<span class="perimeter-code">{perim.code}</span>
			<span class="perimeter-count">{perim.structure_count} structures</span>
		</div>
		{#if perim.description}
			<p class="perimeter-desc">{perim.description}</p>
		{/if}
		<div class="perimeter-rules">
			{#each perim.structures as struct (struct.id)}
				<span class="tag">
					{struct.acronym || struct.name}
					<button class="remove" onclick={() => removePerimeterStructure(perim.id, struct.id)} title="Retirer">x</button>
				</span>
			{/each}
		</div>
		{#if addStructPerimeterId === perim.id}
			<div class="rule-add-form">
				<input type="text" placeholder="Rechercher une structure..." bind:value={structSearch} oninput={searchStructures} autocomplete="off" />
				<button class="btn btn-sm" onclick={() => { addStructPerimeterId = null; }}>Annuler</button>
				{#if structResults.length > 0}
					<div class="rule-results">
						{#each structResults.slice(0, 10) as s (s.id)}
							<button class="picker-item" onclick={() => addPerimeterStructure(s.id)}>{s.acronym ? s.acronym + " — " : ""}{s.name}</button>
						{/each}
					</div>
				{/if}
			</div>
		{:else}
			<button class="btn btn-sm" style="margin-top: 6px;" onclick={() => { addStructPerimeterId = perim.id; structSearch = ""; structResults = []; }}>Ajouter</button>
		{/if}
	</div>
{/each}

<style>
	h2 { font-size: 1.2rem; font-weight: 600; margin: 0 0 4px; }
	.subtitle { color: var(--muted); font-size: 0.9rem; margin: 0 0 20px; }
	.section-title { margin: 24px 0 8px; padding: 6px 14px; background: #5b9ea0; color: white; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; border-radius: 3px; }
	.help-text { background: var(--accent-light); border: 1px solid #c4d8ed; border-radius: 5px; padding: 8px 12px; margin: 4px 0 12px; font-size: 0.85rem; color: #2c3e50; line-height: 1.5; }

	.config-grid { display: flex; flex-direction: column; gap: 8px; max-width: 800px; margin-bottom: 8px; }
	.config-row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--card); border: 1px solid var(--border); border-radius: 5px; }
	.config-label { font-weight: 600; font-size: 0.9rem; min-width: 180px; }
	.config-value-inline { font-size: 0.9rem; flex: 1; }
	.config-editor-inline { width: 80px; font-family: "JetBrains Mono", monospace; font-size: 0.85rem; padding: 3px 6px; border: 1px solid var(--accent); border-radius: 3px; flex: 1; }
	.config-actions-inline { display: flex; gap: 4px; margin-left: auto; }
	.config-editor { width: 100%; font-family: "JetBrains Mono", monospace; font-size: 0.85rem; padding: 6px 8px; border: 1px solid var(--accent); border-radius: 3px; resize: vertical; margin-top: 4px; }
	.config-actions { display: flex; gap: 4px; margin-top: 4px; }

	.hal-coll-list { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
	.hal-coll-tag { font-size: 0.8rem; padding: 2px 8px; background: #e8f0e8; color: #2e6b2e; border-radius: 10px; }
	.hal-coll-label { color: #555; }

	.perimeter-card { background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 12px 16px; margin-bottom: 10px; max-width: 800px; }
	.perimeter-header { display: flex; align-items: center; gap: 10px; }
	.perimeter-code { font-size: 0.75rem; color: var(--muted); font-family: monospace; }
	.perimeter-count { font-size: 0.8rem; color: var(--accent); margin-left: auto; }
	.perimeter-desc { font-size: 0.85rem; color: var(--muted); margin: 4px 0 8px; }
	.perimeter-rules { display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0; }
	.tag { display: inline-flex; align-items: center; gap: 4px; font-size: 0.85rem; padding: 2px 8px; border-radius: 10px; background: #f0f0f0; }

	.remove { cursor: pointer; color: var(--danger); font-weight: bold; background: none; border: none; padding: 0; font-family: inherit; }

	.rule-add-form { margin-top: 8px; }
	.rule-add-form input[type="text"] { width: 250px; padding: 4px 8px; border: 1px solid var(--border); border-radius: 3px; font-size: 0.9rem; font-family: inherit; }
	.rule-results { border: 1px solid var(--border); border-radius: 4px; margin-top: 4px; max-height: 200px; overflow-y: auto; background: white; }
	.picker-item { display: block; width: 100%; padding: 6px 10px; font-size: 0.9rem; cursor: pointer; background: none; border: none; text-align: left; font-family: inherit; }
	.picker-item:hover { background: var(--accent-light); }
	.config-hint { font-size: 0.8rem; color: var(--muted); width: 100%; margin-top: 4px; }
	.config-hint a { color: var(--accent); }
	.none-text { font-size: 0.85rem; color: var(--muted); }
</style>
