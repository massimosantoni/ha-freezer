# Inventario freezer in Home Assistant — analisi e piano

_Stato: Fasi 1–4 completate, release 0.2.0 — 31/10/2026_

## 1. Requisiti (dalla richiesta)

| # | Requisito | Note |
|---|-----------|------|
| R1 | Nome stringa "lunga" (descrizione breve) | es. "Bistecche di manzo – macellaio Dro" |
| R2 | Categoria enum: carne, verdura, frutta, altro | filtro + ordinamento |
| R3 | Quantità con +/- | uso quotidiano, deve restare rapido |
| R4 | Peso opzionale dei singoli pezzi | 200 g / 300 g / 500 g, senza appesantire il flusso base |
| R5 | Data inserimento automatica | |
| R6 | Nota libera opzionale | aggiunta su decisione del 31/10 |
| A1 | Inserimento | |
| A2 | Visualizzazione, ordinabile per categoria o data | |
| A3 | Prelievo con protezione da tocchi accidentali | |
| A4 | (extra) Modifica per correzioni | |
| V  | Integrato in HA, usabile da tutta la famiglia (app companion) | |

Il requisito che discrimina davvero tra le soluzioni è **R4**: serve un modello "voce → N pezzi, ognuno con peso opzionale", non un semplice contatore.

## 2. Soluzioni esistenti

### 2.1 EverShelf (+ integrazione HACS ha-evershelf)

Pantry manager self-hosted (PHP 8 + SQLite, PWA vanilla JS, Docker, template Unraid ufficiale, MIT, autore italiano, traduzione base `it.json`). L'integrazione HA espone sensori (anche `sensor.evershelf_items_freezer`), calendario scadenze, todo lista spesa e servizi `add_scanned_item`, `mark_used`, `update_inventory_item`, `delete_inventory_item`. **Non fornisce una card Lovelace**: l'interfaccia d'uso resta la PWA di EverShelf.

| Req. | Copertura | Compromesso |
|------|-----------|-------------|
| R1 | ✅ | Nomi normalizzati ("il genere guida il titolo", v1.10) — può riscrivere i nomi a modo suo |
| R2 | ⚠️ | Non c'è un enum semplice: tassonomia di ingredienti canonici (modificabile). Carne/verdura/frutta/altro va emulato o accettato com'è |
| R3 | ✅ | Unità pezzi o g/ml; consumo da UI/banner |
| R4 | ⚠️ | Una riga è *o* a pezzi *o* a grammi; pezzi con pesi diversi = righe/lotti separati ("Bistecca 300 g" ×1, "Bistecca 500 g" ×1) |
| R5 | ❓ | Non documentata come campo visibile; il perno è la **scadenza** (stimata in automatico, con tabelle specifiche per freezer) |
| A2 | ⚠️ | Ordinamento per categoria non documentato; viste orientate a scadenze/location |
| A3 | ✅/❓ | Uso via swipe/hold-to-open; undo presente per alcune azioni |
| A4 | ✅ | |
| V | ⚠️ | Servizio separato da mantenere; in HA solo come pannello iframe/webpage (serve HTTPS via Traefik se HA è in HTTPS) |

**Pro**: maturo nelle funzioni, barcode, scadenze automatiche, ricette, lista spesa, gira su Unraid in 5 minuti.
**Contro**: molto più grande del problema (AI, ricette, prezzi, kiosk, bilance BLE); workflow pensato per dispensa con barcode, non per sacchetti da freezer senza etichetta; cadenza di rilascio molto alta con un solo maintainer → rischio di breaking change; la famiglia usa una UI diversa da HA.

### 2.2 Grocy (add-on HA + integrazione HACS)

ERP domestico maturo. Mappatura molto pulita: **product group** = categoria, **location** Freezer, ogni carico crea una **stock entry** con data di acquisto automatica e nota (peso via nota o unità "g"), consumo di una stock entry specifica.
**Contro decisivo**: prima di caricare qualcosa bisogna creare il prodotto in "master data"; UI e terminologia pesanti per la famiglia; da mobile via ingress è scomoda.

### 2.3 Simple Inventory (HACS) — **escluso**

Card nativa con +/-, categorie, scadenza, ordinamento e filtri, ma niente pesi per singolo pezzo, data di inserimento non documentata, nessuna conferma/undo sul "-". Escluso dopo approfondimento per le funzionalità mancanti.

### 2.4 Fridge Assistant (HACS, luglio 2026)

Integrazione nativa giovane, con stime AI e barcode. Da tenere d'occhio, non da adottare ora.

### 2.5 Decisione

Integrazione custom `freezer_inventory`.

## 3. Soluzione custom: `freezer_inventory`

### 3.1 Decisioni (31/10/2026)

| # | Decisione |
|---|-----------|
| D1 | **Nessuna fusione automatica**: `add_item` crea sempre una voce nuova, così ogni voce conserva la propria data di inserimento. L'autocompletamento del nome serve solo a scrivere più in fretta. |
| D2 | **Nota libera** opzionale sulla voce. |
| D3 | **Prelievo**: nella card si sceglie il pezzo dal chip (ognuno ha data e peso propri); il più vecchio è solo preselezionato. Il servizio `take_piece` senza `piece_id` preleva il più vecchio (utile per automazioni/Assist). |
| D4 | **Un solo freezer**: `single_config_entry: true` nel manifest. Il modello resta per-entry, quindi aprire a più freezer in futuro non richiede migrazioni. |
| D5 | **Deploy via GitHub + HACS** (custom repository), release taggate. |

### 3.2 Struttura del repository

```
freezer-inventory/                       # repo GitHub (pubblico: HACS non gestisce repo privati)
├── hacs.json                            # {"name": "Freezer Inventory", "homeassistant": "<min>"}
├── README.md
├── custom_components/freezer_inventory/
│   ├── manifest.json        # domain, version, config_flow, single_config_entry, dependencies
│   ├── __init__.py          # setup entry, Store, servizi, websocket, registrazione card JS
│   ├── config_flow.py
│   ├── const.py             # DOMAIN, CATEGORIES, limiti
│   ├── inventory.py         # modello + logica pura (add/take/update/undo), senza import HA → testabile
│   ├── sensor.py            # sensori riepilogo
│   ├── manager.py           # Store + operazioni condivise da servizi e websocket
│   ├── schemas.py           # schemi voluptuous comuni
│   ├── services.py          # azioni HA
│   ├── websocket.py         # API per la card (subscribe + comandi)
│   ├── services.yaml, icons.json
│   ├── translations/it.json, en.json
│   └── frontend/freezer-inventory-card.js   # Web Component vanilla, installato insieme all'integrazione
├── tests/
└── .github/workflows/       # hassfest + HACS action + pytest su push/PR
```

- La card sta **dentro** il pacchetto dell'integrazione: una sola installazione HACS, una sola versione.
- Repo: `github.com/massimosantoni/ha-freezer`, dominio `freezer_inventory`.
- Websocket e servizi aperti a tutti gli utenti autenticati (anche non admin), testato.
- Storage illeggibile → entry in errore, file lasciato intatto (mai sovrascritto con un inventario vuoto).
- **Persistenza**: `homeassistant.helpers.storage.Store` → `/config/.storage/freezer_inventory.<entry_id>`. Inclusa nei backup di HA.
- **Card auto-registrata**: `hass.http.async_register_static_paths([StaticPathConfig("/freezer_inventory/card.js", ...)])` + `frontend.add_extra_js_url(hass, url + "?v=<version>")` (il parametro versione evita la cache vecchia dopo un aggiornamento).
- **Aggiornamento live**: websocket `freezer_inventory/subscribe` che invia la lista completa a ogni modifica.
- **Lista voci NON negli attributi dei sensori** (limite 16 KB del recorder): gli attributi contengono solo conteggi.

### 3.3 Modello dati

```jsonc
{
  "items": {
    "01JD…": {
      "id": "01JD…",
      "name": "Bistecche di manzo – macellaio Dro",   // 2..80 caratteri
      "category": "carne",           // carne | verdura | frutta | altro
      "note": "",                    // opzionale, max 500
      "created_at": "2026-10-31T18:02:11+01:00",
      "updated_at": "…",
      "created_by": "Max",
      "pieces": [
        { "id": "…", "weight_g": 200,  "added_at": "2026-10-31T18:02:11+01:00" },
        { "id": "…", "weight_g": null, "added_at": "2026-11-12T10:15:00+01:00" }
      ]
    }
  },
  "log": [ { "id": "…", "ts": "…", "user": "Max", "action": "take_piece", "item_id": "…", "before": {…}, "undone": false } ]
}
```

- **quantità = `len(pieces)`**; peso sempre opzionale.
- **`added_at` per pezzo**; l'ordinamento per data usa il pezzo più vecchio (FIFO).
- **Voce a 0 pezzi → eliminata**; lo snapshot `before` nel log permette l'undo.
- Log a ring buffer (300 voci); `undo_last` ripristina lo snapshot dell'ultima operazione non annullata.
- Pesi in grammi interi. Parsing input: `200 300 0,5kg 1.2 kg 3hg` → `[200, 300, 500, 1200, 300]`; numero senza unità < 10 = kg, altrimenti g.

### 3.4 Servizi

| Servizio | Parametri | Note |
|---|---|---|
| `add_item` | name, category, quantity=1, weights=[], note | crea sempre una voce nuova; se `weights` è dato, la quantità è il numero di pesi |
| `add_piece` | item_id, weight_g? | il "+" |
| `take_piece` | item_id, piece_id? | senza piece_id: il più vecchio |
| `update_item` | item_id, name?, category?, note?, pieces? | `pieces` sostituisce la lista (pezzi senza id = nuovi) |
| `delete_item` | item_id | |
| `undo_last` | — | |
| `list_items` | category?, sort? | `SupportsResponse.ONLY` |

### 3.5 Sensori

- `sensor.freezer_pezzi_totali` (state = n. pezzi; attributi: pezzi e voci per categoria, data del pezzo più vecchio).
- opzionale `sensor.freezer_<categoria>`.

### 3.6 Card — UX

```
┌───────────────────────────────────────────┐
│ Freezer piano terra          [＋ Aggiungi] │
│ Ordina: (Data)(Categoria)(Nome)  🔍 cerca  │
│ [Tutte][🥩 Carne][🥦 Verdura][🍓 Frutta][📦]│
├───────────────────────────────────────────┤
│ 🥩 Bistecche di manzo – macellaio Dro      │
│    3 pz · 1,0 kg · da 12 gg      [－] [＋] │
│ 🥦 Piselli surgelati                       │
│    4 pz · da 3 mesi              [－] [＋] │
└───────────────────────────────────────────┘
```

- **Tap sulla riga** → dialog di modifica (nome, categoria, nota, pezzi con peso e data editabili, elimina voce con conferma).
- **＋** → aggiunge un pezzo senza peso; notifica con «Annulla» (il peso si aggiunge dalla modifica voce).
- **－** → bottom sheet con i pezzi come chip (`200 g · 31/10`, `— · 12/11`), il più vecchio preselezionato, pulsante **Preleva** (D3). Toast **Annulla** 6 s. Ultimo pezzo: "Preleva ed elimina voce".
- **Aggiungi**: nome con autocompletamento, chip categoria, stepper quantità, campo "Pesi (facoltativo)", nota.
- **Età colorata** con soglie per categoria (`age_warning_months` nella config della card).
- Web Component vanilla, `<dialog>` nativo, variabili CSS del tema HA.
- Notifiche con le `hass-notification` native di HA (azione «Annulla» → `undo_last`); pulsante ↶ in testata finché c'è qualcosa da annullare.

### 3.7 Accesso rapido in famiglia

- Vista dashboard "Freezer" a pannello pieno.
- Tag NFC sul freezer registrato nell'app companion → apre la vista.

## 4. Piano di lavoro

| Fase | Contenuto | Stato |
|---|---|---|
| 1 | `inventory.py` + test pytest puri | ✅ 55 test |
| 2 | `__init__`, config flow, servizi, websocket, sensori; test con `pytest-homeassistant-custom-component` | ✅ 21 test (HA 2026.2.3 in locale; CI su ultima HA) — card provvisoria in sola lettura |
| 3 | Card: lista, sort/filtri, +/-, sheet prelievo, toast undo | ✅ 0.2.0 |
| 4 | Dialog aggiungi/modifica, autocompletamento, età colorata, traduzioni | ✅ 0.2.0 (soglie età nella config della card; card solo in italiano) |
| 5 | Repo GitHub, `hacs.json`, workflow CI (hassfest, HACS validation, pytest), prima release; installazione come custom repository HACS; vista dashboard + tag NFC | CI verde, installato via HACS; release `v0.2.0` e tag NFC da fare |
| 6 (extra) | Intent Assist, export CSV, notifiche età | |

Note di deploy:
- Flusso: tag `vX.Y.Z` + GitHub Release → HACS mostra l'aggiornamento in HA → riavvio.
- `version` in `manifest.json` allineata al tag (controllo in CI).
- Forgejo eventualmente come mirror, non necessario.
- Backup: coperto dai backup HA (`.storage`).
- 0.1.1 (31/10): la card si registra solo dopo `customElements.whenDefined("home-assistant")`. Il frontend HA sostituisce `window.customElements` con un polyfill di registro scoped *dopo* l'avvio dei moduli extra; una registrazione immediata finiva sul registro nativo → "Custom element not found". Test di regressione in `tests/frontend/`. Verificato funzionante su HA 2026.10.
- 0.2.0 (31/10): card completa (aggiunta, +/-, prelievo dal pezzo scelto, modifica pezzi e date, eliminazione, annulla, ordinamenti, filtri, ricerca, età evidenziata). Test end-to-end in browser (`tests/e2e/card_e2e.cjs`) contro HA locale.
