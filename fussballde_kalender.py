#!/usr/bin/env python3
"""
fussball.de  ->  iCalendar (.ics)

Liest den Vereinsspielplan eines Vereins auf fussball.de aus (alle Mannschaften)
und schreibt ihn als abonnierbaren Kalender in eine .ics-Datei.

Benötigt:  pip install requests beautifulsoup4 fonttools
Python:    3.9 oder neuer

Beispiele:
  # einmal ausführen (z. B. per cron / GitHub Actions)
  python fussballde_kalender.py --club-id DEINE_VEREINS_ID --out tus-harpen.ics

  # dauerhaft laufen lassen, alle 15 Minuten aktualisieren
  python fussballde_kalender.py --club-id DEINE_VEREINS_ID --out tus-harpen.ics --interval 900

  # nur bestimmte Mannschaften (Text muss in "Mannschaft | Wettbewerb" vorkommen)
  python fussballde_kalender.py --club-id ... --team Herren --team "A-Junioren"

Die Vereins-ID findest du auf fussball.de: Verein suchen, Vereinsseite öffnen,
die URL endet auf  .../-/id/XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX  -> das ist die ID.

Hinweis: fussball.de bietet keine offizielle API. Wenn fussball.de das Layout
ändert, muss der Parser ggf. angepasst werden. Mit --debug-html wird die
abgerufene Seite gespeichert, damit man den Fehler nachvollziehen kann.
Datum und Uhrzeit sind auf fussball.de verschleiert; das Skript lädt dazu die
passende Schriftart und entschlüsselt sie (dafür wird fonttools benötigt).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BERLIN = ZoneInfo("Europe/Berlin")
BASE = "https://www.fussball.de"
MATCHPLAN_URL = (
    BASE
    + "/ajax.club.matchplan/-/id/{club_id}/mime-type/HTML/mode/PRINT"
    "/show-filter/false/max/{max}/datum-von/{von}/datum-bis/{bis}"
    "/show-venues/checked/offset/{offset}"
)
PAGE_SIZE = 100
MAX_PAGES = 10
WINDOW_DAYS = 14  # Zeitraum pro Abruf in Tagen
MIN_INTERVAL = 60  # Sekunden; kürzer wird nicht zugelassen

DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
GAME_ID_RE = re.compile(r"/-/spiel/([A-Za-z0-9]+)")
CANCEL_WORDS = ("abgesetzt", "absetzung", "ausfall", "abgesagt", "annulliert")


@dataclass
class Match:
    uid: str
    day: date
    kickoff: datetime | None  # None = Uhrzeit unbekannt -> ganztägig
    home: str
    away: str
    label: str = ""
    location: str = ""
    url: str = ""
    status_note: str = ""
    marker: bool = False  # Platzhalter am alten Termin eines verlegten Spiels

    @property
    def cancelled(self) -> bool:
        return any(w in self.status_note.lower() for w in CANCEL_WORDS)



# --------------------------------------------------------------------------
# Entschlüsselung der verschleierten Texte
# --------------------------------------------------------------------------
# fussball.de ersetzt Datum, Uhrzeit und Ergebnisse durch Zeichen aus dem
# "Private Use"-Bereich von Unicode und liefert eine Schriftart mit, die diese
# Zeichen als die echten Ziffern/Buchstaben darstellt. Jede Kennung in
# data-obfuscation="..." hat ihre eigene Schriftart. Wir laden sie und lesen
# aus ihr ab, welches Zeichen welchem echten Zeichen entspricht.

FONT_URLS = [
    BASE + "/export.fontface/-/format/woff/id/{key}/type/font",
    BASE + "/export.fontface/-/format/ttf/id/{key}/type/font",
    BASE + "/export.fontface/-/id/{key}/type/font/format/woff",
]
CSS_URL = BASE + "/export.fontface/-/format/css/id/{key}/type/font"

GLYPH_FALLBACK = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "period": ".", "colon": ":", "comma": ",", "hyphen": "-", "minus": "-",
    "space": " ", "slash": "/", "bar": "|", "asterisk": "*",
    "adieresis": "ä", "odieresis": "ö", "udieresis": "ü",
    "Adieresis": "Ä", "Odieresis": "Ö", "Udieresis": "Ü", "germandbls": "ß",
}


class Deobfuscator:
    def __init__(self, session: requests.Session):
        self.session = session
        self.maps: dict[str, dict[int, str]] = {}

    @staticmethod
    def _glyph_char(name: str) -> str | None:
        base = name.split(".")[0]
        if base in GLYPH_FALLBACK:
            return GLYPH_FALLBACK[base]
        if len(base) == 1:
            return base
        try:
            from fontTools import agl
            u = agl.toUnicode(base)
            return u if u else None
        except Exception:
            return None

    def _load_font_bytes(self, key: str) -> bytes:
        tried = []
        for tpl in FONT_URLS:
            url = tpl.format(key=key)
            tried.append(url)
            try:
                r = self.session.get(url, timeout=30)
                if r.ok and len(r.content) > 100 and not r.content.lstrip().startswith(b"<"):
                    return r.content
            except requests.RequestException:
                pass
        # Fallback: CSS laden und die Schrift-URL daraus lesen
        try:
            r = self.session.get(CSS_URL.format(key=key), timeout=30)
            if r.ok:
                for u in re.findall(r"url\((['\"]?)([^'\")]+)\1\)", r.text):
                    url = u[1]
                    if url.startswith("//"):
                        url = "https:" + url
                    elif url.startswith("/"):
                        url = BASE + url
                    tried.append(url)
                    if url.endswith(".eot") or "format/eot" in url:
                        continue
                    fr = self.session.get(url, timeout=30)
                    if fr.ok and len(fr.content) > 100:
                        return fr.content
        except requests.RequestException:
            pass
        raise RuntimeError("Schriftart für Kennung '%s' nicht ladbar. Versucht:\n  %s"
                           % (key, "\n  ".join(tried)))

    def mapping(self, key: str) -> dict[int, str]:
        if key in self.maps:
            return self.maps[key]
        try:
            from fontTools.ttLib import TTFont
        except ImportError:
            raise RuntimeError("Bitte zuerst installieren:  pip install fonttools")
        import io
        data = self._load_font_bytes(key)
        font = TTFont(io.BytesIO(data))
        cmap = font.getBestCmap() or {}
        mp = {}
        for cp, gname in cmap.items():
            ch = self._glyph_char(gname)
            if ch is not None:
                mp[cp] = ch
        if not mp:
            raise RuntimeError("Schriftart für '%s' geladen, aber keine Zeichen erkannt "
                               "(Glyphennamen: %s ...)" % (key, list(cmap.values())[:10]))
        self.maps[key] = mp
        return mp

    def decode(self, key: str, text: str) -> str:
        mp = self.mapping(key)
        return "".join(mp.get(ord(c), c) for c in text)

    def apply(self, soup) -> None:
        """Alle verschleierten Stellen im HTML durch Klartext ersetzen."""
        for span in soup.select("[data-obfuscation]"):
            key = span.get("data-obfuscation")
            txt = span.get_text()
            if key and txt:
                span.string = self.decode(key, txt)

# --------------------------------------------------------------------------
# Abrufen
# --------------------------------------------------------------------------

def fetch_page(session: requests.Session, club_id: str, von: date, bis: date, offset: int) -> str:
    url = MATCHPLAN_URL.format(
        club_id=club_id,
        max=PAGE_SIZE,
        von=von.isoformat(),
        bis=bis.isoformat(),
        offset=offset,
    )
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def fetch_matches(club_id: str, von: date, bis: date, debug_html: Path | None) -> list[Match]:
    """Spielplan abschnittsweise abrufen.

    fussball.de liefert pro Abruf höchstens PAGE_SIZE Zeilen (inkl. "spielfrei").
    Damit nichts abgeschnitten wird, wird der Zeitraum in kurze Fenster
    zerlegt; ist ein Fenster trotzdem voll, wird darin weitergeblättert.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Vereinskalender-Skript (privater Kalender-Export)",
        "Accept-Language": "de-DE,de;q=0.9",
    })

    deob = Deobfuscator(session)
    found: dict[str, Match] = {}
    req_no = 0
    win_start = von
    while win_start <= bis:
        win_end = min(win_start + timedelta(days=WINDOW_DAYS - 1), bis)
        for page in range(MAX_PAGES):
            if req_no:
                time.sleep(1)  # höflich bleiben
            html = fetch_page(session, club_id, win_start, win_end, page * PAGE_SIZE)
            if debug_html:
                stem = f"{debug_html.stem}_{req_no}"
                debug_html.with_name(stem + (debug_html.suffix or ".html")).write_text(html, encoding="utf-8")
            req_no += 1

            page_matches = parse_matchplan(html, deob)
            if debug_html:
                soup = BeautifulSoup(html, "html.parser")
                deob.apply(soup)
                debug_html.with_name(f"{stem}_klartext{debug_html.suffix or '.html'}").write_text(
                    str(soup), encoding="utf-8")

            new = 0
            for m in page_matches:
                if m.uid not in found:
                    found[m.uid] = m
                    new += 1
                elif found[m.uid].marker and not m.marker:
                    found[m.uid] = m  # Platzhalter durch echten Eintrag ersetzen
                    new += 1
            raw_rows = html.count("row-competition")  # zählt auch "spielfrei"-Zeilen
            if raw_rows < PAGE_SIZE or new == 0:
                break
        win_start = win_end + timedelta(days=1)

    return sorted(found.values(), key=lambda m: (m.kickoff or datetime.combine(m.day, datetime.min.time(), BERLIN)))


# --------------------------------------------------------------------------
# Parsen
# --------------------------------------------------------------------------

def clean(text: str) -> str:
    return " ".join(text.replace("\u200b", "").replace("\xa0", " ").split())


def parse_date(text: str) -> date | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


RELATIVE_DAYS = {"vorgestern": -2, "gestern": -1, "heute": 0, "morgen": 1, "übermorgen": 2}


def parse_relative_date(text: str) -> date | None:
    """fussball.de schreibt bei nahen Spielen "Heute", "Morgen" o. Ä. statt des Datums."""
    low = text.lower()
    heute = datetime.now(BERLIN).date()
    # längere Wörter zuerst prüfen ("übermorgen" enthält "morgen")
    for wort, diff in sorted(RELATIVE_DAYS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![a-zäöüß]){wort}(?![a-zäöüß])", low):
            return heute + timedelta(days=diff)
    return None


def parse_time(text: str) -> tuple[int, int] | None:
    m = TIME_RE.search(text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h < 24 and 0 <= mi < 60:
        return h, mi
    return None


def label_from_row(tr) -> str:
    """Mannschaft und Wettbewerb aus einer Kopfzeile ziehen."""
    cells = [clean(td.get_text(" ")) for td in tr.select(".column-team, .column-competition")]
    cells = [c for c in cells if c]
    if cells:
        return " | ".join(cells)
    # Fallback: "Sonntag, 12.10.2025 - 15:00 Uhr | Herren | Kreisliga A"
    parts = [clean(p) for p in tr.get_text(" ").split("|")]
    return " | ".join(p for p in parts[1:] if p)


def parse_matchplan(html: str, deob: "Deobfuscator | None" = None) -> list[Match]:
    soup = BeautifulSoup(html, "html.parser")
    if deob is not None:
        deob.apply(soup)
    matches: list[Match] = []
    cur_day: date | None = None
    cur_time: tuple[int, int] | None = None
    cur_label = ""
    last: Match | None = None

    for tr in soup.find_all("tr"):
        classes = tr.get("class") or []
        text = clean(tr.get_text(" "))

        # Kopfzeilen mit Datum / Uhrzeit / Mannschaft / Wettbewerb
        if "row-headline" in classes or "row-competition" in classes:
            d = parse_date(text) or parse_relative_date(text)
            if d:
                cur_day = d
                cur_time = parse_time(text)
            elif "row-headline" in classes:
                # Kein Datum erkennbar: lieber auslassen als einem falschen Tag zuordnen
                cur_day, cur_time = None, None
            lbl = label_from_row(tr)
            if lbl:
                cur_label = lbl
            continue

        # Spielort-Zeile gehört zum vorherigen Spiel
        if "row-venue" in classes:
            if last is not None and text:
                mv = re.search(r"Spielst(?:ä|ae)tte:\s*(.*)", text)
                last.location = clean(mv.group(1)) if mv else ("" if "Schiedsrichter" in text else text)
                vv = re.search(r"verlegt vom:?\s*(\d{1,2}\.\d{1,2}\.\d{2,4}(?:\s+\d{1,2}:\d{2})?)", text)
                if vv:
                    hinweis = f"verlegt vom {vv.group(1)}"
                    last.status_note = f"{last.status_note} · {hinweis}" if last.status_note else hinweis
            continue

        # Spielzeile: zwei Vereinsnamen
        names = [clean(n.get_text(" ")) for n in tr.select(".club-name")]
        if len(names) < 2 or cur_day is None:
            continue

        home, away = names[0], names[1]
        link = tr.find("a", href=GAME_ID_RE)
        url = link["href"] if link else ""
        if url.startswith("/"):
            url = BASE + url
        gid = GAME_ID_RE.search(url).group(1) if url else None

        score_cell = tr.select_one(".column-score")
        status_note = ""
        day, tme, marker = cur_day, cur_time, False
        if score_cell:
            st = clean(score_cell.get_text(" "))
            info = score_cell.select_one(".info-text")
            info_txt = clean(info.get_text(" ")) if info else ""
            new_day = parse_date(info_txt)
            if new_day:
                # Verlegtes Spiel: fussball.de zeigt am ALTEN Termin einen Platzhalter
                # mit dem NEUEN Datum. Wir übernehmen das neue Datum; der eigentliche
                # Eintrag am neuen Termin (mit Spielort) ersetzt ihn später.
                day, tme, marker = new_day, parse_time(info_txt), True
            elif re.search(r"[A-Za-zÄÖÜäöüß]{4,}", st):
                # Nur echte Wörter übernehmen (Ergebnisse sind verschleiert)
                status_note = st

        kickoff = None
        if tme:
            kickoff = datetime(day.year, day.month, day.day, *tme, tzinfo=BERLIN)

        uid_src = gid or f"{day.isoformat()}|{home}|{away}|{cur_label}"
        uid = hashlib.sha1(uid_src.encode("utf-8")).hexdigest()[:24] + "@fussballde-kalender"

        last = Match(
            uid=uid, day=day, kickoff=kickoff, home=home, away=away,
            label=cur_label, url=url, status_note=status_note, marker=marker,
        )
        matches.append(last)

    return matches


# --------------------------------------------------------------------------
# iCalendar schreiben
# --------------------------------------------------------------------------

def ics_escape(s: str) -> str:
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
             .replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line: str) -> str:
    """Zeilen nach RFC 5545 auf 75 Oktette umbrechen."""
    out, buf = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(buf) + len(b) > (75 if not out else 74):
            out.append(buf.decode("utf-8"))
            buf = b""
        buf += b
    out.append(buf.decode("utf-8"))
    return "\r\n ".join(out)


def utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(matches: list[Match], cal_name: str, duration_min: int, stamp: datetime) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//fussballde-kalender//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape(cal_name)}",
        "X-WR-TIMEZONE:Europe/Berlin",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for m in matches:
        team = m.label.split("|")[0].strip()  # z. B. "B-Junioren" aus "B-Junioren | Kreispokal"
        summary = f"{m.home} – {m.away}"
        if team:
            summary = f"[{team}] {summary}"
        if m.cancelled:
            summary = "ABGESETZT: " + summary
        desc_parts = [p for p in (m.label, m.status_note, m.url) if p]

        lines += ["BEGIN:VEVENT", f"UID:{m.uid}", f"DTSTAMP:{utc(stamp)}"]
        if m.kickoff:
            lines.append(f"DTSTART:{utc(m.kickoff)}")
            lines.append(f"DTEND:{utc(m.kickoff + timedelta(minutes=duration_min))}")
        else:
            lines.append(f"DTSTART;VALUE=DATE:{m.day.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{(m.day + timedelta(days=1)).strftime('%Y%m%d')}")
        lines.append(f"SUMMARY:{ics_escape(summary)}")
        if desc_parts:
            lines.append(f"DESCRIPTION:{ics_escape(chr(10).join(desc_parts))}")
        if m.location:
            lines.append(f"LOCATION:{ics_escape(m.location)}")
        if m.url:
            lines.append(f"URL:{m.url}")
        lines.append(f"STATUS:{'CANCELLED' if m.cancelled else 'CONFIRMED'}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def without_stamps(ics: str) -> str:
    return "\n".join(l for l in ics.splitlines() if not l.startswith("DTSTAMP:"))


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if without_stamps(old) == without_stamps(content):
            return False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="")
    os.replace(tmp, path)  # atomar: Abonnenten sehen nie eine halbe Datei
    return True


# --------------------------------------------------------------------------
# Ablauf
# --------------------------------------------------------------------------

def run_once(args) -> int:
    today = date.today()
    von = today - timedelta(days=args.days_back)
    bis = today + timedelta(days=args.days_ahead)
    try:
        matches = fetch_matches(args.club_id, von, bis, Path(args.debug_html) if args.debug_html else None)
    except requests.RequestException as e:
        print(f"[{datetime.now():%H:%M:%S}] Abruf fehlgeschlagen: {e} – alte Datei bleibt erhalten.", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"[{datetime.now():%H:%M:%S}] Entschlüsselung fehlgeschlagen: {e}\n– alte Datei bleibt erhalten.", file=sys.stderr)
        return 3

    if args.team:
        wanted = [t.lower() for t in args.team]
        matches = [m for m in matches if any(t in m.label.lower() for t in wanted)]

    if not matches:
        # Leeres Ergebnis ist meist ein Layout-/Sperrproblem -> nichts überschreiben
        print(f"[{datetime.now():%H:%M:%S}] Keine Spiele gefunden – alte Datei bleibt erhalten. "
              "Tipp: mit --debug-html seite.html die Rohdaten prüfen.", file=sys.stderr)
        return 1

    ics = build_ics(matches, args.name, args.duration, datetime.now(timezone.utc))
    changed = write_if_changed(Path(args.out), ics)
    print(f"[{datetime.now():%H:%M:%S}] {len(matches)} Spiele, "
          f"{'Datei aktualisiert' if changed else 'keine Änderung'}: {args.out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="fussball.de Vereinsspielplan als .ics exportieren")
    p.add_argument("--club-id", default=os.environ.get("FUSSBALLDE_CLUB_ID", "00ES8GN8N4000022VV0AG08LVUPGND5I"),
                   help="Vereins-ID von fussball.de (oder Umgebungsvariable FUSSBALLDE_CLUB_ID)")
    p.add_argument("--out", default="spielplan.ics", help="Zieldatei (Standard: spielplan.ics)")
    p.add_argument("--name", default="TuS Harpen 08/11 – Spielplan", help="Kalendername")
    p.add_argument("--team", action="append", help="Nur Spiele, deren Mannschaft/Wettbewerb diesen Text enthält (mehrfach möglich)")
    p.add_argument("--days-back", type=int, default=30, help="Wie viele Tage zurück (Standard 30)")
    p.add_argument("--days-ahead", type=int, default=240, help="Wie viele Tage voraus (Standard 240)")
    p.add_argument("--duration", type=int, default=120, help="Termindauer in Minuten (Standard 120)")
    p.add_argument("--interval", type=int, default=0,
                   help="Sekunden zwischen zwei Abrufen; 0 = nur einmal ausführen (Minimum 60)")
    p.add_argument("--debug-html", help="Rohes HTML zusätzlich in diese Datei speichern")
    args = p.parse_args()

    if not args.club_id:
        p.error("Bitte --club-id angeben (Vereins-ID aus der fussball.de-URL).")
    # Mitkopierte URL-Reste entfernen (z. B. "#!/" am Ende oder die ganze URL)
    m = re.search(r"[A-Z0-9]{32}", args.club_id.upper())
    if not m:
        p.error(f"'{args.club_id}' sieht nicht wie eine fussball.de-Vereins-ID aus (32 Zeichen, A-Z und 0-9).")
    args.club_id = m.group(0)

    if args.interval <= 0:
        return run_once(args)

    interval = max(args.interval, MIN_INTERVAL)
    if interval < 600:
        print("Hinweis: Sehr kurze Intervalle können zu einer Sperre durch fussball.de führen. "
              "15–60 Minuten sind in der Praxis ausreichend.", file=sys.stderr)
    while True:
        run_once(args)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
