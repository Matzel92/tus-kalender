#!/usr/bin/env python3
"""
Ligatabellen aller TuS-Harpen-Mannschaften von fussball.de holen und als tabellen.json speichern.

Ablauf: Vereinsseite → Liste der Mannschaften (Altersklasse + team-id) → je Mannschaft die
Mannschaftsseite → dort steht die Adresse der aktuellen Tabelle (ajax.team.table …) und der Name
des Wettbewerbs → Tabelle auslesen. Mannschaften ohne Tabelle (F-/G-Jugend, Ü-Teams, Spielfeste)
fallen von selbst heraus. Die Wappen aller Tabellen-Vereine landen wie beim Spielplan im Ordner
wappen/ (zentrale Ablage) und werden mit hochgeladen.

Genutzt von der Homepage (Plugin „TuS Harpen – Werkzeug“): Tabelle unter dem Spielplan jeder Teamseite.

Aufruf:  python tabellen.py --out tabellen.json --wappen wappen
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from fussballde_kalender import BASE, BERLIN, LOGO_ID_RE, wappen_logos_laden, wappen_name

VEREIN_URL = BASE + "/verein/-/id/{club_id}"
TEAM_ID_RE = re.compile(r"/team-id/([A-Z0-9]+)")
TABELLE_RE = re.compile(r"https://www\.fussball\.de/ajax\.team\.table/-/saison/\d+/staffel/[A-Z0-9-]+/team-id/[A-Z0-9]+")
ROEMISCH = {"": 1, "II": 2, "III": 3, "IV": 4, "V": 5}


def text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ") if el else "").replace("​", "").strip()


def zahl(s: str):
    s = s.strip().rstrip(".")
    try:
        return int(s)
    except ValueError:
        return s


def nummer(name: str) -> int:
    """1 = „TuS Harpen“ / JSG …, 2 = „TuS Harpen II“ … (Zusätze wie „o.W.“ werden übergangen)."""
    teile = name.replace("o.W.", "").split()
    return ROEMISCH.get(teile[-1], 1) if teile and teile[-1] in ROEMISCH else 1


def mannschaften(session: requests.Session, club_id: str) -> list[dict]:
    soup = BeautifulSoup(session.get(VEREIN_URL.format(club_id=club_id), timeout=30).text, "html.parser")
    teams, gesehen = [], set()
    for a in soup.select('a[href*="/mannschaft/"]'):
        t = text(a)
        m = re.match(r"^(.+?) - (.+)$", t)
        tid = TEAM_ID_RE.search(a["href"])
        if not m or not tid or tid.group(1) in gesehen:
            continue
        gesehen.add(tid.group(1))
        teams.append({"altersklasse": m.group(1), "name": m.group(2), "team_id": tid.group(1),
                      "nummer": nummer(m.group(2)), "url": a["href"]})
    return teams


def tabelle(session: requests.Session, team: dict) -> dict | None:
    seite = session.get(team["url"], timeout=30).text
    m = TABELLE_RE.search(seite)
    if not m:
        return None
    soup = BeautifulSoup(seite, "html.parser")
    wahl = soup.select_one('select[name="staffel"] option[selected]') or soup.select_one('select[name="staffel"] option')
    liga = re.sub(r"\s+", " ", wahl.get_text()).strip() if wahl else ""
    time.sleep(0.3)
    tsoup = BeautifulSoup(session.get(m.group(0), timeout=30).text, "html.parser")
    zeilen = []
    for tr in tsoup.select("table tbody tr"):
        tds = tr.find_all("td", recursive=False)
        verein = tr.select_one(".column-club")
        if len(tds) < 10 or not verein:
            continue
        link = verein.find("a", href=True)
        tid = TEAM_ID_RE.search(link["href"]) if link else None
        img = verein.find("img")
        logo = LOGO_ID_RE.search(img.get("src", "")) if img else None
        klassen = " ".join(tr.get("class", []))
        zeilen.append({
            "pl": zahl(text(tds[1])),
            "verein": text(verein.select_one(".club-name")) or text(verein),
            "logo": logo.group(1) if logo else "",
            "sp": zahl(text(tds[3])), "g": zahl(text(tds[4])), "u": zahl(text(tds[5])), "v": zahl(text(tds[6])),
            "tore": re.sub(r"\s*:\s*", ":", text(tds[7])), "diff": zahl(text(tds[8])), "pkt": zahl(text(tds[9])),
            "eigen": bool(tid and tid.group(1) == team["team_id"]),
            "zone": "auf" if "promotion" in klassen else ("ab" if ("relegation" in klassen or "demotion" in klassen) else ""),
        })
    if not zeilen:
        return None
    return {**{k: team[k] for k in ("altersklasse", "name", "nummer", "team_id")},
            "liga": liga, "quelle": team["url"], "zeilen": zeilen}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--club-id", default=os.environ.get("FUSSBALLDE_CLUB_ID", "00ES8GN8N4000022VV0AG08LVUPGND5I"))
    ap.add_argument("--out", default="tabellen.json")
    ap.add_argument("--wappen", help="Ordner der Vereinswappen (fehlende werden geladen)")
    a = ap.parse_args()
    session = requests.Session()
    session.headers.update({"User-Agent": "Vereinskalender-Skript (privater Kalender-Export)"})
    try:
        teams = mannschaften(session, a.club_id)
    except requests.RequestException as e:
        print(f"Vereinsseite nicht geladen: {e} – alte Datei bleibt.", file=sys.stderr)
        return 2
    tabellen = []
    for team in teams:
        time.sleep(0.3)
        try:
            t = tabelle(session, team)
        except requests.RequestException as e:
            print(f"{team['altersklasse']} {team['name']}: {e}", file=sys.stderr)
            continue
        print(f"{team['altersklasse']:15} {team['name']:45} {t['liga'] + ' (' + str(len(t['zeilen'])) + ')' if t else '– keine Tabelle'}")
        if t:
            tabellen.append(t)
    if not tabellen:
        print("Keine Tabellen gefunden – alte Datei bleibt.", file=sys.stderr)
        return 1
    if a.wappen:
        wappen_logos_laden({z["logo"] for t in tabellen for z in t["zeilen"] if z["logo"]}, Path(a.wappen))
    for t in tabellen:
        for z in t["zeilen"]:
            z["w"] = wappen_name(z.pop("logo"))
    daten = {"stand": datetime.now(BERLIN).isoformat(timespec="seconds"), "tabellen": tabellen}
    Path(a.out).write_text(json.dumps(daten, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(tabellen)} Tabellen → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
