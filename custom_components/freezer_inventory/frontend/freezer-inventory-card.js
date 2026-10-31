/*
 * Freezer Inventory card — Fase 2: elenco in sola lettura, per verificare
 * installazione, websocket e aggiornamento live. La card completa (+/-, prelievo,
 * aggiunta, modifica) arriva nella Fase 3.
 *
 *   type: custom:freezer-inventory-card
 *   title: Freezer piano terra   # facoltativo
 */
const CATEGORY_ICON = { carne: "🥩", verdura: "🥦", frutta: "🍓", altro: "📦" };

class FreezerInventoryCard extends HTMLElement {
  static getStubConfig() {
    return { title: "Freezer" };
  }

  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._unsub && hass?.connection) this._subscribe();
  }

  async _subscribe() {
    this._unsub = this._hass.connection
      .subscribeMessage((snap) => {
        this._snap = snap;
        this._render();
      }, { type: "freezer_inventory/subscribe" })
      .catch((err) => {
        this._error = err?.message || String(err);
        this._unsub = undefined;
        this._render();
      });
  }

  disconnectedCallback() {
    this._unsub?.then((unsub) => unsub && unsub());
    this._unsub = undefined;
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  getCardSize() {
    return 2 + (this._snap?.items.length || 0);
  }

  _render() {
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
    }
    const title = this._config?.title || "Freezer";
    let body;
    if (this._error) body = `<p class="err">Errore: ${esc(this._error)}</p>`;
    else if (!this._snap) body = `<p class="muted">Caricamento…</p>`;
    else if (!this._snap.items.length) body = `<p class="muted">Il freezer è vuoto.</p>`;
    else body = `<ul>${this._snap.items.map(row).join("")}</ul>`;
    this._root.innerHTML = `
      <style>
        ha-card { padding: 12px 16px; }
        h2 { margin: 0 0 8px; font-size: 1.2em; }
        ul { list-style: none; margin: 0; padding: 0; }
        li { padding: 8px 0; border-bottom: 1px solid var(--divider-color); }
        li:last-child { border-bottom: none; }
        .name { font-weight: 500; }
        .meta, .muted { color: var(--secondary-text-color); font-size: 0.9em; }
        .err { color: var(--error-color); }
      </style>
      <ha-card><h2>${esc(title)}</h2>${body}</ha-card>`;
  }
}

function row(item) {
  const parts = [`${item.quantity} pz`];
  if (item.weighed_pieces) parts.push(formatWeight(item.total_weight_g));
  parts.push(`da ${age(item.oldest_added_at)}`);
  return `<li><div class="name">${CATEGORY_ICON[item.category] || ""} ${esc(item.name)}</div>
    <div class="meta">${parts.join(" · ")}</div></li>`;
}

function formatWeight(g) {
  return g >= 1000 ? `${(g / 1000).toLocaleString("it-IT", { maximumFractionDigits: 2 })} kg` : `${g} g`;
}

function age(iso) {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days < 1) return "oggi";
  if (days < 60) return `${days} gg`;
  return `${Math.floor(days / 30)} mesi`;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/*
 * Registration must wait for the HA frontend. The frontend replaces
 * window.customElements with a scoped-registry polyfill *after* extra modules
 * start loading; an element defined on the native registry before the swap is
 * invisible to Lovelace ("Custom element not found"). The polyfill defines
 * <home-assistant> through the native registry, so its whenDefined() resolves
 * only once the final registry is in place. A timeout covers pages without it.
 */
const TAG = "freezer-inventory-card";

function register() {
  if (customElements.get(TAG)) return; // `customElements` is read now, not at module load
  customElements.define(TAG, FreezerInventoryCard);
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === TAG)) {
    window.customCards.push({ type: TAG, name: "Freezer Inventory", description: "Contenuto del freezer" });
  }
}

Promise.race([
  customElements.whenDefined("home-assistant"),
  new Promise((resolve) => setTimeout(resolve, 10000)),
]).then(register);
