# Trainingsplan TuS Harpen 08/11

Öffentliche Seite: https://trainingsplan.tus-harpen.de (Webspace: `/matz_dinge/trainingsplan`)

## Pflegen

1. `Trainingszeiten.xlsx` öffnen, im Blatt **Eingabe** die Zeiten ändern (eine Zeile pro Mannschaft, je Wochentag von/bis/Ort).
   Neue Mannschaften zuerst im Blatt **Mannschaften** anlegen (Name, Kurzname, Farbe). Gültigkeitszeiträume im Blatt **Pläne**.
2. Die geänderte Datei hier im Ordner `trainingsplan/` hochladen (GitHub: Datei öffnen → „…“ → *Upload files* bzw. ersetzen) und *Commit changes*.
3. Der Workflow **Trainingsplan auf IONOS aktualisieren** baut die Seite und lädt sie hoch – nach ca. 1 Minute ist sie online.

## Dateien

| Datei | Zweck |
|---|---|
| `Trainingszeiten.xlsx` | Eingabe (einzige Datenquelle) |
| `trainingszeiten_json.py` | liest die Excel-Datei → `trainingsplan.json` |
| `training.html` | Vorlage der Seite (Wochenplan, Mannschaften, Platz jetzt) |
| `seite_bauen.py` | Vorlage + Daten → `index.html` |

## Adressen

- Wochenplan: `https://trainingsplan.tus-harpen.de/`
- Eine Mannschaft: `https://trainingsplan.tus-harpen.de/?team=G4-Jugend&ansicht=mannschaften`
- Vereinsheim (Fernseher): `https://trainingsplan.tus-harpen.de/?ansicht=platz&stil=dunkel`

## Lokal testen

```
pip install openpyxl
python trainingszeiten_json.py Trainingszeiten.xlsx --out trainingsplan.json
python seite_bauen.py --daten trainingsplan.json --logo ../logo.png --out index.html
```
