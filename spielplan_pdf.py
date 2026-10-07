#!/usr/bin/env python3
"""
Erzeugt aus der Kalenderdatei (tus-harpen.ics) eine druckfertige PDF-Liste
aller Spiele der nächsten Monate, nach Tagen gruppiert.

Benötigt:  pip install reportlab
Logo:      logo.png (PNG oder JPG) neben das Skript legen, oder --logo angeben
Beispiel:  python spielplan_pdf.py tus-harpen.ics --out spielplan.pdf --months 3
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)
import os

BERLIN = ZoneInfo("Europe/Berlin")
FONT, FONT_BOLD, FONT_SIZE = "Helvetica", "Helvetica-Bold", 8
PAD = 4  # Innenabstand links/rechts in Punkt
WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

# Farben
DUNKEL = colors.HexColor("#1F2A44")
HELL = colors.HexColor("#E9EDF4")
LINIE = colors.HexColor("#C9D1DE")
GRAU = colors.HexColor("#8A8F98")


@dataclass
class Spiel:
    tag: date
    zeit: str          # "15:00" oder "" (offen)
    mannschaft: str
    wettbewerb: str
    heim: str
    gast: str
    ort: str
    abgesetzt: bool


# --------------------------------------------------------------------------
# ICS einlesen (genau das Format, das fussballde_kalender.py schreibt)
# --------------------------------------------------------------------------

def ics_unescape(s: str) -> str:
    return (s.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",")
             .replace("\\;", ";").replace("\\\\", "\\"))


def read_ics(path: str) -> list[dict[str, str]]:
    raw = open(path, encoding="utf-8").read().replace("\r\n", "\n")
    raw = re.sub(r"\n[ \t]", "", raw)  # gefaltete Zeilen zusammenfügen
    events, cur = [], None
    for line in raw.split("\n"):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, val = line.split(":", 1)
            name, _, params = key.partition(";")
            cur[name] = val
            if params:
                cur[name + "_PARAMS"] = params
    return events


def to_spiel(ev: dict[str, str]) -> Spiel | None:
    start = ev.get("DTSTART", "")
    if not start:
        return None
    if "VALUE=DATE" in ev.get("DTSTART_PARAMS", "") or len(start) == 8:
        tag = datetime.strptime(start[:8], "%Y%m%d").date()
        zeit = ""
    else:
        dt = datetime.strptime(start, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(BERLIN)
        tag, zeit = dt.date(), dt.strftime("%H:%M")

    summary = ics_unescape(ev.get("SUMMARY", ""))
    abgesetzt = ev.get("STATUS") == "CANCELLED" or summary.startswith("ABGESETZT")
    summary = re.sub(r"^ABGESETZT:\s*", "", summary)
    summary = re.sub(r"^\[[^\]]*\]\s*", "", summary)  # [Mannschaft] entfernen
    heim, _, gast = summary.partition(" – ")

    beschr = ics_unescape(ev.get("DESCRIPTION", "")).split("\n")
    label = beschr[0] if beschr and "|" in beschr[0] else ""
    teile = [t.strip() for t in label.split("|")] if label else []
    mannschaft = teile[0] if teile else ""
    wettbewerb = " · ".join(teile[1:]) if len(teile) > 1 else ""
    if "freundschaft" in wettbewerb.lower():
        wettbewerb = "Freundschaftsspiel"  # Kreis-, Verbands-, Hallen-… einheitlich

    ort = ics_unescape(ev.get("LOCATION", "")).replace(" | ", ", ")
    return Spiel(tag, zeit, mannschaft, wettbewerb, heim.strip(), gast.strip(), ort, abgesetzt)


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    tage = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, tage))


def fmt_datum(d: date) -> str:
    return f"{WOCHENTAGE[d.weekday()]}, {d.day}. {MONATE[d.month - 1]} {d.year}"


# --------------------------------------------------------------------------
# PDF bauen
# --------------------------------------------------------------------------

def build_pdf(spiele: list[Spiel], out: str, titel: str, von: date, bis: date, verein: str,
              logo: str | None = None) -> None:
    stand = datetime.now(BERLIN)
    seite_b, seite_h = landscape(A4)

    s_titel = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=DUNKEL)
    s_unter = ParagraphStyle("u", fontName="Helvetica", fontSize=10, leading=13, textColor=GRAU)
    s_zelle = ParagraphStyle("z", fontName=FONT, fontSize=FONT_SIZE, leading=10, alignment=TA_LEFT)
    s_kopf = ParagraphStyle("k", parent=s_zelle, fontName="Helvetica-Bold", textColor=colors.white)
    s_tag = ParagraphStyle("d", parent=s_zelle, fontName="Helvetica-Bold", fontSize=9.5, textColor=DUNKEL)

    def kuerzen(text: str, breite: float, bold: bool) -> str:
        """Text so kürzen, dass er einzeilig in die Spalte passt."""
        font = FONT_BOLD if bold else FONT
        platz = breite - 2 * PAD - 1
        if stringWidth(text, font, FONT_SIZE) <= platz:
            return text
        while text and stringWidth(text + "…", font, FONT_SIZE) > platz:
            text = text[:-1]
        return text.rstrip(" ,/-") + "…"

    def zelle(text: str, breite: float, bold: bool = False, aus: bool = False) -> Paragraph:
        t = escape(kuerzen(text, breite, bold))
        if bold:
            t = f"<b>{t}</b>"
        if aus:
            t = f'<strike><font color="#8A8F98">{t}</font></strike>'
        return Paragraph(t, s_zelle)

    def ort_kurz(ort: str, breite: float) -> str:
        """Spielort einzeilig: erst komplett, sonst Platz + PLZ/Ort, sonst gekürzt."""
        platz = breite - 2 * PAD - 1
        if stringWidth(ort, FONT, FONT_SIZE) <= platz:
            return ort
        teile = [t.strip() for t in ort.split(",") if t.strip()]
        if len(teile) >= 3:
            kurz = f"{teile[0]}, {teile[-1]}"
            if stringWidth(kurz, FONT, FONT_SIZE) <= platz:
                return kurz
        return ort

    kopf = [Paragraph(h, s_kopf) for h in
            ("Zeit", "Mannschaft", "Heim", "Gast", "Wettbewerb", "Spielort")]
    breiten = [12 * mm, 21 * mm, 55 * mm, 55 * mm, 27 * mm, 111 * mm]  # = 281 mm

    daten = [kopf]
    stil = [
        ("BACKGROUND", (0, 0), (-1, 0), DUNKEL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), PAD),
        ("RIGHTPADDING", (0, 0), (-1, -1), PAD),
    ]

    letzter_tag = None
    for sp in spiele:
        if sp.tag != letzter_tag:
            daten.append([Paragraph(fmt_datum(sp.tag), s_tag), "", "", "", "", ""])
            r = len(daten) - 1
            stil += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), HELL),
                     ("TOPPADDING", (0, r), (-1, r), 5)]
            letzter_tag = sp.tag
        heim_eigen = verein.lower() in sp.heim.lower()
        gast_eigen = verein.lower() in sp.gast.lower()
        zeit = sp.zeit or "offen"
        if sp.abgesetzt:
            zeit = "abges."
        daten.append([
            zelle(zeit, breiten[0], aus=sp.abgesetzt),
            zelle(sp.mannschaft, breiten[1], aus=sp.abgesetzt),
            zelle(sp.heim, breiten[2], bold=heim_eigen and not sp.abgesetzt, aus=sp.abgesetzt),
            zelle(sp.gast, breiten[3], bold=gast_eigen and not sp.abgesetzt, aus=sp.abgesetzt),
            zelle(sp.wettbewerb, breiten[4], aus=sp.abgesetzt),
            zelle(ort_kurz(sp.ort, breiten[5]), breiten[5], aus=sp.abgesetzt),
        ])
        r = len(daten) - 1
        stil.append(("LINEBELOW", (0, r), (-1, r), 0.4, LINIE))

    if len(daten) == 1:
        daten.append([Paragraph("Im gewählten Zeitraum sind keine Spiele angesetzt.", s_zelle), "", "", "", "", ""])
        stil.append(("SPAN", (0, 1), (-1, 1)))

    tabelle = Table(daten, colWidths=breiten, repeatRows=1)
    tabelle.setStyle(TableStyle(stil))

    def fuss(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GRAU)
        canvas.drawString(8 * mm, 7 * mm,
                          f"Quelle: fussball.de · Stand: {stand:%d.%m.%Y, %H:%M} Uhr · "
                          "Kurzfristige Änderungen möglich")
        canvas.drawRightString(seite_b - 8 * mm, 7 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=8 * mm, rightMargin=8 * mm,
                            topMargin=10 * mm, bottomMargin=13 * mm, title=titel, author=verein)
    titelblock = [
        Paragraph(escape(titel), s_titel),
        Spacer(1, 2),
        Paragraph(f"Alle Spiele vom {von:%d.%m.%Y} bis {bis:%d.%m.%Y} · "
                  f"{sum(1 for s in spiele if not s.abgesetzt)} Spiele · "
                  f"Spiele des Vereins sind fett markiert", s_unter),
    ]
    nutzbreite = seite_b - 16 * mm
    logo_bild = None
    if logo and os.path.exists(logo):
        try:
            iw, ih = ImageReader(logo).getSize()
            h = 20 * mm
            w = min(h * iw / ih, 50 * mm)
            h = w * ih / iw
            logo_bild = Image(logo, width=w, height=h)
        except Exception as e:
            print(f"Logo konnte nicht geladen werden ({e}) – PDF wird ohne Logo erstellt.", file=sys.stderr)
    elif logo:
        print(f"Logo '{logo}' nicht gefunden – PDF wird ohne Logo erstellt.", file=sys.stderr)

    if logo_bild:
        kopfbereich = Table([[titelblock, logo_bild]],
                            colWidths=[nutzbreite - logo_bild.drawWidth, logo_bild.drawWidth])
        kopfbereich.setStyle(TableStyle([
            ("VALIGN", (0, 0), (0, 0), "BOTTOM"), ("VALIGN", (1, 0), (1, 0), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story = [kopfbereich]
    else:
        story = list(titelblock)
    story += [Spacer(1, 6), tabelle]
    doc.build(story, onFirstPage=fuss, onLaterPages=fuss)


def main() -> int:
    p = argparse.ArgumentParser(description="Spielplan-PDF aus .ics erzeugen")
    p.add_argument("ics", help="Kalenderdatei, z. B. tus-harpen.ics")
    p.add_argument("--out", default="spielplan.pdf", help="Ziel-PDF (Standard: spielplan.pdf)")
    p.add_argument("--months", type=int, default=3, help="Zeitraum in Monaten ab heute (Standard 3)")
    p.add_argument("--titel", default="TuS Bochum-Harpen – Spielplan")
    p.add_argument("--verein", default="Harpen", help="Namensteil zum Hervorheben der eigenen Teams")
    p.add_argument("--team", action="append", help="Nur bestimmte Mannschaften (mehrfach möglich)")
    p.add_argument("--logo", default="logo.png", help="Vereinslogo (PNG/JPG), Standard: logo.png")
    args = p.parse_args()

    von = datetime.now(BERLIN).date()
    bis = add_months(von, args.months)
    spiele = [s for s in (to_spiel(e) for e in read_ics(args.ics)) if s and von <= s.tag <= bis]
    if args.team:
        wanted = [t.lower() for t in args.team]
        spiele = [s for s in spiele if any(t in s.mannschaft.lower() for t in wanted)]
    spiele.sort(key=lambda s: (s.tag, s.zeit or "99:99", s.mannschaft))

    build_pdf(spiele, args.out, args.titel, von, bis, args.verein, args.logo)
    print(f"{len(spiele)} Spiele vom {von:%d.%m.%Y} bis {bis:%d.%m.%Y} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
