<script lang="ts">
  // Volet d'édition d'un éditeur, réservé à la session admin : nom, type, pays, formes de nom et fusion.
  import { onMount, untrack } from "svelte";
  import { resolve } from "$app/paths";
  import { api, ApiError, errorMessage, publishers as publishersApi } from "#lib/api/index.js";
  import { autofocus } from "#lib/actions/focus.js";
  import { useDebouncedSearch } from "#lib/composables/useDebouncedSearch.svelte.js";
  import { confirmDialog, toast } from "#lib/dialogs.svelte.js";
  import Drawer from "#lib/components/Drawer.svelte";
  import IconButton from "#lib/components/IconButton.svelte";
  import Picker from "#lib/components/Picker.svelte";
  import type { components } from "#lib/api/schema.js";

  type Publisher = components["schemas"]["Publisher"];
  type PublisherListItem = components["schemas"]["PublisherListItem"];
  type PublisherNameForm = components["schemas"]["PublisherNameForm"];
  type BlockingSerial = components["schemas"]["BlockingSerialItem"];
  type MergeBlocked = components["schemas"]["PublisherMergeBlockedResponse"];
  type EnumOption = components["schemas"]["EnumOption"];
  type Country = components["schemas"]["CountryOut"];

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

  let publisher = $state<Publisher | null>(null);
  let nameForms = $state<PublisherNameForm[] | null>(null);
  let publisherTypes: EnumOption[] = $state([]);
  let countries: Country[] = $state([]);

  let editing = $state(false);
  let name = $state("");

  let mergeOpen = $state(false);
  // Paires de publications en série qui bloquent la dernière fusion demandée.
  let blocking = $state<{ detail: string; serials: BlockingSerial[] } | null>(null);
  const mergeSearch = useDebouncedSearch<PublisherListItem>({
    search: async (q, request) => {
      const data = await request<{ publishers: PublisherListItem[] }>(
        // Les éditeurs les plus fournis en publications en série d'abord.
        `/api/publishers?search=${encodeURIComponent(q)}&sort=serials_desc&per_page=10`,
      );
      return data.publishers;
    },
    transform: (results) => results.filter((p) => p.id !== id),
  });

  async function load() {
    const current = id;
    const [p, forms] = await Promise.all([
      api<Publisher>(`/api/publishers/${current}`),
      api<PublisherNameForm[]>(`/api/publishers/${current}/name-forms`),
    ]);
    if (current !== id) return;
    publisher = p;
    nameForms = forms;
  }

  // Chaque éditeur ouvert repart de son état chargé, sans édition ni fusion en cours.
  $effect(() => {
    void id;
    untrack(() => {
      publisher = null;
      nameForms = null;
      editing = false;
      blocking = null;
      closeMerge();
      void load();
    });
  });

  onMount(async () => {
    [publisherTypes, countries] = await Promise.all([
      api<EnumOption[]>("/api/publishers/types"),
      api<Country[]>("/api/countries"),
    ]);
  });

  async function update(body: Record<string, unknown>): Promise<boolean> {
    try {
      await publishersApi.update(id, body);
    } catch (e) {
      toast(errorMessage(e), "error");
      return false;
    }
    await load();
    onchange();
    return true;
  }

  function startEdit() {
    if (!publisher) return;
    name = publisher.name;
    editing = true;
  }

  async function saveName() {
    const value = name.trim();
    if (value && (await update({ name: value }))) editing = false;
  }

  /* ── Fusion ── */

  function openMerge() {
    blocking = null;
    mergeOpen = true;
    mergeSearch.clear();
  }

  function closeMerge() {
    mergeOpen = false;
    mergeSearch.clear();
  }

  async function absorb(source: PublisherListItem) {
    if (!publisher) return;
    const message = `Fusionner « ${source.name} » dans « ${publisher.name} » ? Ses publications en série et ses formes de nom passent à « ${publisher.name} ».`;
    if (!(await confirmDialog({ message, danger: true }))) return;
    try {
      await publishersApi.merge(id, source.id);
    } catch (e) {
      const body = e instanceof ApiError ? (e.detail as Partial<MergeBlocked>) : null;
      if (body?.blocking_serials?.length) {
        closeMerge();
        blocking = { detail: body.detail ?? "", serials: body.blocking_serials };
      } else {
        toast(errorMessage(e), "error");
      }
      return;
    }
    closeMerge();
    await load();
    onchange();
  }

  // Échap annule d'abord l'édition du nom en cours.
  function onescape() {
    if (editing) editing = false;
    else onclose();
  }
</script>

<Drawer {onclose} {onescape}>
  {#snippet head()}
    {#if publisher}
      <div class="drawer-head-row">
        {#if editing}
          <form class="drawer-edit" onsubmit={(e) => { e.preventDefault(); saveName(); }}>
            <input bind:value={name} aria-label="Nom" use:autofocus={{ select: true }} />
            <button type="submit" class="btn btn-sm btn-primary">OK</button>
            <button type="button" class="btn btn-sm" onclick={() => (editing = false)}>Annuler</button>
          </form>
        {:else}
          <a class="drawer-name-link" href={resolve(`publishers/${publisher.id}`)} target="_blank" rel="noopener" title="Voir la fiche publique">
            {publisher.name}
          </a>
          <div class="drawer-head-actions">
            <IconButton icon="edit" label="Modifier le nom" onclick={startEdit} />
          </div>
        {/if}
      </div>
    {/if}
  {/snippet}

  {#if !publisher}
    <p class="muted">Chargement…</p>
  {:else}
    <div class="drawer-meta">
      <span>{publisher.serial_count.toLocaleString("fr-FR")} publications en série</span>
      <span>{publisher.publication_count.toLocaleString("fr-FR")} publications</span>
    </div>

    <dl class="drawer-section drawer-fields">
      <dt><label for="publisher-type">Type</label></dt>
      <dd>
        <select
          id="publisher-type"
          class="select"
          value={publisher.publisher_type}
          onchange={(e) => update({ publisher_type: e.currentTarget.value })}
        >
          {#each publisherTypes as opt (opt.value)}
            <option value={opt.value}>{opt.label_fr}</option>
          {/each}
        </select>
      </dd>
      <dt><label for="publisher-country">Pays</label></dt>
      <dd>
        <select
          id="publisher-country"
          class="select"
          value={(publisher.country ?? "").toUpperCase()}
          onchange={(e) => update({ country: e.currentTarget.value || null })}
        >
          <option value="">—</option>
          {#each countries as c (c.code)}
            <option value={c.code.toUpperCase()}>{c.name}</option>
          {/each}
        </select>
      </dd>
    </dl>

    {#if publisher.doi_prefixes.length}
      <section class="drawer-section">
        <h3>Préfixes DOI</h3>
        <div class="tag-list">
          {#each publisher.doi_prefixes as p (p.prefix)}
            <span class="tag id-badge" title="RA : {p.ra}{p.crossref_member_id ? ` / membre Crossref ${p.crossref_member_id}` : ''}">{p.prefix}</span>
          {/each}
        </div>
      </section>
    {/if}

    <section class="drawer-section">
      <h3>Fusion</h3>
      {#if blocking}
        <div class="blocking" role="alert">
          <p><strong>Fusion impossible.</strong> {blocking.detail}</p>
          <p class="muted">Fusionner d'abord ces paires de publications en série, puis relancer la fusion des éditeurs.</p>
          <ul>
            {#each blocking.serials as bs (`${bs.target_serial_id}-${bs.source_serial_id}`)}
              <li>
                <a href={resolve(`journals/${bs.target_serial_id}`)} target="_blank" rel="noopener">{bs.target_title}</a>
                et
                <a href={resolve(`journals/${bs.source_serial_id}`)} target="_blank" rel="noopener">{bs.source_title}</a>
                <span class="muted">: {bs.reason}</span>
              </li>
            {/each}
          </ul>
        </div>
      {/if}
      {#if mergeOpen}
        <Picker
          floating
          minLength={2}
          placeholder="Éditeur à absorber"
          search={mergeSearch.query}
          onsearch={mergeSearch.setQuery}
          loading={mergeSearch.loading}
          results={mergeSearch.results}
          onpick={absorb}
          onclose={closeMerge}
        >
          {#snippet item(r)}
            {r.name}
            <span class="muted">({r.serial_count} publications en série, {r.publication_count} publications)</span>
          {/snippet}
        </Picker>
      {:else}
        <button class="btn btn-sm btn-dashed" onclick={openMerge}>Fusionner…</button>
      {/if}
    </section>

    <section class="drawer-section">
      <h3>Formes de nom</h3>
      {#if nameForms === null}
        <span class="muted">Chargement…</span>
      {:else if nameForms.length === 0}
        <span class="muted">Aucune</span>
      {:else}
        <table class="data-table forms-table">
          <thead>
            <tr><th>Forme</th><th class="num">Enregistrements sources</th></tr>
          </thead>
          <tbody>
            {#each nameForms as nf (nf.form)}
              <tr>
                <td>{nf.form}</td>
                <td class="num" class:zero={nf.source_record_count === 0}>{nf.source_record_count.toLocaleString("fr-FR")}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>
  {/if}
</Drawer>

<style>
  .muted {
    color: var(--muted);
  }
  .forms-table {
    width: 100%;
  }
  .forms-table td.zero {
    color: var(--text-faint);
  }
  .blocking {
    background: var(--warning-light);
    border: 1px solid var(--warning);
    border-radius: var(--radius);
    padding: 8px 12px;
    margin-bottom: 10px;
    font-size: var(--fs-sm);
  }
  .blocking p {
    margin: 0 0 6px;
  }
  .blocking ul {
    margin: 0;
    padding-left: 18px;
  }
</style>
