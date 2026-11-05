<script lang="ts">
  import EntityBreadcrumb from "#lib/components/EntityBreadcrumb.svelte";
  import EntityStatus from "#lib/components/EntityStatus.svelte";
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { page } from "$app/state";
  import { apiDetail } from "#lib/api/index.js";
  import { titleText } from "#lib/utils.js";
  import ClampedBlock from "#lib/components/ClampedBlock.svelte";
  import PublicationAbstract from "#lib/components/PublicationAbstract.svelte";
  import type { PubResponse } from "./types";
  import PublicationHeader from "./PublicationHeader.svelte";
  import PublicationSidebar from "./PublicationSidebar.svelte";
  import ThesisBlock from "./ThesisBlock.svelte";
  import StructuresBlock from "./StructuresBlock.svelte";
  import PersonsBlock from "./PersonsBlock.svelte";
  import SubjectsBlock from "./SubjectsBlock.svelte";
  import SectionLabel from "./SectionLabel.svelte";
  import PublicationDrawer from "#lib/components/publications/PublicationDrawer.svelte";
  import { useDrawerParam } from "#lib/composables/useDrawerParam.svelte.js";

  const publicationId = $derived(page.params.id);
  // Volet de la publication : ouvert tant que `?publication=<id>` figure dans l'URL.
  const drawer = useDrawerParam("publication");
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

  // Après une fusion dans le volet de la publication de la page, la page passe à la publication conservée.
  function openKept(keptId: number) {
    if (drawer.id === Number(publicationId))
      void goto(`${resolve(`publications/${keptId}`)}?publication=${keptId}`);
    else drawer.open(keptId);
  }

  function merged(keptId: number) {
    if (String(keptId) === publicationId)
      loadData(publicationId).catch(() => {
        error = true;
      });
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

<EntityBreadcrumb
  section={{ label: "Publications", path: "publications" }}
  name={titleText(pub?.title)}
  title={titleText(pub?.title).slice(0, 80)}
  fallback="Publication"
/>

{#if error || !pub}
  <EntityStatus {error} notFound="Publication introuvable" />
{:else}
  <div class="detail-layout">
    <div class="detail-main">
      <PublicationHeader
        {pub}
        relations={data!.relations}
        onopenDrawer={() => drawer.open(pub.id)}
      />

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
            <!-- Six lignes environ. -->
            <div class="abstract-text">
              {#key pub.id}
                <ClampedBlock maxHeight="calc(1.65em * 6)" moreLabel="Lire la suite">
                  <PublicationAbstract resume={pub.abstract} />
                </ClampedBlock>
              {/key}
            </div>
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

{#if drawer.id !== null}
  <PublicationDrawer
    publicationId={drawer.id}
    onclose={() => drawer.open(null)}
    onopen={openKept}
    onchange={merged}
  />
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
    font-size: var(--fs-base);
    line-height: 1.65;
    color: var(--text);
    margin: 0;
  }
  /* Le résumé garde les paragraphes que la source y dépose : conteneur en `div`, un `p` ne
     pouvant pas en contenir un autre. */
  .abstract-text :global(p) {
    margin: 0 0 0.75rem;
  }

  .abstract-text :global(p:last-child) {
    margin-bottom: 0;
  }
</style>
