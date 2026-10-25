<script lang="ts">
  import { pageTitle } from "#lib/institution.svelte.js";
  import { page } from "$app/state";
  import { onMount } from "svelte";
  import { apiDetail } from "#lib/api/index.js";
  import { titleText } from "#lib/utils.js";
  import PublicationAbstract from "#lib/components/PublicationAbstract.svelte";
  import type { PubResponse } from "./types";
  import PublicationHeader from "./PublicationHeader.svelte";
  import PublicationSidebar from "./PublicationSidebar.svelte";
  import ThesisBlock from "./ThesisBlock.svelte";
  import StructuresBlock from "./StructuresBlock.svelte";
  import PersonsBlock from "./PersonsBlock.svelte";
  import SubjectsBlock from "./SubjectsBlock.svelte";

  const publicationId = $derived(page.params.id);
  let canGoBack = $state(false);

  let data = $state<PubResponse | null>(null);
  let error = $state(false);

  const pub = $derived(data?.publication);
  const hasTruthTable = $derived((data?.contributions.length ?? 0) > 0);
  // Structures liées : union des structures des contributions, ordre d'apparition.
  const structureIds = $derived.by(() => {
    const seen = new Set<number>();
    const out: number[] = [];
    for (const a of data?.contributions ?? [])
      for (const sid of a.structure_ids ?? [])
        if (!seen.has(sid)) {
          seen.add(sid);
          out.push(sid);
        }
    return out;
  });
  const thesesAuth = $derived(data?.theses_contributions ?? []);
  const thesisMeta = $derived(data?.thesis_meta);
  const thesisAuthorStructures = $derived(
    data?.contributions.find((a) => a.in_perimeter)?.structure_ids ?? [],
  );

  const thesesSource = $derived(data?.sources.find((s) => s.source === "theses"));

  async function loadData(id: string) {
    data = await apiDetail<PubResponse>(`/api/publications/${id}`);
  }

  // Charge la publication de l'identifiant de la page.
  $effect(() => {
    const id = publicationId;
    if (!id) return;
    data = null;
    error = false;
    loadData(id).catch(() => {
      error = true;
    });
  });

  onMount(() => {
    canGoBack =
      (window as any).navigation?.canGoBack ??
      document.referrer.startsWith(window.location.origin);
  });
</script>

<svelte:head>
  <title>{pageTitle(titleText(pub?.title).slice(0, 80) || "Publication")}</title>
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
  <div class="publication-header"><div class="no-results">Publication introuvable</div></div>
{:else if !pub}
  <div class="publication-header"><div class="loading">Chargement…</div></div>
{:else}
  <PublicationHeader {pub} relations={data!.relations} />

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
          <PersonsBlock contributions={data!.contributions} />
        {/if}

        <StructuresBlock {structureIds} structures={data!.structures} />

        <SubjectsBlock subjects={data!.subjects} keywords={data!.keywords} />

        {#if pub.abstract}
          <div class="detail-section">
            <div class="detail-label">Résumé</div>
            <div class="abstract-text"><PublicationAbstract resume={pub.abstract} /></div>
          </div>
        {/if}
      </div>
    </div>

    <PublicationSidebar {pub} sources={data!.sources} externalIds={data!.external_identifiers} />
  </div>
{/if}

<style>
  .publication-header {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 20px 24px;
    margin-bottom: 16px;
  }
  /* Deux colonnes : contenu à gauche, accès et identifiants à droite. Replie en une colonne (sidebar sous le contenu) en dessous de 860px. */
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
  /* Panneau unique regroupant les sections plates (structures, personnes, relations, sujets, résumé), séparées par des filets fins. */
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

  /* Le résumé garde les paragraphes que la source y dépose : conteneur en `div`, un `p` ne
     pouvant pas en contenir un autre. Le dernier ne pousse pas la bordure de la section. */
  .abstract-text :global(p) {
    margin: 0 0 0.75rem;
  }

  .abstract-text :global(p:last-child) {
    margin-bottom: 0;
  }
</style>
