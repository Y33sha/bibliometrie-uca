<script lang="ts">
  import { page } from "$app/stores";
  import { onMount } from "svelte";
  import { api, auth } from "$lib/api";
  import { sanitizeTitle } from "$lib/utils";
  import { PARENT_RELATION_TYPES } from "$lib/labels";
  import type { PubResponse, SourceAuthorship, SourceRow } from "./types";
  import PublicationHeader from "./PublicationHeader.svelte";
  import PublicationSidebar from "./PublicationSidebar.svelte";
  import ThesisBlock from "./ThesisBlock.svelte";
  import StructuresBlock from "./StructuresBlock.svelte";
  import PersonsBlock from "./PersonsBlock.svelte";
  import SourceComparison from "./SourceComparison.svelte";
  import SubjectsBlock from "./SubjectsBlock.svelte";
  import RelatedPublications from "./RelatedPublications.svelte";

  const pubId = $derived($page.params.id);
  let canGoBack = $state(false);
  // Comparaison des sources réservée à l'admin connecté.
  let isAdmin = $state(false);

  let data = $state<PubResponse | null>(null);
  let error = $state(false);

  const pub = $derived(data?.publication);
  const hasTruthTable = $derived((data?.authorships.length ?? 0) > 0);
  // Structures liées : union des structures des signatures consolidées, ordre d'apparition.
  const structureIds = $derived.by(() => {
    const seen = new Set<number>();
    const out: number[] = [];
    for (const a of data?.authorships ?? [])
      for (const sid of a.structure_ids ?? [])
        if (!seen.has(sid)) {
          seen.add(sid);
          out.push(sid);
        }
    return out;
  });
  const thesesAuth = $derived(data?.theses_authorships ?? []);
  const thesisMeta = $derived(data?.thesis_meta);
  const thesisAuthorStructures = $derived(
    data?.authorships.find((a) => a.in_perimeter)?.structure_ids ?? [],
  );

  // Relations « vers le parent » (la publi est une pièce dépendante) mises en avant dans le header ;
  // les autres (dépendantes de la publi, latérales) restent dans le bloc central.
  const parentRelations = $derived(
    (data?.relations ?? []).filter((r) => PARENT_RELATION_TYPES.has(r.relation_type)),
  );
  const otherRelations = $derived(
    (data?.relations ?? []).filter((r) => !PARENT_RELATION_TYPES.has(r.relation_type)),
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

      let conflict = false;
      // Conflit : auteur UCA dans une source mais absent d'une autre source présente
      const ucaEntries = entries.filter((e) => e.in_perimeter);
      if (ucaEntries.length > 0) {
        if (hal === null && data.hal_authorships.length > 0) conflict = true;
        if (oa === null && data.openalex_authorships.length > 0) conflict = true;
        if (wos === null && data.wos_authorships.length > 0) conflict = true;
        if (scanr === null && data.scanr_authorships.length > 0) conflict = true;
      }
      // Conflit : deux personnes résolues différentes
      const personIds = entries
        .filter((e) => e.person_id !== null)
        .map((e) => e.person_id!);
      if (new Set(personIds).size > 1) conflict = true;
      // Conflit : auteur UCA résolu aligné avec auteur non résolu
      if (
        ucaEntries.some((e) => e.person_id !== null) &&
        entries.some((e) => e.person_id === null)
      )
        conflict = true;

      rows.push({ position: pos, hal, oa, wos, scanr, conflict });
    }
    return rows;
  });

  const hasSourceConflict = $derived(sourceRows.some((r) => r.conflict));

  async function loadData(id: string) {
    data = await api<PubResponse>(`/api/publications/${id}`);
  }

  // Recharge à chaque changement d'`id`. La navigation d'une publication à une autre réutilise la
  // même route `[id]`, donc le composant n'est pas remonté : `onMount` ne suffit pas, il faut un
  // effet réactif sur `pubId` (sinon l'URL change mais le contenu reste).
  $effect(() => {
    const id = pubId;
    if (!id) return;
    data = null;
    error = false;
    loadData(id).catch(() => {
      error = true;
    });
  });

  onMount(async () => {
    canGoBack =
      (window as any).navigation?.canGoBack ??
      document.referrer.startsWith(window.location.origin);
    try {
      isAdmin = (await auth.check()).authenticated;
    } catch {
      isAdmin = false;
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
  <div class="pub-header"><div class="loading">Chargement…</div></div>
{:else}
  <PublicationHeader {pub} {parentRelations} />

  <div class="detail-layout">
    <div class="detail-main">
      {#if thesesAuth.length || thesisMeta}
        <ThesisBlock
          {thesesAuth}
          {thesisMeta}
          {thesisAuthorStructures}
          structures={data!.structures}
        />
      {/if}

      <div class="detail-body">
        {#if hasTruthTable && pub.doc_type !== "thesis" && pub.doc_type !== "ongoing_thesis"}
          <PersonsBlock authorships={data!.authorships} />
        {/if}

        <StructuresBlock {structureIds} structures={data!.structures} />

        <RelatedPublications relations={otherRelations} />

        <SubjectsBlock subjects={data!.subjects} />

        {#if pub.abstract}
          <div class="detail-section">
            <div class="detail-label">Résumé</div>
            <p class="abstract-text">{@html sanitizeTitle(pub.abstract)}</p>
          </div>
        {/if}
      </div>
    </div>

    <PublicationSidebar {pub} sources={data!.sources} externalIds={data!.external_identifiers} />
  </div>

  {#if isAdmin}
    <SourceComparison
      data={data!}
      {sourceRows}
      {hasSourceConflict}
      {halSource}
      {oaSource}
      {wosSource}
      {scanrSource}
      structures={data!.structures}
    />
  {/if}
{/if}

<style>
  .pub-header {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 20px 24px;
    margin-bottom: 16px;
  }
  /* Deux colonnes : contenu à gauche, accès & identité à droite. Replie en une colonne (sidebar
     sous le contenu) en dessous de 860px. */
  .detail-layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 300px;
    gap: 16px;
    align-items: start;
  }
  .detail-main {
    min-width: 0;
  }
  @media (max-width: 860px) {
    .detail-layout {
      grid-template-columns: 1fr;
    }
  }
  /* Panneau unique regroupant les sections plates (structures, personnes, relations, sujets,
     résumé), séparées par des filets fins plutôt qu'un encadré par section. */
  .detail-body {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 24px;
    margin-bottom: 16px;
  }
  .detail-body:empty {
    display: none;
  }
  .abstract-text {
    font-size: 0.95rem;
    line-height: 1.6;
    color: var(--text);
    margin: 0;
  }
</style>
