# Freezer Inventory per Home Assistant

Inventario del freezer integrato in Home Assistant: ogni **voce** (es. "Bistecche di manzo") contiene dei **pezzi**, ciascuno con la propria data di inserimento e un peso facoltativo. Pensato per essere usato da tutta la famiglia dall'app companion.

- Categorie: carne, verdura, frutta, altro
- Quantità = numero di pezzi; per ogni pezzo, facoltativo, un peso **oppure** un numero di porzioni (`300 0,5kg 4`)
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

**Peso o porzioni** — un solo campo per pezzo, l'unità si deduce dal numero:

| Scrivi | Diventa |
|---|---|
| `300`, `1200` (da 10 in su) | grammi |
| `0,5kg`, `1.2 kg`, `3hg`, `5g` | grammi (unità esplicita) |
| `4` (intero sotto 10) | 4 porzioni |
| `12 por`, `12 porzioni` | porzioni oltre 9 |
| `0,5` | errore: scrivi `0,5kg` |

In aggiunta multipla i valori si separano con spazi: `300 0,5kg 4` = tre pezzi. I totali mostrano grammi e porzioni separati (es. `1,2 kg · 9 por.`); un `+` finale indica che alcuni pezzi non hanno né peso né porzioni.

- **＋ Aggiungi**: nome (con suggerimenti dai nomi già presenti), categoria, quantità oppure peso/porzioni dei singoli pezzi, nota. Crea sempre una voce nuova.
- **＋ sulla riga**: aggiunge un pezzo con la data di oggi.
- **－ sulla riga**: apre la scelta del pezzo da prelevare (peso o porzioni e data di ogni pezzo); il più vecchio è preselezionato. Sull'ultimo pezzo la voce viene eliminata.
- **Tocco sulla riga**: modifica nome, categoria, nota, peso/porzioni e data di ogni pezzo; aggiunta/rimozione pezzi; eliminazione voce (doppia conferma).
- Ogni operazione mostra una notifica con **Annulla**; il pulsante **↶** in alto annulla l'ultima operazione anche più tardi.
- Ordinamento per **data** (pezzo più vecchio prima), **categoria** o **nome** (ricordato per dispositivo), filtro per categoria, ricerca su nome e nota.

## Entità

| Entità | Stato | Attributi |
|---|---|---|
| `sensor.<freezer>_pezzi_totali` | pezzi totali | voci, peso totale noto (g), porzioni totali, pezzo più vecchio |
| `sensor.<freezer>_carne` … `_altro` | pezzi per categoria | voci |

## Azioni (servizi)

| Azione | Parametri | Risposta |
|---|---|---|
| `freezer_inventory.add_item` | `name`, `category`, `quantity`?, `weights`? (pesi o porzioni, es. `300 0,5kg 4`), `note`? | `item` |
| `freezer_inventory.add_piece` | `item_id`, `weight_g`? \| `portions`? \| `amount`? (testo, es. `4`) | `item`, `piece` |
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
  weights: "300 0,5kg 4"   # 300 g, 500 g, 4 porzioni
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
