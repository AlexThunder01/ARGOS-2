# SPEC — [Nome del Task]

> **Istruzioni:** Compila questo file prima di iniziare. Poi passa il file all'agente
> con `/clear` e una nuova sessione. L'agente ha tutto il contesto necessario.

---

## Obiettivo
<!-- Una frase: cosa deve essere fatto e perché. -->


## File coinvolti
<!-- Lista dei file da leggere/modificare. Sii preciso: questo evita all'agente
     di scansionare l'intero progetto prima di fare qualcosa. -->

| File | Azione |
|------|--------|
| `src/...` | modifica |
| `tests/...` | aggiungere test |

## Vincoli e regole
<!-- Regole architetturali da rispettare. Copia quelle rilevanti dalle agent instructions. -->

- [ ] Nessun metadata hardcoded fuori da `ToolSpec`
- [ ] Nessun mock del DB nei test
- [ ] Un tool call per turno LLM
- [ ] ...

## Input / Output atteso
<!-- Descrizione precisa del comportamento: cosa entra, cosa esce, casi limite. -->

**Input:**
```
...
```

**Output atteso:**
```
...
```

**Casi limite:**
- ...

## Classe / funzione da aggiungere o modificare
<!-- Più contesto fornisci qui, meno tool call sprechi. -->

```python
# Esempio di firma attesa
def my_function(arg1: str, arg2: int) -> str:
    ...
```

## Dipendenze
<!-- Librerie nuove? Migrazioni DB? Variabili d'ambiente? -->

- [ ] Nessuna dipendenza nuova
- [ ] Aggiungere a `requirements.txt`: `...`
- [ ] Nuova variabile d'ambiente: `...`

## Test da scrivere
<!-- Descrivi i test che devono passare al termine del task. -->

- [ ] Test unitario per `...`
- [ ] Test di integrazione per `...`

## Note aggiuntive
<!-- Qualsiasi altra cosa utile all'agente: link a PR correlate, decisioni già prese, ecc. -->

