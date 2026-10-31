# Freezer Inventory per Home Assistant

Inventario del freezer integrato in Home Assistant: ogni **voce** (es. "Bistecche di manzo") contiene dei **pezzi**, ciascuno con la propria data di inserimento e un peso facoltativo. Pensato per essere usato da tutta la famiglia dall'app companion.

- Categorie: carne, verdura, frutta, altro
- Quantità = numero di pezzi; pesi per singolo pezzo facoltativi (`200 300 0,5kg`)
- Prelievo del pezzo scelto (o del più vecchio), annullabile
- Nota libera, modifica di ogni campo, storico delle ultime 300 operazioni
- Card Lovelace inclusa, aggiornamento live su tutti i dispositivi
- Dati salvati in `.storage`, inclusi nei backup di HA

## Installazione (HACS)

1. HACS → ⋮ → **Custom repositories** → `https://github.com/massimosantoni/ha-freezer`, tipo **Integration**
2. Cerca **Freezer Inventory** → Download → riavvia Home Assistant
3. Impostazioni → Dispositivi e servizi → **Aggiungi integrazione** → Freezer Inventory

La card viene registrata automaticamente: in una dashboard aggiungi la card **Freezer Inventory** dal selettore, oppure

```yaml
type: custom:freezer-inventory-card
title: Freezer piano terra
age_warning_months:   # facoltativo: età oltre la quale la voce è evidenziata
  carne: 6
  verdura: 10
  frutta: 10
  altro: 3
```

### Uso della card

- **＋ Aggiungi**: nome (con suggerimenti dai nomi già presenti), categoria, quantità oppure pesi dei singoli pezzi (`200 300 0,5kg`), nota. Crea sempre una voce nuova.
- **＋ sulla riga**: aggiunge un pezzo con la data di oggi.
- **－ sulla riga**: apre la scelta del pezzo da prelevare (peso e data di ogni pezzo); il più vecchio è preselezionato. Sull'ultimo pezzo la voce viene eliminata.
- **Tocco sulla riga**: modifica nome, categoria, nota, peso e data di ogni pezzo; aggiunta/rimozione pezzi; eliminazione voce (doppia conferma).
- Ogni operazione mostra una notifica con **Annulla**; il pulsante **↶** in alto annulla l'ultima operazione anche più tardi.
- Ordinamento per **data** (pezzo più vecchio prima), **categoria** o **nome** (ricordato per dispositivo), filtro per categoria, ricerca su nome e nota.

## Entità

| Entità | Stato | Attributi |
|---|---|---|
| `sensor.<freezer>_pezzi_totali` | pezzi totali | voci, peso totale noto (g), pezzo più vecchio |
| `sensor.<freezer>_carne` … `_altro` | pezzi per categoria | voci |

## Azioni (servizi)

| Azione | Parametri | Risposta |
|---|---|---|
| `freezer_inventory.add_item` | `name`, `category`, `quantity`?, `weights`?, `note`? | `item` |
| `freezer_inventory.add_piece` | `item_id`, `weight_g`? | `item`, `piece` |
| `freezer_inventory.take_piece` | `item_id`, `piece_id`? (default: il più vecchio) | `piece`, `item`, `item_deleted` |
| `freezer_inventory.update_item` | `item_id`, `name`?, `category`?, `note`?, `pieces`? | `item` |
| `freezer_inventory.delete_item` | `item_id` | `item` |
| `freezer_inventory.undo_last` | — | `action`, `item_id`, `item_name` |
| `freezer_inventory.list_items` | `category`?, `sort` (`date`/`category`/`name`), `descending` | `items` |

`add_item` crea sempre una voce nuova, anche se il nome esiste già: ogni voce conserva la propria data.

Esempio:

```yaml
action: freezer_inventory.add_item
data:
  name: Bistecche di manzo – macellaio
  category: carne
  weights: "200 300 0,5kg"
  note: sottovuoto
response_variable: result
```

## Sviluppo

```bash
pip install -r requirements_test.txt
ruff check . && pytest -q -p no:logging
```

- `tests/test_inventory.py`: logica pura (`inventory.py`, nessuna dipendenza da HA)
- `tests/ha/`: integrazione su un Home Assistant reale
- `tests/frontend/`: registrazione della card (`node --test tests/frontend/card_registration.test.mjs`)
- `tests/e2e/card_e2e.cjs`: prova completa della card in un browser contro un HA avviato (manuale, istruzioni nel file)

Release: aggiorna `version` in `manifest.json`, crea il tag `vX.Y.Z` e una GitHub Release; HACS proporrà l'aggiornamento.
