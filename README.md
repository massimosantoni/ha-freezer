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

La card viene registrata automaticamente: in una dashboard aggiungi

```yaml
type: custom:freezer-inventory-card
title: Freezer piano terra
```

> Versione attuale della card: elenco in sola lettura (Fase 2). La card completa con +/-, prelievo, aggiunta e modifica arriva con la Fase 3.

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

`tests/test_inventory.py` copre la logica pura (`inventory.py`, nessuna dipendenza da HA); `tests/ha/` testa l'integrazione su un Home Assistant reale.

Release: aggiorna `version` in `manifest.json`, crea il tag `vX.Y.Z` e una GitHub Release; HACS proporrà l'aggiornamento.
