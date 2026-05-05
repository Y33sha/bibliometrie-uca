<script lang="ts">
  import { page } from "$app/stores";
  import { onMount } from "svelte";
  import { api, auth } from "$lib/api";
  import { sanitizeTitle } from "$lib/utils";
  import type { PubResponse, SourceAuthorship, SourceRow } from "./types";
  import PublicationHeader from "./PublicationHeader.svelte";
  import ThesisBlock from "./ThesisBlock.svelte";
  import TruthAuthorshipsTable from "./TruthAuthorshipsTable.svelte";
  import SourceComparison from "./SourceComparison.svelte";
  import SubjectsBlock from "./SubjectsBlock.svelte";

  const pubId = $derived($page.params.id);
  let canGoBack = $state(false);

  let data = $state<PubResponse | null>(null);
  let error = $state(false);
  let isAdmin = $state(false);

  const pub = $derived(data?.publication);
  const hasTruthTable = $derived((data?.authorships.length ?? 0) > 0);
  const thesesAuth = $derived(data?.theses_authorships ?? []);
  const thesisMeta = $derived(data?.thesis_meta);
  const thesisAuthorStructures = $derived(
    data?.authorships.find((a) => a.in_perimeter)?.structure_ids ?? [],
  );

  const halSource = $derived(data?.sources.find((s) => s.source === "hal"));
  const oaSource = $derived(data?.sources.find((s) => s.source === "openalex"));
  const scanrSource = $derived(data?.sources.find((s) => s.source === "scanr"));
  const wosSource = $derived(data?.sources.find((s) => s.source === "wos"));
  const thesesSource = $derived(data?.sources.find((s) => s.source === "theses"));

  const sourceRows = $derived.by(() => {
    if (!data) return [];
    const halMap = new Map<number, SourceAuthorship>();
    const oaMap = new Map<number, SourceAuthorship>();
    const wosMap = new Map<number, SourceAuthorship>();
    const scanrMap = new Map<number, SourceAuthorship>();
    for (const a of data.hal_authorships) if (a.author_position != null) halMap.set(a.author_position, a);
    for (const a of data.openalex_authorships) if (a.author_position != null) oaMap.set(a.author_position, a);
    for (const a of data.wos_authorships) if (a.author_position != null) wosMap.set(a.author_position, a);
    for (const a of data.scanr_authorships) if (a.author_position != null) scanrMap.set(a.author_position, a);

    const allPos = new Set([
      ...halMap.keys(),
      ...oaMap.keys(),
      ...wosMap.keys(),
      ...scanrMap.keys(),
    ]);
    const rows: SourceRow[] = [];
    for (const pos of [...allPos].sort((a, b) => a - b)) {
      const hal = halMap.get(pos) ?? null;
      const oa = oaMap.get(pos) ?? null;
      const wos = wosMap.get(pos) ?? null;
      const scanr = scanrMap.get(pos) ?? null;
      const entries = [hal, oa, wos, scanr].filter((x): x is SourceAuthorship => x !== null);
      const activeEntries = entries.filter((e) => !e.excluded);

      let conflict = false;
      // Conflit : auteur UCA dans une source mais absent d'une autre source présente
      const ucaEntries = activeEntries.filter((e) => e.in_perimeter);
      if (ucaEntries.length > 0) {
        if (
          (hal === null || hal.excluded) &&
          data.hal_authorships.some((a) => !a.excluded)
        )
          conflict = true;
        if (
          (oa === null || oa.excluded) &&
          data.openalex_authorships.some((a) => !a.excluded)
        )
          conflict = true;
        if (
          (wos === null || wos.excluded) &&
          data.wos_authorships.some((a) => !a.excluded)
        )
          conflict = true;
        if (
          (scanr === null || scanr.excluded) &&
          data.scanr_authorships.some((a) => !a.excluded)
        )
          conflict = true;
      }
      // Conflit : deux personnes résolues différentes
      const personIds = activeEntries
        .filter((e) => e.person_id !== null)
        .map((e) => e.person_id!);
      if (new Set(personIds).size > 1) conflict = true;
      // Conflit : auteur UCA résolu aligné avec auteur non résolu
      if (
        ucaEntries.some((e) => e.person_id !== null) &&
        activeEntries.some((e) => e.person_id === null)
      )
        conflict = true;

      rows.push({ position: pos, hal, oa, wos, scanr, conflict });
    }
    return rows;
  });

  const hasSourceConflict = $derived(sourceRows.some((r) => r.conflict));

  async function loadData() {
    data = await api<PubResponse>(`/api/publications/${pubId}`);
  }

  onMount(async () => {
    canGoBack =
      (window as any).navigation?.canGoBack ??
      document.referrer.startsWith(window.location.origin);
    auth
      .check()
      .then((d) => {
        isAdmin = !!d.authenticated;
      })
      .catch(() => {});
    try {
      await loadData();
    } catch {
      error = true;
    }
  });
</script>

<svelte:head>
  <title>{pub?.title ? pub.title.slice(0, 80) : "Publication"} — Bibliométrie UCA</title>
</svelte:head>

{#if canGoBack}
  <!-- svelte-ignore a11y_invalid_attribute -->
  <a
    href="#"
    class="back-link"
    onclick={(e) => {
      e.preventDefault();
      history.back();
    }}>&larr; Retour</a
  >
{/if}

{#if error}
  <div class="pub-header"><div class="no-results">Publication introuvable</div></div>
{:else if !pub}
  <div class="pub-header"><div class="loading">Chargement...</div></div>
{:else}
  <PublicationHeader
    {pub}
    sources={data!.sources}
  />

  {#if thesesAuth.length || thesisMeta}
    <ThesisBlock
      {thesesAuth}
      {thesisMeta}
      {thesisAuthorStructures}
      structures={data!.structures}
    />
  {/if}

  <SubjectsBlock subjects={data!.subjects} />

  {#if pub.abstract}
    <div class="section abstract-section">
      <h2 class="section-title">Abstract</h2>
      <p class="abstract-text">{@html sanitizeTitle(pub.abstract)}</p>
    </div>
  {/if}

  {#if hasTruthTable && pub.doc_type !== "thesis" && pub.doc_type !== "ongoing_thesis"}
    <TruthAuthorshipsTable
      authorships={data!.authorships}
      structures={data!.structures}
    />
  {/if}

  <SourceComparison
    data={data!}
    {sourceRows}
    {hasSourceConflict}
    {halSource}
    {oaSource}
    {wosSource}
    {scanrSource}
    structures={data!.structures}
    {isAdmin}
    onChange={loadData}
  />
{/if}

<style>
  .section {
    margin-bottom: 16px;
  }
  .section-title {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0 0 8px;
  }
  .pub-header {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 20px 24px;
    margin-bottom: 16px;
  }
  .abstract-section {
    background: white;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px 20px;
  }
  .abstract-text {
    font-size: 0.95rem;
    line-height: 1.6;
    color: var(--fg);
    margin: 0;
  }
</style>
