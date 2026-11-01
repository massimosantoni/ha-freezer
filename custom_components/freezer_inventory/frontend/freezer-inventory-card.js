/*
 * Freezer Inventory card
 *
 *   type: custom:freezer-inventory-card
 *   title: Freezer piano terra        # facoltativo
 *   age_warning_months:               # facoltativo: evidenzia i pezzi più vecchi di N mesi
 *     carne: 6
 *     verdura: 10
 *     frutta: 10
 *     altro: 3
 *
 * Data arrive via the websocket subscription `freezer_inventory/subscribe`;
 * every action is a websocket command with the same payload as the services.
 * Plain Web Component (no build step, no dependency on HA internal elements).
 */

const CATEGORIES = {
  carne: { icon: "🥩", label: "Carne" },
  verdura: { icon: "🥦", label: "Verdura" },
  frutta: { icon: "🍓", label: "Frutta" },
  altro: { icon: "📦", label: "Altro" },
};
const CATEGORY_KEYS = Object.keys(CATEGORIES);
const DEFAULT_AGE_WARNING = { carne: 6, verdura: 10, frutta: 10, altro: 3 };
const SORTS = { date: "Data", category: "Categoria", name: "Nome" };
const DAY_MS = 86400000;

const ERRORS = {
  invalid_name: "Il nome deve avere tra 2 e 80 caratteri.",
  invalid_category: "Scegli una categoria.",
  invalid_note: "La nota non può superare i 500 caratteri.",
  invalid_amount: "Valore non valido: grammi (es. 250, 0,5kg) oppure porzioni (intero sotto 10, es. 4; oltre scrivi «12 por»).",
  invalid_weight: "Peso non valido: deve essere tra 1 g e 50 kg.",
  invalid_portions: "Le porzioni devono essere tra 1 e 50.",
  invalid_quantity: "La quantità deve essere tra 1 e 50.",
  quantity_weights_mismatch: "La quantità non corrisponde al numero di valori indicati.",
  item_not_found: "Voce non trovata: forse è già stata prelevata o eliminata.",
  piece_not_found: "Pezzo non trovato: forse è già stato prelevato.",
  empty_pieces: "Serve almeno un pezzo: per togliere la voce usa «Elimina voce».",
  invalid_piece: "Pezzo non valido: indica un peso oppure delle porzioni.",
  invalid_date: "Data non valida.",
  nothing_to_undo: "Non c'è nulla da annullare.",
  not_loaded: "L'integrazione Freezer Inventory non è attiva.",
};
const UNDO_LABEL = {
  add_item: "inserimento",
  add_piece: "aggiunta pezzo",
  take_piece: "prelievo",
  update_item: "modifica",
  delete_item: "eliminazione",
};

// ---------------------------------------------------------------- helpers --
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const formatWeight = (g) =>
  g >= 1000 ? `${(g / 1000).toLocaleString("it-IT", { maximumFractionDigits: 2 })} kg` : `${g} g`;

const formatPortions = (n) => `${n} por.`;

// what a piece holds, for chips: "300 g", "4 por.", "—"
function formatAmount(p) {
  if (p.weight_g != null) return formatWeight(p.weight_g);
  if (p.portions != null) return formatPortions(p.portions);
  return "—";
}

// value for the single "g / por." input; round-trips through the server parser:
// bare numbers below 10 are portions, so small weights / big portion counts get a unit
function amountInput(p) {
  if (p?.weight_g != null) return p.weight_g >= 10 ? `${p.weight_g}` : `${p.weight_g}g`;
  if (p?.portions != null) return p.portions < 10 ? `${p.portions}` : `${p.portions} por`;
  return "";
}

function formatDate(iso) {
  const d = new Date(iso);
  const opts = { day: "2-digit", month: "2-digit" };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = "2-digit";
  return d.toLocaleDateString("it-IT", opts);
}

const ageDays = (iso) => Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / DAY_MS));

function formatAge(iso) {
  const days = ageDays(iso);
  if (days < 1) return "oggi";
  if (days === 1) return "1 giorno";
  if (days < 60) return `${days} gg`;
  return `${Math.floor(days / 30.44)} mesi`;
}

// local date "YYYY-MM-DD" for <input type="date">
function isoDay(iso) {
  const d = iso ? new Date(iso) : new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// rough client-side count, only for the "N pezzi" hint; the server parses for real
const countWeights = (text) => (String(text).match(/\d+(?:[.,]\d+)?/g) || []).length;

function errorText(err) {
  return ERRORS[err?.code] || err?.message || String(err);
}

// ------------------------------------------------------------------- card --
class FreezerInventoryCard extends HTMLElement {
  static getStubConfig() {
    return { title: "Freezer" };
  }

  constructor() {
    super();
    this._snap = null;
    this._filter = "all";
    this._search = "";
    this._sort = this._loadPref("sort", "date");
  }

  setConfig(config) {
    this._config = { ...(config || {}) };
    this._ageWarning = { ...DEFAULT_AGE_WARNING, ...(this._config.age_warning_months || {}) };
    if (this.shadowRoot) this._renderList();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._build();
    if (!this._unsub && hass?.connection) this._subscribe();
  }

  getCardSize() {
    return 3 + (this._snap?.items.length || 0);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    this._unsub?.then((unsub) => unsub?.()).catch(() => {});
    this._unsub = undefined;
  }

  // ------------------------------------------------------------- data ----
  _subscribe() {
    this._unsub = this._hass.connection
      .subscribeMessage(
        (snap) => {
          this._snap = snap;
          this._error = undefined;
          this._renderList();
        },
        { type: "freezer_inventory/subscribe" },
      )
      .catch((err) => {
        this._error = errorText(err);
        this._unsub = undefined;
        this._renderList();
      });
  }

  _call(command, data = {}) {
    return this._hass.callWS({ type: `freezer_inventory/${command}`, ...data });
  }

  _item(id) {
    return this._snap?.items.find((i) => i.id === id);
  }

  _loadPref(key, fallback) {
    try {
      return localStorage.getItem(`freezer_inventory.${key}`) || fallback;
    } catch {
      return fallback;
    }
  }

  _savePref(key, value) {
    try {
      localStorage.setItem(`freezer_inventory.${key}`, value);
    } catch {
      /* private mode / blocked storage: preference is per-session only */
    }
  }

  _toast(message, undo = false) {
    const detail = { message, duration: undo ? 6000 : 4000 };
    if (undo) detail.action = { text: "Annulla", action: () => this._undo() };
    this.dispatchEvent(new CustomEvent("hass-notification", { detail, bubbles: true, composed: true }));
  }

  async _undo() {
    try {
      const res = await this._call("undo_last");
      this._toast(`Annullato: ${UNDO_LABEL[res.action] || res.action} «${res.item_name}»`);
    } catch (err) {
      this._toast(errorText(err));
    }
  }

  // ---------------------------------------------------------- skeleton ----
  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <div class="title"></div>
          <button class="icon" data-action="undo" title="Annulla l'ultima operazione" hidden>↶</button>
          <button class="primary" data-action="add">＋ Aggiungi</button>
        </div>
        <div class="controls">
          <div class="chips sort">
            ${Object.entries(SORTS)
              .map(([k, l]) => `<button class="chip" data-sort="${k}">${l}</button>`)
              .join("")}
          </div>
          <input class="search" type="search" placeholder="Cerca…" aria-label="Cerca">
          <div class="chips filter"></div>
        </div>
        <div class="list"></div>
      </ha-card>
      <dialog class="take"></dialog>
      <dialog class="form"></dialog>`;

    root.querySelector(".header").addEventListener("click", (e) => this._onHeaderClick(e));
    root.querySelector(".controls").addEventListener("click", (e) => this._onControlsClick(e));
    root.querySelector(".search").addEventListener("input", (e) => {
      this._search = e.target.value;
      this._renderList();
    });
    root.querySelector(".list").addEventListener("click", (e) => this._onListClick(e));
    for (const dlg of root.querySelectorAll("dialog")) {
      // tap on the backdrop closes the dialog
      dlg.addEventListener("click", (e) => {
        if (e.target === dlg) dlg.close();
      });
    }
    this._renderList();
  }

  _onHeaderClick(e) {
    const action = e.target.closest("button")?.dataset.action;
    if (action === "add") this._openForm(null);
    if (action === "undo") this._undo();
  }

  _onControlsClick(e) {
    const btn = e.target.closest("button");
    if (!btn) return;
    if (btn.dataset.sort) {
      this._sort = btn.dataset.sort;
      this._savePref("sort", this._sort);
    }
    if (btn.dataset.filter) this._filter = btn.dataset.filter;
    this._renderList();
  }

  async _onListClick(e) {
    const btn = e.target.closest("button[data-action]");
    const row = e.target.closest("[data-id]");
    if (!row) return;
    const item = this._item(row.dataset.id);
    if (!item) return;
    if (!btn) return this._openForm(item);
    if (btn.dataset.action === "take") return this._openTake(item);
    if (btn.dataset.action === "plus") {
      btn.disabled = true;
      try {
        await this._call("add_piece", { item_id: item.id });
        this._toast(`Aggiunto un pezzo a «${item.name}»`, true);
      } catch (err) {
        this._toast(errorText(err));
      } finally {
        btn.disabled = false;
      }
    }
  }

  // -------------------------------------------------------------- list ----
  _visibleItems() {
    const q = this._search.trim().toLocaleLowerCase("it");
    let items = (this._snap?.items || []).filter(
      (i) =>
        (this._filter === "all" || i.category === this._filter) &&
        (!q || i.name.toLocaleLowerCase("it").includes(q) || i.note.toLocaleLowerCase("it").includes(q)),
    );
    const byDate = (a, b) => a.oldest_added_at.localeCompare(b.oldest_added_at) || a.name.localeCompare(b.name, "it");
    if (this._sort === "name") items = items.sort((a, b) => a.name.localeCompare(b.name, "it", { sensitivity: "base" }) || byDate(a, b));
    else if (this._sort === "category")
      items = items.sort((a, b) => CATEGORY_KEYS.indexOf(a.category) - CATEGORY_KEYS.indexOf(b.category) || byDate(a, b));
    else items = items.sort(byDate);
    return items;
  }

  _renderList() {
    const root = this.shadowRoot;
    if (!root) return;
    root.querySelector(".title").textContent = this._config?.title || "Freezer";
    root.querySelector('[data-action="undo"]').hidden = !this._snap?.can_undo;
    for (const b of root.querySelectorAll("[data-sort]")) b.classList.toggle("on", b.dataset.sort === this._sort);

    const all = this._snap?.items || [];
    const pieces = (cat) => all.filter((i) => cat === "all" || i.category === cat).reduce((n, i) => n + i.quantity, 0);
    root.querySelector(".filter").innerHTML = ["all", ...CATEGORY_KEYS]
      .map((k) => {
        const label = k === "all" ? "Tutto" : `${CATEGORIES[k].icon} ${CATEGORIES[k].label}`;
        return `<button class="chip ${this._filter === k ? "on" : ""}" data-filter="${k}">${label} <span class="n">${pieces(k)}</span></button>`;
      })
      .join("");

    const list = root.querySelector(".list");
    if (this._error) {
      list.innerHTML = `<p class="empty err">${esc(this._error)}</p>`;
      return;
    }
    if (!this._snap) {
      list.innerHTML = `<p class="empty">Caricamento…</p>`;
      return;
    }
    const items = this._visibleItems();
    if (!items.length) {
      list.innerHTML = `<p class="empty">${all.length ? "Nessuna voce corrisponde ai filtri." : "Il freezer è vuoto."}</p>`;
      return;
    }
    let html = "";
    let group = null;
    for (const item of items) {
      if (this._sort === "category" && item.category !== group) {
        group = item.category;
        html += `<div class="group">${CATEGORIES[group].icon} ${CATEGORIES[group].label}</div>`;
      }
      html += this._rowHtml(item);
    }
    list.innerHTML = html;
  }

  _rowHtml(item) {
    const meta = [`${item.quantity} pz`];
    const measures = [];
    if (item.weighed_pieces) measures.push(formatWeight(item.total_weight_g));
    if (item.portioned_pieces) measures.push(formatPortions(item.total_portions));
    // "+" = some pieces have no weight/portions, so the total is a lower bound
    if (measures.length && item.weighed_pieces + item.portioned_pieces < item.quantity) {
      measures[measures.length - 1] += "+";
    }
    meta.push(...measures);
    const months = ageDays(item.oldest_added_at) / 30.44;
    const old = months >= (this._ageWarning[item.category] ?? Infinity);
    meta.push(`<span class="age ${old ? "old" : ""}">da ${formatAge(item.oldest_added_at)}</span>`);
    return `
      <div class="row" data-id="${esc(item.id)}">
        <div class="cat">${CATEGORIES[item.category]?.icon || ""}</div>
        <div class="body">
          <div class="name">${esc(item.name)}</div>
          <div class="meta">${meta.join(" · ")}</div>
          ${item.note ? `<div class="note">${esc(item.note)}</div>` : ""}
        </div>
        <button class="round" data-action="take" aria-label="Preleva">－</button>
        <button class="round" data-action="plus" aria-label="Aggiungi un pezzo">＋</button>
      </div>`;
  }

  // ------------------------------------------------------- take sheet ----
  _openTake(item) {
    const dlg = this.shadowRoot.querySelector("dialog.take");
    let selected = item.pieces[0]?.id; // oldest is preselected (D3)
    const chips = item.pieces
      .map(
        (p) => `<button class="chip piece" data-piece="${esc(p.id)}">
          <b>${formatAmount(p)}</b><small>${formatDate(p.added_at)}</small></button>`,
      )
      .join("");
    const last = item.quantity === 1;
    dlg.innerHTML = `
      <h3>Prelevare da «${esc(item.name)}»?</h3>
      <p class="hint">${last ? "È l'ultimo pezzo: la voce verrà eliminata." : "Scegli il pezzo (il più vecchio è già selezionato)."}</p>
      <div class="chips pieces">${chips}</div>
      <p class="err" hidden></p>
      <div class="actions">
        <button data-action="cancel">Annulla</button>
        <button class="primary" data-action="confirm">${last ? "Preleva ed elimina voce" : "Preleva"}</button>
      </div>`;
    const mark = () => dlg.querySelectorAll("[data-piece]").forEach((b) => b.classList.toggle("on", b.dataset.piece === selected));
    mark();
    dlg.onclick = async (e) => {
      if (e.target === dlg) return dlg.close();
      const chip = e.target.closest("[data-piece]");
      if (chip) {
        selected = chip.dataset.piece;
        return mark();
      }
      const action = e.target.closest("button")?.dataset.action;
      if (action === "cancel") return dlg.close();
      if (action !== "confirm") return;
      const btn = e.target.closest("button");
      btn.disabled = true;
      try {
        const res = await this._call("take_piece", { item_id: item.id, piece_id: selected });
        dlg.close();
        const what = formatAmount(res.piece);
        this._toast(`Prelevato ${what === "—" ? "" : `${what} `}da «${item.name}»`, true);
      } catch (err) {
        const p = dlg.querySelector(".err");
        p.textContent = errorText(err);
        p.hidden = false;
        btn.disabled = false;
      }
    };
    dlg.showModal();
  }

  // --------------------------------------------------- add/edit form ----
  _openForm(item) {
    const dlg = this.shadowRoot.querySelector("dialog.form");
    const edit = !!item;
    const names = [...new Set((this._snap?.items || []).map((i) => i.name))];
    const category = item?.category || (CATEGORIES[this._filter] ? this._filter : "carne");
    dlg.innerHTML = `
      <h3>${edit ? "Modifica voce" : "Aggiungi al freezer"}</h3>
      <form novalidate>
        <label>Nome
          <input name="name" maxlength="80" required autocomplete="off" list="fi-names" value="${esc(item?.name)}">
        </label>
        <datalist id="fi-names">${names.map((n) => `<option value="${esc(n)}">`).join("")}</datalist>
        <div class="field">Categoria
          <div class="chips cats">
            ${CATEGORY_KEYS.map(
              (k) => `<button type="button" class="chip ${k === category ? "on" : ""}" data-cat="${k}">${CATEGORIES[k].icon} ${CATEGORIES[k].label}</button>`,
            ).join("")}
          </div>
        </div>
        ${edit ? this._piecesEditorHtml(item) : this._quantityHtml()}
        <label>Nota <span class="opt">(facoltativa)</span>
          <textarea name="note" maxlength="500" rows="2">${esc(item?.note)}</textarea>
        </label>
        <p class="err" hidden></p>
        <div class="actions">
          ${edit ? `<button type="button" class="danger" data-action="delete">Elimina voce</button><span class="spacer"></span>` : ""}
          <button type="button" data-action="cancel">Annulla</button>
          <button type="submit" class="primary">${edit ? "Salva" : "Aggiungi"}</button>
        </div>
      </form>`;

    const form = dlg.querySelector("form");
    // form.name is the <form> name attribute, so always go through elements
    const field = (n) => form.elements.namedItem(n);
    let cat = category;
    const showError = (msg) => {
      const p = dlg.querySelector(".err");
      p.textContent = msg;
      p.hidden = !msg;
    };

    dlg.onclick = async (e) => {
      if (e.target === dlg) return dlg.close();
      const btn = e.target.closest("button");
      if (!btn) return;
      if (btn.dataset.cat) {
        cat = btn.dataset.cat;
        dlg.querySelectorAll("[data-cat]").forEach((b) => b.classList.toggle("on", b.dataset.cat === cat));
        return;
      }
      if (btn.dataset.step) return this._stepQuantity(form, Number(btn.dataset.step));
      if (btn.dataset.action === "cancel") return dlg.close();
      if (btn.dataset.action === "add-piece") return this._appendPieceRow(form);
      if (btn.dataset.action === "remove-piece") return btn.closest(".piece-row").remove();
      if (btn.dataset.action === "delete") {
        if (!btn.classList.contains("confirm")) {
          btn.classList.add("confirm");
          btn.textContent = "Confermi l'eliminazione?";
          return;
        }
        try {
          await this._call("delete_item", { item_id: item.id });
          dlg.close();
          this._toast(`Eliminata «${item.name}»`, true);
        } catch (err) {
          showError(errorText(err));
        }
      }
    };

    if (!edit) {
      field("weights").addEventListener("input", () => {
        const n = countWeights(field("weights").value);
        field("quantity").disabled = n > 0;
        dlg.querySelectorAll("[data-step]").forEach((b) => (b.disabled = n > 0));
        if (n > 0) field("quantity").value = n;
      });
    }

    form.onsubmit = async (e) => {
      e.preventDefault();
      showError("");
      const submit = form.querySelector('[type="submit"]');
      submit.disabled = true;
      try {
        if (edit) {
          const pieces = this._readPieces(form);
          await this._call("update_item", {
            item_id: item.id,
            name: field("name").value,
            category: cat,
            note: field("note").value,
            pieces,
          });
          dlg.close();
          this._toast(`Salvata «${field("name").value.trim()}»`, true);
        } else {
          const data = { name: field("name").value, category: cat, note: field("note").value };
          if (field("weights").value.trim()) data.weights = field("weights").value;
          else data.quantity = Number(field("quantity").value) || 1;
          const res = await this._call("add_item", data);
          dlg.close();
          this._toast(`Aggiunto «${res.item.name}» (${res.item.quantity} pz)`, true);
        }
      } catch (err) {
        showError(errorText(err));
      } finally {
        submit.disabled = false;
      }
    };

    dlg.showModal();
    if (!edit) field("name").focus();
  }

  _quantityHtml() {
    return `
      <div class="field">Quantità
        <div class="stepper">
          <button type="button" class="round" data-step="-1" aria-label="Meno">－</button>
          <input name="quantity" type="number" min="1" max="50" value="1" inputmode="numeric">
          <button type="button" class="round" data-step="1" aria-label="Più">＋</button>
        </div>
      </div>
      <label>Peso o porzioni dei pezzi <span class="opt">(facoltativo, uno per pezzo)</span>
        <input name="weights" placeholder="es. 300 0,5kg 4" autocomplete="off">
        <span class="opt">da 10 in su = grammi, sotto 10 = porzioni</span>
      </label>`;
  }

  _stepQuantity(form, delta) {
    const input = form.elements.namedItem("quantity");
    input.value = Math.min(50, Math.max(1, (Number(input.value) || 1) + delta));
  }

  _piecesEditorHtml(item) {
    return `
      <div class="field">Pezzi <span class="opt">(peso in g, oppure porzioni se sotto 10)</span>
        <div class="pieces-editor">${item.pieces.map((p) => this._pieceRowHtml(p)).join("")}</div>
        <button type="button" data-action="add-piece">＋ Aggiungi pezzo</button>
      </div>`;
  }

  _pieceRowHtml(p) {
    return `
      <div class="piece-row" data-piece="${esc(p?.id || "")}" data-day="${p ? isoDay(p.added_at) : ""}">
        <input class="w" placeholder="g / por." autocomplete="off"
          value="${esc(amountInput(p))}" aria-label="Peso in grammi o porzioni">
        <input class="d" type="date" value="${isoDay(p?.added_at)}" max="${isoDay()}" aria-label="Data di inserimento">
        <button type="button" class="round" data-action="remove-piece" aria-label="Rimuovi pezzo">×</button>
      </div>`;
  }

  _appendPieceRow(form) {
    form.querySelector(".pieces-editor").insertAdjacentHTML("beforeend", this._pieceRowHtml(null));
  }

  _readPieces(form) {
    // existing piece: send added_at only if the day changed (keeps the exact time otherwise);
    // new piece: send the day only if it is not today (server uses "now")
    return [...form.querySelectorAll(".piece-row")].map((row) => {
      const day = row.querySelector(".d").value;
      // parsed by the server with the same rule as the add form ("" = unknown)
      const piece = { amount: row.querySelector(".w").value.trim() };
      if (row.dataset.piece) {
        piece.id = row.dataset.piece;
        if (day && day !== row.dataset.day) piece.added_at = day;
      } else if (day && day !== isoDay()) {
        piece.added_at = day;
      }
      return piece;
    });
  }
}

const STYLE = `
  :host { display: block; }
  ha-card { padding: 12px 12px 4px; }
  button { font: inherit; color: inherit; cursor: pointer; border: 1px solid var(--divider-color);
    background: var(--card-background-color); border-radius: 18px; padding: 6px 12px; }
  button:disabled { opacity: .5; cursor: default; }
  button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
  button.danger { color: var(--error-color); border-color: var(--error-color); }
  button.danger.confirm { background: var(--error-color); color: #fff; }
  button.icon { border: none; font-size: 1.3em; padding: 2px 8px; }
  button.round { width: 40px; height: 40px; padding: 0; border-radius: 50%; font-size: 1.2em; flex: none; }
  .header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .title { flex: 1; font-size: 1.25em; font-weight: 500; }
  .controls { display: flex; flex-direction: column; gap: 8px; margin-bottom: 4px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { padding: 4px 10px; font-size: .9em; }
  .chip.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
  .chip .n { opacity: .7; font-size: .85em; }
  input, textarea { font: inherit; color: var(--primary-text-color); background: var(--card-background-color);
    border: 1px solid var(--divider-color); border-radius: 8px; padding: 8px; box-sizing: border-box; width: 100%; }
  .search { width: 100%; }
  .group { margin: 12px 0 2px; font-weight: 500; color: var(--secondary-text-color); font-size: .9em; }
  .row { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--divider-color); cursor: pointer; }
  .row:last-child { border-bottom: none; }
  .cat { font-size: 1.4em; width: 1.6em; text-align: center; flex: none; }
  .body { flex: 1; min-width: 0; }
  .name { font-weight: 500; overflow-wrap: anywhere; }
  .meta, .note, .hint, .opt { color: var(--secondary-text-color); font-size: .9em; }
  .note { font-style: italic; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .age.old { color: var(--warning-color, #e65100); font-weight: 500; }
  .empty { color: var(--secondary-text-color); text-align: center; padding: 16px 0; }
  .err { color: var(--error-color); margin: 8px 0 0; }
  dialog { border: none; border-radius: 16px; padding: 16px; width: min(460px, calc(100vw - 24px)); box-sizing: border-box;
    background: var(--card-background-color); color: var(--primary-text-color); max-height: 90vh; }
  dialog::backdrop { background: rgba(0, 0, 0, .45); }
  dialog.take { margin-bottom: 12px; }
  dialog h3 { margin: 0 0 8px; font-weight: 500; }
  form { display: flex; flex-direction: column; gap: 12px; }
  label, .field { display: flex; flex-direction: column; gap: 4px; font-size: .9em; color: var(--secondary-text-color); }
  label input, label textarea { font-size: 1.1em; }
  .chip.piece { display: flex; flex-direction: column; align-items: center; min-width: 70px; padding: 6px 10px; border-radius: 12px; }
  .chip.piece small { opacity: .8; }
  .stepper { display: flex; align-items: center; gap: 8px; }
  .stepper input { width: 80px; text-align: center; font-size: 1.1em; }
  .pieces-editor { display: flex; flex-direction: column; gap: 6px; margin-bottom: 4px; }
  .piece-row { display: flex; align-items: center; gap: 6px; }
  .piece-row .w { width: 100px; flex: none; }
  .piece-row .d { flex: 1; min-width: 0; }
  .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; flex-wrap: wrap; }
  .actions .spacer { flex: 1; }
`;

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
