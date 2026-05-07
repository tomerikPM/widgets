#!/usr/bin/env python3
"""
Henter alle adresser i Grenland (Skien 4003, Porsgrunn 4001, Bamble 4012,
Siljan 4010) fra Kartverkets åpne Geonorge-API og lagrer som kompakt JSON.

Geonorge sok-API capper på 10 000 treff per spørring. Vi paginerer derfor
per postnummer (ingen postnummer har over 10k adresser).

Postnumre per kommune hentes fra Postens åpne register (Bring).

Output: data/grenland-adresser.json  (gruppert etter gate, kompakt)
"""
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

KOMMUNER = {
    "4001": "Porsgrunn",
    "4003": "Skien",
    "4010": "Siljan",
    "4012": "Bamble",
}
PER_PAGE = 1000  # max API tillater
USER_AGENT = "varden-bypakke-grenland-widget/1.0 (post@varden.no)"

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "grenland-adresser.json"


def fetch_postnumre():
    """Hent norsk postnummerregister fra Bring og filtrer til Grenland."""
    url = "https://www.bring.no/postnummerregister-ansi.txt"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("iso-8859-1")
    by_kommune = defaultdict(list)
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        postnr, _sted, knr, _knavn = parts[0], parts[1], parts[2], parts[3]
        if knr in KOMMUNER:
            by_kommune[knr].append(postnr)
    return by_kommune


def fetch_page(postnr, side):
    params = {
        "postnummer": postnr,
        "treffPerSide": PER_PAGE,
        "side": side,
        "objtype": "Vegadresse",
    }
    url = "https://ws.geonorge.no/adresser/v1/sok?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_for_postnummer(postnr):
    out = []
    side = 0
    while True:
        data = fetch_page(postnr, side)
        adr = data.get("adresser", [])
        if not adr:
            break
        out.extend(adr)
        meta = data.get("metadata", {})
        til = meta.get("viserTil") or 0
        total = meta.get("totaltAntallTreff") or 0
        if til >= total:
            break
        side += 1
        time.sleep(0.05)
    return out


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    print("Henter postnummerregister fra Bring …")
    by_kommune = fetch_postnumre()
    for knr, navn in KOMMUNER.items():
        print(f"  {navn} ({knr}): {len(by_kommune[knr])} postnumre")

    seen = set()
    all_addresses = []
    for knr, navn in KOMMUNER.items():
        print(f"\n=== {navn} ({knr}) ===")
        for i, postnr in enumerate(sorted(by_kommune[knr]), 1):
            adr_raw = fetch_for_postnummer(postnr)
            kept = 0
            for a in adr_raw:
                if a.get("kommunenummer") != knr:
                    continue  # postnummer kan dekke flere kommuner
                key = (a["adressekode"], a["nummer"], a.get("bokstav") or "")
                if key in seen:
                    continue
                seen.add(key)
                pt = a.get("representasjonspunkt") or {}
                lat = pt.get("lat")
                lng = pt.get("lon")
                if lat is None or lng is None:
                    continue
                all_addresses.append({
                    "gate": a["adressenavn"],
                    "nr": a["nummer"],
                    "bokstav": a.get("bokstav") or "",
                    "postnr": a.get("postnummer") or "",
                    "poststed": (a.get("poststed") or "").title(),
                    "lat": round(lat, 5),
                    "lng": round(lng, 5),
                })
                kept += 1
            print(f"  [{i:>2}/{len(by_kommune[knr])}] {postnr}: {kept} nye (av {len(adr_raw)} treff)")

    print(f"\nTotalt: {len(all_addresses)} unike adresser")

    # Grupper per (gate, poststed) for kompakt format
    grouped = defaultdict(list)
    for a in all_addresses:
        key = f"{a['gate']}, {a['poststed']}"
        grouped[key].append([a["nr"], a["bokstav"], a["lat"], a["lng"]])

    out = {}
    for key in sorted(grouped):
        houses = sorted(grouped[key], key=lambda h: (h[0], h[1]))
        out[key] = houses

    payload = {
        "version": 1,
        "kilde": "Kartverket / Geonorge — Matrikkelens vegadresser",
        "kommuner": list(KOMMUNER.values()),
        "antall_adresser": len(all_addresses),
        "antall_gater": len(out),
        "gater": out,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"Skrev {OUT_PATH} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
