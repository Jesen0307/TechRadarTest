#!/usr/bin/env python3
"""
Menggabungkan unmapped.json dan proposals.json dari AI agent
langsung menjadi radar.json tanpa memerlukan mapping.json.
"""
import json
import sys

def main():
    try:
        with open("unmapped.json", encoding="utf-8") as f:
            unmapped = json.load(f)
    except FileNotFoundError:
        sys.exit("unmapped.json tidak ditemukan.")

    try:
        with open("proposals.json", encoding="utf-8") as f:
            proposals = json.load(f)
    except FileNotFoundError:
        sys.exit("proposals.json tidak ditemukan.")

    if not isinstance(proposals, list):
        sys.exit("proposals.json harus berupa array JSON.")

    # Indeks usulan AI berdasarkan nama teknologi
    prop_map = {p["name"]: p for p in proposals if isinstance(p, dict) and "name" in p}

    blips = []
    for item in unmapped:
        name = item["name"]
        if name in prop_map:
            p = prop_map[name]
            blips.append({
                "name": name,
                "ring": p.get("ring", "Assess"),
                "quadrant": p.get("quadrant", "Tools"),
                "isNew": "FALSE",
                "description": f"Dipakai di {item['projectCount']} project ({', '.join(item['projects'][:3])}). {p.get('alasan', '')}".strip()
            })
        else:
            # Fallback jika teknologi tidak disebut oleh AI
            blips.append({
                "name": name,
                "ring": "Assess",
                "quadrant": "Tools",
                "isNew": "FALSE",
                "description": f"Dipakai di {item['projectCount']} project. Belum diklasifikasikan oleh AI."
            })

    with open("radar.json", "w", encoding="utf-8") as f:
        json.dump(blips, f, indent=2, ensure_ascii=False)
    
    print(f"Berhasil membuat radar.json dengan {len(blips)} blip langsung dari hasil AI.")

if __name__ == "__main__":
    main()
