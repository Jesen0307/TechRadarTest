#!/usr/bin/env python3
"""
Validasi proposals.json hasil AI agent, dan (opsional) gabungkan ke mapping.json.

Aturan validasi:
    - proposals.json harus berupa array JSON
    - tiap entri hanya boleh punya kunci: name, quadrant, ring, alasan, yakin
    - name harus ada di unmapped.json dan belum ada di mapping.json, tanpa duplikat
    - quadrant dan ring harus dari daftar yang diizinkan
    - yakin: tinggi | sedang | rendah
    - alasan: teks tidak kosong

Exit code 0 bila valid, 1 bila ada kesalahan.

Contoh:
    python3 validate_proposals.py proposals.json
    python3 validate_proposals.py proposals.json --merge
    python3 validate_proposals.py proposals.json --merge --include-low
"""
import argparse
import json
import os
import sys

QUADRANTS = ["Languages & Frameworks", "Platforms", "Tools", "Techniques"]
RINGS = ["Adopt", "Trial", "Assess", "Hold"]
CONFIDENCE = ["tinggi", "sedang", "rendah"]
KEYS = {"name", "quadrant", "ring", "alasan", "yakin"}
MAX_ALASAN = 400


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"{what} tidak ditemukan: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"{what} bukan JSON valid ({path}): {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proposals", help="File usulan dari agent")
    ap.add_argument("--unmapped", default="unmapped.json")
    ap.add_argument("--mapping", default="mapping.json")
    ap.add_argument("--merge", action="store_true", help="Gabungkan usulan valid ke file mapping")
    ap.add_argument("--include-low", action="store_true",
                    help="Saat --merge, ikutkan usulan berkeyakinan rendah (default: dilewati)")
    args = ap.parse_args()

    proposals = read_json(args.proposals, "File usulan")
    unmapped = read_json(args.unmapped, "unmapped.json")
    mapping = read_json(args.mapping, "mapping.json") if os.path.exists(args.mapping) else {}

    known = {u["name"] for u in unmapped}
    errors = []

    if not isinstance(proposals, list):
        sys.exit("File usulan harus berupa array JSON.")

    seen = set()
    for i, p in enumerate(proposals, 1):
        tag = f"usulan #{i}"
        if not isinstance(p, dict):
            errors.append(f"{tag}: harus berupa objek")
            continue
        name = p.get("name")
        if isinstance(name, str):
            tag = f"usulan #{i} ({name})"
        extra = set(p) - KEYS
        missing = KEYS - set(p)
        if extra:
            errors.append(f"{tag}: kunci tidak dikenal: {sorted(extra)}")
        if missing:
            errors.append(f"{tag}: kunci wajib hilang: {sorted(missing)}")
            continue
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{tag}: name kosong")
            continue
        if name in seen:
            errors.append(f"{tag}: duplikat")
        seen.add(name)
        if name in mapping:
            errors.append(f"{tag}: sudah ada di mapping.json")
        elif name not in known:
            errors.append(f"{tag}: tidak ada di unmapped.json")
        if p["quadrant"] not in QUADRANTS:
            errors.append(f"{tag}: quadrant '{p['quadrant']}' tidak valid")
        if p["ring"] not in RINGS:
            errors.append(f"{tag}: ring '{p['ring']}' tidak valid")
        if p["yakin"] not in CONFIDENCE:
            errors.append(f"{tag}: yakin '{p['yakin']}' tidak valid")
        alasan = p["alasan"]
        if not isinstance(alasan, str) or not alasan.strip():
            errors.append(f"{tag}: alasan kosong")
        elif len(alasan) > MAX_ALASAN:
            errors.append(f"{tag}: alasan lebih dari {MAX_ALASAN} karakter")

    if errors:
        print(f"{len(errors)} kesalahan pada {args.proposals}:", file=sys.stderr)
        for e in errors[:50]:
            print(f"  - {e}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  ... dan {len(errors) - 50} lainnya", file=sys.stderr)
        sys.exit(1)

    low = [p["name"] for p in proposals if p["yakin"] == "rendah"]
    no_proposal = sorted(known - seen - set(mapping))
    print(f"Valid: {len(proposals)} usulan ({len(low)} berkeyakinan rendah)", file=sys.stderr)
    if no_proposal:
        print(f"Belum ada usulan untuk {len(no_proposal)} teknologi: {', '.join(no_proposal[:10])}"
              f"{' ...' if len(no_proposal) > 10 else ''}", file=sys.stderr)

    if args.merge:
        added, skipped_low = 0, []
        for p in proposals:
            if p["yakin"] == "rendah" and not args.include_low:
                skipped_low.append(p["name"])
                continue
            mapping[p["name"]] = {
                "quadrant": p["quadrant"],
                "ring": p["ring"],
                "catatan": p["alasan"].strip(),
                "sumber": "agent-usulan",
                "yakin": p["yakin"],
            }
            added += 1
        with open(args.mapping, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(mapping.items(), key=lambda kv: kv[0].lower())), f,
                      indent=2, ensure_ascii=False)
        print(f"Digabung ke {args.mapping}: {added} entri", file=sys.stderr)
        if skipped_low:
            print(f"Dilewati (keyakinan rendah, perlu keputusan manusia): {', '.join(skipped_low)}",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
