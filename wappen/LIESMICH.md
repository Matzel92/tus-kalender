# Vereinswappen – zentrale Ablage

Alle Wappen, die die Homepage (neu.tus-harpen.de / später www) und die Spiele-Anzeige
(spiele.tus-harpen.de) zeigen, kommen aus diesem Ordner. Der Workflow „Spielplan auf IONOS
aktualisieren“ lädt neue Wappen von fussball.de, checkt sie hier ein und lädt den Ordner nach
`spiele.tus-harpen.de/wappen/` hoch. Andere Quellen gibt es nicht.

- `<ID>.png` – Original von fussball.de (99 × 99 px)
- `<ID>.f2.png` – automatisch freigestellt (Hintergrund durchsichtig); das nutzen die Seiten
- `korrektur/<ID>.png` – **von Hand verbessertes Wappen**. Liegt hier eine Datei, nutzen alle
  Seiten automatisch diese (Dateiname auf dem Webspace `<ID>.f9xxxxx.png`, xxxxx = Prüfsumme).

Wappen korrigieren: Original `<ID>.png` herunterladen, bearbeiten (PNG, durchsichtiger Hintergrund),
als `korrektur/<ID>.png` hochladen. Nach wenigen Minuten ist es überall sichtbar
(Homepage spätestens nach 10 Minuten Zwischenspeicher). Die ID eines Vereins steht in
`spiele.json` (Felder `hw` = Heim, `aw` = Gast).
