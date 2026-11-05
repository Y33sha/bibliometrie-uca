<script lang="ts">
  // Volet d'édition d'une publication en série, réservé à la session admin : titre, type, modèle OA, caractère académique et fusion.
  import { onMount, untrack } from "svelte";
  import { resolve } from "$app/paths";
  import { api, errorMessage, serials as serialsApi } from "#lib/api/index.js";
  import { autofocus } from "#lib/actions/focus.js";
  import { useDebouncedSearch } from "#lib/composables/useDebouncedSearch.svelte.js";
  import { confirmDialog, toast } from "#lib/dialogs.svelte.js";
  import { issnLabel } from "#lib/labels.js";
  import Drawer from "#lib/components/Drawer.svelte";
  import IconButton from "#lib/components/IconButton.svelte";
  import Picker from "#lib/components/Picker.svelte";
  import IssnBadge from "./IssnBadge.svelte";
  import { mergeSerial } from "./mergeSerial";
  import type { components } from "#lib/api/schema.js";
  import { formatCount } from "#lib/plural.js";

  type SerialDetail = components["schemas"]["SerialDetailResponse"];
  type Serial = components["schemas"]["SerialListItem"];
  type SerialListResponse = components["schemas"]["SerialListResponse"];
  type EnumOption = components["schemas"]["EnumOption"];

  let {
    id,
    onclose,
    onchange,
  }: {
    id: number;
    onclose: () => void;
    /** Appelé après chaque écriture, pour que la page hôte recharge ses données. */
    onchange: () => void;
  } = $props();

  let serial = $state<SerialDetail | null>(null);
  let serialTypes: EnumOption[] = $state([]);
  let oaModels: EnumOption[] = $state([]);

  let editing = $state(false);
  let title = $state("");

  let mergeOpen = $state(false);
  const mergeSearch = useDebouncedSearch<Serial>({
    search: async (q, request) => {
      const data = await request<SerialListResponse>(
        // Les publications en série les plus fournies en publications d'abord.
        `/api/serials?search=${encodeURIComponent(q)}&sort=publications_desc&per_page=10`,
      );
      return data.serials;
    },
    transform: (results) => results.filter((j) => j.id !== id),
  });

  async function load() {
    const current = id;
    const detail = await api<SerialDetail>(`/api/serials/${current}`);
    if (current === id) serial = detail;
  }

  // Chaque publication en série ouverte repart de son état chargé, sans édition ni fusion en cours.
  $effect(() => {
    void id;
    untrack(() => {
      serial = null;
      editing = false;
      closeMerge();
      void load();
    });
  });

  onMount(async () => {
    [serialTypes, oaModels] = await Promise.all([
      api<EnumOption[]>("/api/serials/types"),
      api<EnumOption[]>("/api/serials/oa-models"),
    ]);
  });

  async function update(body: Record<string, unknown>): Promise<boolean> {
    try {
      await serialsApi.update(id, body);
    } catch (e) {
      toast(errorMessage(e), "error");
      return false;
    }
    await load();
    onchange();
    return true;
  }

  function startEdit() {
    if (!serial) return;
    title = serial.title;
    editing = true;
  }

  async function saveTitle() {
    const value = title.trim();
    if (value && (await update({ title: value }))) editing = false;
  }

  // Un changement de type requalifie les publications : leur nombre est annoncé et le changement attend une confirmation.
  async function setType(select: HTMLSelectElement) {
    if (!serial) return;
    const previous = serial.serial_type ?? "";
    const next = select.value;
    try {
      const impact = await serialsApi.typeChangeImpact(id, next);
      if (impact.count > 0) {
        const message = `Ce changement entraînera un recalcul de la métadonnée « type de document » sur ${formatCount(impact.count, "publication")}. Continuer ?`;
        if (!(await confirmDialog({ message }))) {
          select.value = previous;
          return;
        }
      }
    } catch (e) {
      toast("Erreur lors du calcul d'impact : " + errorMessage(e), "error");
      select.value = previous;
      return;
    }
    if (!(await update({ serial_type: next }))) select.value = previous;
  }

  /* ── Fusion ── */

  function openMerge() {
    mergeOpen = true;
    mergeSearch.clear();
  }

  function closeMerge() {
    mergeOpen = false;
    mergeSearch.clear();
  }

  async function absorb(source: Serial) {
    if (!serial) return;
    const message = `Fusionner « ${source.title} » dans « ${serial.title} » ? Ses publications passent à « ${serial.title} ».`;
    if (!(await confirmDialog({ message, danger: true }))) return;
    if (!(await mergeSerial(serial, source.id))) return;
    closeMerge();
    await load();
    onchange();
  }

  // Échap annule d'abord l'édition du titre en cours.
  function onescape() {
    if (editing) editing = false;
    else onclose();
  }
</script>

<Drawer {onclose} {onescape}>
  {#snippet head()}
    {#if serial}
      <div class="drawer-head-row">
        {#if editing}
          <form class="drawer-edit" onsubmit={(e) => { e.preventDefault(); saveTitle(); }}>
            <input bind:value={title} aria-label="Titre" use:autofocus={{ select: true }} />
            <button type="submit" class="btn btn-sm btn-primary">OK</button>
            <button type="button" class="btn btn-sm" onclick={() => (editing = false)}>Annuler</button>
          </form>
        {:else}
          <a class="drawer-name-link" href={resolve(`journals/${serial.id}`)} target="_blank" rel="noopener" title="Voir la fiche publique">
            {serial.title}
          </a>
          <div class="drawer-head-actions">
            <IconButton icon="edit" label="Modifier le titre" onclick={startEdit} />
          </div>
        {/if}
      </div>
    {/if}
  {/snippet}

  {#if !serial}
    <p class="muted">Chargement…</p>
  {:else}
    <div class="drawer-meta">
      <span>{serial.publication_count.toLocaleString("fr-FR")} publications</span>
      {#if serial.is_in_doaj}<span class="tag tag-success badge-doaj">DOAJ</span>{/if}
    </div>

    <dl class="drawer-section drawer-fields">
      {#if serial.publisher_name}
        <dt>Éditeur</dt>
        <dd>
          {#if serial.publisher_id}
            <a href={resolve(`publishers/${serial.publisher_id}`)} target="_blank" rel="noopener">{serial.publisher_name}</a>
          {:else}
            {serial.publisher_name}
          {/if}
        </dd>
      {/if}
      <dt><label for="serial-type">Type</label></dt>
      <dd>
        <select id="serial-type" class="select" value={serial.serial_type ?? ""} onchange={(e) => setType(e.currentTarget)}>
          {#each serialTypes as opt (opt.value)}
            <option value={opt.value}>{opt.label_fr}</option>
          {/each}
        </select>
      </dd>
      <dt><label for="serial-oa-model">Modèle OA</label></dt>
      <dd>
        <select
          id="serial-oa-model"
          class="select"
          value={serial.oa_model ?? ""}
          onchange={(e) => update({ oa_model: e.currentTarget.value || null })}
        >
          <option value="">—</option>
          {#each oaModels as opt (opt.value)}
            <option value={opt.value}>{opt.label_fr}</option>
          {/each}
        </select>
      </dd>
      <dt><label for="serial-academic">Académique</label></dt>
      <dd>
        <input
          id="serial-academic"
          type="checkbox"
          checked={serial.is_academic ?? true}
          onchange={(e) => update({ is_academic: e.currentTarget.checked })}
        />
      </dd>
    </dl>

    {#if serial.issn_details.length}
      <section class="drawer-section">
        <h3>ISSN</h3>
        <dl class="drawer-fields">
          {#each serial.issn_details.filter((i) => i.status === "active" || i.linking) as issn (issn.issn)}
            <dt>{issnLabel(issn)}</dt>
            <dd><IssnBadge issn={issn.issn} /></dd>
          {/each}
        </dl>
      </section>
    {/if}

    <section class="drawer-section">
      <h3>Fusion</h3>
      {#if mergeOpen}
        <Picker
          floating
          minLength={2}
          placeholder="Publication en série à absorber"
          search={mergeSearch.query}
          onsearch={mergeSearch.setQuery}
          loading={mergeSearch.loading}
          results={mergeSearch.results}
          onpick={absorb}
          onclose={closeMerge}
        >
          {#snippet item(r)}
            {r.title}
            {#if r.publisher_name}<span class="muted"> — {r.publisher_name}</span>{/if}
            <span class="muted"> ({r.publication_count} publications)</span>
          {/snippet}
        </Picker>
      {:else}
        <button class="btn btn-sm btn-dashed" onclick={openMerge}>Fusionner…</button>
      {/if}
    </section>
  {/if}
</Drawer>

<style>
  .muted {
    color: var(--muted);
  }
</style>
