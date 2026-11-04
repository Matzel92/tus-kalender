#!/usr/bin/env python3
"""
Trainingszeiten.xlsx  ->  trainingsplan.json  (für training.html)

Liest die Pflegedatei:
  Blatt "Eingabe":       je Mannschaft eine Zeile; je Wochentag von/bis/Ort, dazu "Zusatz 1/2" (Tag, von, bis, Ort, nur im)
  Blatt "Mannschaften":  Name, Kurzname, Farbe, Schriftfarbe (Reihenfolge = Anzeige-Reihenfolge)
  Blatt "Pläne":         Plan (Sommer/Winter), Überschrift, gültig von, gültig bis (mehrere Zeilen je Plan möglich)
Mannschaften, die zur selben Zeit auf demselben Platzbereich trainieren, werden zu einer Einheit zusammengefasst.

Benötigt: pip install openpyxl
Aufruf:   python trainingszeiten_json.py Trainingszeiten.xlsx --out trainingsplan.json
"""
import argparse, json, re, sys
from datetime import datetime, time, date
import openpyxl

FELDER = ["Kleinfeld", "VL", "VR", "HL", "HR", "Laufbahn"]
KT = {"Mo": 1, "Di": 2, "Mi": 3, "Do": 4, "Fr": 5, "Sa": 6, "So": 7}
TAGNAME = {"Montag": 1, "Dienstag": 2, "Mittwoch": 3, "Donnerstag": 4, "Freitag": 5, "Samstag": 6, "Sonntag": 7}

def hhmm(v):
    if v is None or v == "": return None
    if isinstance(v, datetime): v = v.time()
    if isinstance(v, time): return "%02d:%02d" % (v.hour, v.minute)
    if isinstance(v, (int, float)):  # Excel-Bruchteil eines Tages
        m = round(float(v) * 1440); return "%02d:%02d" % (m // 60 % 24, m % 60)
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})", str(v))
    return "%02d:%02d" % (int(m.group(1)), int(m.group(2))) if m else None

def felder(ort):
    s = str(ort or "")
    found = [f for f in FELDER if re.search(r"\b" + f + r"\b", s, re.I)]
    if re.search(r"\bganz", s, re.I) and not found: found = ["VL", "VR", "HL", "HR"]
    return found

def d(v):
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", str(v or ""))
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("xlsx"); ap.add_argument("--out", default="trainingsplan.json")
    a = ap.parse_args()
    wb = openpyxl.load_workbook(a.xlsx, data_only=True)
    # Mannschaften
    wm = wb["Mannschaften"]; teams = []
    for r in range(2, wm.max_row + 1):
        n = wm.cell(r, 1).value
        if not n or not wm.cell(r, 2).value: continue   # nur Zeilen mit Kurzname (Hinweistexte überspringen)
        farbe = (str(wm.cell(r, 3).value or "BFBFBF").strip().lstrip("#") or "BFBFBF").upper()
        text = (str(wm.cell(r, 4).value or "000000").strip().lstrip("#") or "000000").upper()
        teams.append(dict(name=str(n).strip(), kurz=str(wm.cell(r, 2).value or n).strip(), farbe="#" + farbe, text="#" + text))
    tinfo = {t["name"]: t for t in teams}
    # Pläne
    wp = wb["Pläne"]; plaene = {}
    for r in range(2, wp.max_row + 1):
        p = wp.cell(r, 1).value
        if not p or not d(wp.cell(r, 3).value): continue
        e = plaene.setdefault(str(p).strip(), dict(titel=str(wp.cell(r, 2).value or "").strip(), gueltig=[]))
        e["gueltig"].append([d(wp.cell(r, 3).value).isoformat(), d(wp.cell(r, 4).value).isoformat()])
    # Eingabe: Kopfzeilen finden (Zeile mit "Mannschaft", darunter von/bis/Ort)
    we = wb["Eingabe"]
    hr = next(r for r in range(1, 15) if str(we.cell(r, 1).value or "").strip() == "Mannschaft")
    tage, zus = [], []
    c = 2
    while c <= we.max_column:
        top = we.cell(hr, c).value
        if top and str(top).strip() in TAGNAME: tage.append((TAGNAME[str(top).strip()], c)); c += 3; continue
        if top and str(top).strip().lower().startswith("zusatz"): zus.append(c); c += 5; continue
        c += 1
    roh = []   # (plan|None, team, tag, von, bis, felder)
    fehler = []
    for r in range(hr + 2, we.max_row + 1):
        team = we.cell(r, 1).value
        if not team: continue
        team = str(team).strip()
        for tag, c in tage:
            v, b, o = hhmm(we.cell(r, c).value), hhmm(we.cell(r, c + 1).value), we.cell(r, c + 2).value
            if v or b or o:
                if not (v and b and felder(o)): fehler.append(f"{team}: Tag {tag} unvollständig"); continue
                roh.append((None, team, tag, v, b, felder(o)))
        for c in zus:
            tg, v, b, o, p = we.cell(r, c).value, hhmm(we.cell(r, c + 1).value), hhmm(we.cell(r, c + 2).value), we.cell(r, c + 3).value, we.cell(r, c + 4).value
            if tg or v or b or o:
                if not (str(tg).strip()[:2] in KT and v and b and felder(o)): fehler.append(f"{team}: Zusatz unvollständig"); continue
                roh.append((str(p).strip() if p else None, team, KT[str(tg).strip()[:2]], v, b, felder(o)))
    order = {t["name"]: i for i, t in enumerate(teams)}
    out = []
    for pname, pinfo in plaene.items():
        grp = {}
        for (p, team, tag, v, b, f) in roh:
            if p and p != pname: continue
            grp.setdefault((tag, v, b, tuple(f)), []).append(team)
        einheiten = []
        for (tag, v, b, f), mitgl in grp.items():
            mitgl = sorted(set(mitgl), key=lambda n: order.get(n, 999))
            ti = tinfo.get(mitgl[0], dict(farbe="#BFBFBF", text="#000000", kurz=mitgl[0]))
            name, kurz = " & ".join(mitgl), "/".join(tinfo.get(m, {}).get("kurz", m) for m in mitgl)
            # mehrere nummerierte Mannschaften einer Abteilung gemeinsam (1. Damen + 2. Damen) -> "Damen"
            rest = {re.sub(r"^\d+\.\s*", "", m) for m in mitgl}
            if len(mitgl) > 1 and len(rest) == 1 and all(re.match(r"^\d+\.\s*", m) for m in mitgl):
                name = kurz = rest.pop()
            einheiten.append(dict(tag=tag, team=name, kurz=kurz,
                                  felder=list(f), von=v, bis=b, farbe=ti["farbe"], text=ti["text"], mitglieder=mitgl))
        einheiten.sort(key=lambda e: (e["tag"], e["von"], FELDER.index(e["felder"][0])))
        out.append(dict(blatt=pname, titel=pinfo["titel"], saison=pname, gueltig=sorted(pinfo["gueltig"]),
                        gueltigText="gültig " + " und ".join("vom %s bis %s" % (date.fromisoformat(x).strftime("%d.%m.%Y"), date.fromisoformat(y).strftime("%d.%m.%Y")) for x, y in sorted(pinfo["gueltig"])),
                        einheiten=einheiten))
    res = dict(erzeugt=datetime.now().isoformat(timespec="minutes"), mannschaften=teams, plaene=out)
    with open(a.out, "w", encoding="utf-8") as fh: json.dump(res, fh, ensure_ascii=False, indent=1)
    for p in out: print(f"{p['saison']}: {len(p['einheiten'])} Einheiten, gültig {p['gueltig']}")
    for f in fehler: print("WARNUNG:", f, file=sys.stderr)

if __name__ == "__main__":
    main()
