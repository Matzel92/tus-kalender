#!/usr/bin/env python3
"""
Baut die fertige Trainingsplan-Seite (index.html) aus der Vorlage training.html und trainingsplan.json.

Die Daten werden als Startwert in die Seite eingebettet (sie funktioniert damit auch ohne Nachladen);
auf dem Webspace lädt die Seite trainingsplan.json zusätzlich alle 10 Minuten nach.

Aufruf:  python seite_bauen.py --daten trainingsplan.json --out index.html [--logo logo.png]
"""
import argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vorlage", default="training.html")
    ap.add_argument("--daten", default="trainingsplan.json")
    ap.add_argument("--logo", default="logo.png", help="Pfad/Adresse des Vereinslogos, relativ zur Seite")
    ap.add_argument("--out", default="index.html")
    a = ap.parse_args()
    t = open(a.vorlage, encoding="utf-8").read()
    daten = open(a.daten, encoding="utf-8").read().replace("</", "<\\/")
    t = t.replace("__DATA__", daten).replace("__LOGO__", a.logo)
    kopf, rest = t.split("</style>", 1)
    seite = ('<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
             '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
             '<meta name="description" content="Trainingszeiten aller Mannschaften des TuS Harpen 08/11 – Wochenplan, Mannschaften und Platzbelegung">\n'
             '<link rel="icon" type="image/png" href="favicon.png">\n'
             '<link rel="apple-touch-icon" href="apple-touch-icon.png">\n'
             + kopf + "</style>\n</head>\n<body>\n" + rest.strip() + "\n</body>\n</html>\n")
    open(a.out, "w", encoding="utf-8").write(seite)
    print(f"{a.out} geschrieben ({len(seite) // 1024} KB)")

if __name__ == "__main__":
    main()
