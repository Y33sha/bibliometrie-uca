<script lang="ts">
  import Breadcrumb from "#lib/components/Breadcrumb.svelte";
  import { pageTitle } from "#lib/institution.svelte.js";
  import { page } from "$app/state";
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
  import SectionLabel from "./SectionLabel.svelte";

  const publicationId = $derived(page.params.id);
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

  // Résumé replié à quelques lignes ; « Lire la suite » n'apparaît que s'il dépasse.
  let abstractEl = $state<HTMLDivElement | undefined>();
  let abstractOpen = $state(false);
  let abstractOverflows = $state(false);
  $effect(() => {
    void pub?.abstract;
    abstractOpen = false;
  });
  $effect(() => {
    if (!abstractEl || abstractOpen) return;
    abstractOverflows = abstractEl.scrollHeight > abstractEl.clientHeight + 2;
  });

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

</script>

<svelte:head>
  <title>{pageTitle(titleText(pub?.title).slice(0, 80) || "Publication")}</title>
</svelte:head>

<Breadcrumb trail={[{ label: "Publications", path: "publications" }]} current={titleText(pub?.title)} />

{#if error}
  <div class="no-results">Publication introuvable</div>
{:else if !pub}
  <div class="loading">Chargement…</div>
{:else}
  <div class="detail-layout">
    <div class="detail-main">
      <PublicationHeader {pub} relations={data!.relations} />

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

        {#if pub.abstract}
          <div class="detail-section">
            <SectionLabel icon="document" text="Résumé" />
            <div class="abstract-text" class:clamped={!abstractOpen} class:overflows={abstractOverflows} bind:this={abstractEl}>
              <PublicationAbstract resume={pub.abstract} />
            </div>
            {#if abstractOverflows || abstractOpen}
              <button type="button" class="read-more" onclick={() => (abstractOpen = !abstractOpen)}>
                {abstractOpen ? "Réduire" : "Lire la suite"}
              </button>
            {/if}
          </div>
        {/if}

        <SubjectsBlock subjects={data!.subjects} keywords={data!.keywords} />
      </div>
    </div>

    <PublicationSidebar
      {pub}
      accessUrl={data!.access_url}
      access={data!.access}
      referencedBy={data!.referenced_by}
      externalIds={data!.external_identifiers}
    />
  </div>
{/if}

<style>
  /* Deux colonnes dès le haut de la page : en-tête et contenu à gauche, accès et sources à droite. Replie en une colonne (encadré sous le contenu) en dessous de 860px. */
  .detail-layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 320px;
    gap: 48px;
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
  .abstract-text {
    /* Environ 120 caractères par ligne : en Source Sans 3, un caractère moyen est plus étroit que le « 0 » qui définit `ch`. */
    max-width: 96ch;
    font-size: 1.02rem;
    line-height: 1.65;
    color: var(--text);
    margin: 0;
  }
  /* Six lignes environ ; fondu sur la dernière quand le résumé dépasse. */
  .abstract-text.clamped {
    max-height: calc(1.65em * 6);
    overflow: hidden;
  }
  .abstract-text.clamped.overflows {
    mask-image: linear-gradient(to bottom, black 70%, transparent);
  }

  /* Le résumé garde les paragraphes que la source y dépose : conteneur en `div`, un `p` ne
     pouvant pas en contenir un autre. */
  .abstract-text :global(p) {
    margin: 0 0 0.75rem;
  }

  .abstract-text :global(p:last-child) {
    margin-bottom: 0;
  }
  .read-more {
    margin-top: 6px;
    padding: 4px 0;
    border: none;
    background: none;
    font: inherit;
    font-weight: 600;
    color: var(--accent);
    cursor: pointer;
  }
  .read-more:hover {
    text-decoration: underline;
  }
</style>
