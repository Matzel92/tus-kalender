#!/usr/bin/env python3
"""
Kartenbild für die Homepage erzeugen (OpenStreetMap-Kacheln + Markierungen), im Stil der Turnen-Karten:
weißes Schild mit blauem Rand über der Markierung, „Karte öffnen ↗“ unten links, Quellenangabe unten rechts.

Die Karte wird als Bild auf der Homepage gezeigt (kein Laden von openstreetmap.org beim Besucher);
erst ein Klick öffnet openstreetmap.org.

Aufruf:  python karten/karte.py karten/anreise.json      (erzeugt das in der JSON genannte Bild)
Läuft im Workflow „Karte erzeugen“ (GitHub Actions), weil die Kachelserver nur von dort erreichbar sind.
"""
import io, json, math, sys, time
from pathlib import Path
import requests
from PIL import Image, ImageDraw, ImageFont

KACHEL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
BLAU, WEISS = (11, 65, 153), (255, 255, 255)
SCHRIFT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SCHRIFT_N = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def welt(lat, lon, z):
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def schild(d, x, y, text, f, unten=False):
    """Weißes Schild mit blauem Rand, zentriert über (x, y) – oder darunter."""
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    w, h = r - l + 44, b - t + 26
    x0 = int(x - w / 2); y0 = int(y + 18) if unten else int(y - h - 18)
    d.rounded_rectangle((x0 + 3, y0 + 5, x0 + w + 3, y0 + h + 5), 14, fill=(0, 0, 0, 60))
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), 14, fill=WEISS, outline=BLAU, width=4)
    d.text((x0 + 22 - l, y0 + 13 - t), text, font=f, fill=BLAU)


def pin(d, x, y, s=1.0):
    r = 26 * s
    d.ellipse((x - r + 3, y - 2.6 * r + 5, x + r + 3, y - 0.6 * r + 5), fill=(0, 0, 0, 60))
    d.polygon([(x - r * .82, y - 1.25 * r), (x + r * .82, y - 1.25 * r), (x, y)], fill=BLAU)
    d.ellipse((x - r, y - 2.6 * r, x + r, y - 0.6 * r), fill=BLAU)
    d.ellipse((x - r * .42, y - 2.02 * r, x + r * .42, y - 1.18 * r), fill=WEISS)


def haltestelle(d, x, y):
    """Haltestellenzeichen: gelber Kreis mit grünem H (wie in Deutschland üblich)."""
    r = 22
    d.ellipse((x - r + 2, y - r + 4, x + r + 2, y + r + 4), fill=(0, 0, 0, 70))
    d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 212, 0), outline=(0, 130, 70), width=4)
    f = ImageFont.truetype(SCHRIFT, 28)
    l, t, rr, b = d.textbbox((0, 0), "H", font=f)
    d.text((x - (rr - l) / 2 - l, y - (b - t) / 2 - t), "H", font=f, fill=(0, 130, 70))


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    W, H, z = cfg["breite"], cfg["hoehe"], cfg["zoom"]
    cx, cy = welt(cfg["mitte"][0], cfg["mitte"][1], z)
    x0, y0 = cx - W / 2, cy - H / 2
    bild = Image.new("RGBA", (W, H), WEISS)
    s = requests.Session(); s.headers["User-Agent"] = "TuS-Harpen-Homepage-Kartenbild/1.0 (einmalige Erzeugung, github.com/Matzel92/tus-kalender)"
    for tx in range(int(x0 // 256), int((x0 + W) // 256) + 1):
        for ty in range(int(y0 // 256), int((y0 + H) // 256) + 1):
            r = s.get(KACHEL.format(z=z, x=tx, y=ty), timeout=30); r.raise_for_status()
            bild.paste(Image.open(io.BytesIO(r.content)).convert("RGBA"), (int(tx * 256 - x0), int(ty * 256 - y0)))
            time.sleep(0.1)
    ebene = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ebene)
    f = ImageFont.truetype(SCHRIFT, cfg.get("schrift", 30)); fk = ImageFont.truetype(SCHRIFT, 26)
    for m in cfg["markierungen"]:
        x, y = welt(m["lat"], m["lon"], z); x -= x0; y -= y0
        if m.get("art") == "haltestelle":
            haltestelle(d, x, y); schild(d, x, y + (0 if m.get("unten") else -8), m["text"], fk, unten=m.get("unten", False))
        else:
            pin(d, x, y); schild(d, x, y - 70, m["text"], f)
    # „Karte öffnen ↗“ unten links, Quelle unten rechts
    t = "Karte öffnen ↗"; l, tt, r, b = d.textbbox((0, 0), t, font=fk)
    d.rounded_rectangle((24, H - 24 - (b - tt) - 28, 24 + (r - l) + 44, H - 24), 30, fill=BLAU)
    d.text((24 + 22 - l, H - 24 - (b - tt) - 14 - tt), t, font=fk, fill=WEISS)
    q = "© OpenStreetMap-Mitwirkende"; fq = ImageFont.truetype(SCHRIFT_N, 20); l, tt, r, b = d.textbbox((0, 0), q, font=fq)
    d.rectangle((W - (r - l) - 20, H - (b - tt) - 14, W, H), fill=(255, 255, 255, 210))
    d.text((W - (r - l) - 10 - l, H - (b - tt) - 7 - tt), q, font=fq, fill=(40, 40, 40))
    bild = Image.alpha_composite(bild, ebene).convert("RGB")
    ziel = Path(cfg["datei"]); ziel.parent.mkdir(parents=True, exist_ok=True)
    bild.save(ziel, quality=86, optimize=True, progressive=True)
    print(ziel, bild.size, ziel.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
