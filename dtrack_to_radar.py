#!/usr/bin/env python3
"""
Ambil component dari Dependency-Track, kelompokkan menjadi teknologi, lalu hasilkan:

    radar.json      blip format Thoughtworks BYOR (hanya teknologi yang ada di mapping)
    unmapped.json   teknologi yang belum punya quadrant/ring, beserta data pendukung

Keputusan quadrant dan ring dibaca dari mapping.json:

    {"Spring Boot": {"quadrant": "Languages & Frameworks", "ring": "Adopt", "catatan": "..."}}

Entri dengan "manual": true selalu masuk radar walau tidak ada di data
(contoh: base image yang tidak muncul di SBOM).

Contoh:
    export DT_KEY="odt_xxxxxxxx"
    python3 dtrack_to_radar.py --url http://localhost:8082
"""
import argparse
import datetime
import fnmatch
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

QUADRANTS = ["Languages & Frameworks", "Platforms", "Tools", "Techniques"]
RINGS = ["Adopt", "Trial", "Assess", "Hold"]

DEFAULT_RING = "Adopt"
DEFAULT_QUADRANT = "Languages & Frameworks"

INCLUDE_CLASSIFIERS = {"LIBRARY", "FRAMEWORK"}
OS_PURL_TYPES = {"deb", "apk", "rpm"}

TECH_RULES = [
    ("org.springframework.boot*",     "*", "Spring Boot"),
    ("org.springframework.data*",     "*", "Spring Data"),
    ("org.springframework.security*", "*", "Spring Security"),
    ("org.springframework*",          "*", "Spring Framework"),
    ("com.fasterxml.jackson*",        "*", "Jackson"),
    ("com.fasterxml",                 "*", "Jackson"),
    ("org.apache.tomcat*",            "*", "Apache Tomcat"),
    ("org.apache.logging.log4j*",     "*", "Log4j2"),
    ("org.hibernate*",                "*", "Hibernate ORM"),
    ("org.glassfish.jaxb*",           "*", "JAXB"),
    ("com.sun.istack*",               "*", "JAXB"),
    ("jakarta.*",                     "*", "Jakarta EE"),
    ("org.eclipse.angus*",            "*", "Eclipse Angus (Jakarta Mail)"),
    ("io.micrometer*",                "*", "Micrometer"),
]


def api_get(base, path, key, params=None, ctx=None):
    url = f"{base.rstrip('/')}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Api-Key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            total = resp.headers.get("X-Total-Count")
            return json.load(resp), (int(total) if total else None)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} pada {url}\n"
                 f"  401/403 -> cek API key dan permission (VIEW_PORTFOLIO)\n  {e.read()[:200]!r}")
    except urllib.error.URLError as e:
        sys.exit(f"Gagal konek ke {url}: {e.reason}\n"
                 f"  Cek --url (http vs https) dan port API server.")


def fetch_all(base, path, key, ctx, page_size=100):
    items, page = [], 1
    while True:
        data, total = api_get(base, path, key, {"pageSize": page_size, "pageNumber": page}, ctx)
        if not data:
            break
        items.extend(data)
        if (total is not None and len(items) >= total) or len(data) < page_size:
            break
        page += 1
    return items


def purl_type(purl):
    if purl and purl.startswith("pkg:"):
        return purl[4:].split("/", 1)[0].lower()
    return ""


def technology_of(comp):
    group, name = comp.get("group") or "", comp.get("name") or ""
    for g_pat, n_pat, tech in TECH_RULES:
        if fnmatch.fnmatch(group, g_pat) and fnmatch.fnmatch(name, n_pat):
            return tech
    return name


def major(version):
    m = re.match(r"\D*(\d+)", version or "")
    if not m:
        return None
    n = int(m.group(1))
    return n if n < 1000 else None


def month(ms):
    if not ms:
        return None
    dt = datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m")


def new_tech():
    return {"projects": set(), "versions": set(), "components": set(), "purl_types": set(),
            "pub_min": None, "pub_max": None, "critical": 0, "high": 0, "kev": False,
            "policy_fail": 0, "licenses": set(), "no_license": 0, "behind": set()}


def add_component(t, comp, label):
    t["projects"].add(label)
    if comp.get("version"):
        t["versions"].add(comp["version"])
    t["components"].add(comp["name"])
    t["purl_types"].add(purl_type(comp.get("purl")) or "unknown")

    meta = comp.get("repositoryMeta") or {}
    pub = meta.get("latestVersionPublishedAt")
    if pub:
        t["pub_min"] = pub if t["pub_min"] is None else min(t["pub_min"], pub)
        t["pub_max"] = pub if t["pub_max"] is None else max(t["pub_max"], pub)
    cur, latest = comp.get("version"), meta.get("latestVersion")
    mc, ml = major(cur), major(latest)
    if mc is not None and ml is not None and ml > mc:
        t["behind"].add(f"{comp['name']} {cur} -> {latest}")

    metrics = comp.get("metrics") or {}
    t["critical"] = max(t["critical"], metrics.get("critical") or 0)
    t["high"] = max(t["high"], metrics.get("high") or 0)
    t["kev"] = t["kev"] or (metrics.get("kev") or 0) > 0
    t["policy_fail"] = max(t["policy_fail"], metrics.get("policyViolationsFail") or 0)

    lic = comp.get("resolvedLicense") or {}
    lic_id = lic.get("licenseId") or lic.get("name")
    if lic_id:
        t["licenses"].add(lic_id)
    else:
        t["no_license"] += 1


def load_mapping(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        sys.exit(f"{path}: harus berupa objek JSON {{nama teknologi: {{quadrant, ring}}}}")
    errors = []
    for name, entry in data.items():
        if not isinstance(entry, dict):
            errors.append(f"{name}: entri harus berupa objek")
            continue
        if entry.get("quadrant") not in QUADRANTS:
            errors.append(f"{name}: quadrant '{entry.get('quadrant')}' tidak valid ({', '.join(QUADRANTS)})")
        if entry.get("ring") not in RINGS:
            errors.append(f"{name}: ring '{entry.get('ring')}' tidak valid ({', '.join(RINGS)})")
    if errors:
        sys.exit(f"{path} tidak valid:\n  " + "\n  ".join(errors))
    return data


def describe(t, extra=None):
    text = f"Dipakai di {len(t['projects'])} project ({', '.join(sorted(t['projects']))}). "
    text += f"Versi: {', '.join(sorted(t['versions']))}. "
    if len(t["components"]) > 1:
        text += f"Modul: {', '.join(sorted(t['components']))}. "
    if extra:
        text += extra
    return text.strip()


def unmapped_entry(name, t):
    return {
        "name": name,
        "projectCount": len(t["projects"]),
        "projects": sorted(t["projects"]),
        "versions": sorted(t["versions"]),
        "modules": sorted(t["components"]),
        "purlTypes": sorted(t["purl_types"]),
        "evidence": {
            "latestReleaseOldest": month(t["pub_min"]),
            "latestReleaseNewest": month(t["pub_max"]),
            "majorBehind": sorted(t["behind"])[:5],
            "maxCritical": t["critical"],
            "maxHigh": t["high"],
            "kev": t["kev"],
            "policyViolationsFail": t["policy_fail"],
            "licenses": sorted(t["licenses"]),
            "componentsWithoutLicense": t["no_license"],
        },
    }


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("DT_URL", "http://localhost:8081"),
                    help="Base URL API server Dependency-Track (env: DT_URL)")
    ap.add_argument("--out", default="radar.json", help="File radar (default: radar.json)")
    ap.add_argument("--mapping", default="mapping.json", help="File keputusan (default: mapping.json)")
    ap.add_argument("--unmapped", default="unmapped.json", help="File teknologi belum terpetakan")
    ap.add_argument("--include-unmapped", action="store_true",
                    help="Masukkan teknologi belum terpetakan ke radar dengan quadrant/ring default")
    ap.add_argument("--tag", help="Hanya project yang punya tag ini")
    ap.add_argument("--include-inactive", action="store_true", help="Ikutkan project non-aktif")
    ap.add_argument("--include-os", action="store_true", help="Ikutkan paket OS (deb/apk/rpm)")
    ap.add_argument("--exclude-type", action="append", default=[], metavar="TIPE",
                    help="Filter jenis purl tambahan, bisa diulang (contoh: --exclude-type golang)")
    ap.add_argument("--insecure", action="store_true", help="Abaikan validasi sertifikat TLS")
    args = ap.parse_args()

    key = os.environ.get("DT_KEY")
    if not key:
        sys.exit('Env DT_KEY belum di-set. Jalankan: export DT_KEY="<api key>"')

    exclude_types = set() if args.include_os else set(OS_PURL_TYPES)
    exclude_types |= {t.lower() for t in args.exclude_type}

    ctx = None
    if args.insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    mapping = load_mapping(args.mapping)

    projects = fetch_all(args.url, "/api/v1/project", key, ctx)
    if not args.include_inactive:
        projects = [p for p in projects if p.get("active", True)]
    if args.tag:
        projects = [p for p in projects
                    if args.tag.lower() in [t.get("name", "").lower() for t in p.get("tags", [])]]
    print(f"{len(projects)} project dipakai", file=sys.stderr)

    techs = defaultdict(new_tech)
    by_type, filtered_type = Counter(), Counter()
    skipped = 0
    for p in projects:
        label = f"{p['name']}:{p.get('version') or '-'}"
        comps = fetch_all(args.url, f"/api/v1/component/project/{p['uuid']}", key, ctx)
        kept = 0
        for c in comps:
            if (c.get("classifier") or "LIBRARY") not in INCLUDE_CLASSIFIERS:
                skipped += 1
                continue
            ptype = purl_type(c.get("purl"))
            if ptype in exclude_types:
                skipped += 1
                filtered_type[ptype] += 1
                continue
            add_component(techs[technology_of(c)], c, label)
            by_type[ptype or "unknown"] += 1
            kept += 1
        print(f"  {label}: {kept}/{len(comps)} component dipakai", file=sys.stderr)

    blips, unmapped = [], []
    for name in sorted(techs, key=str.lower):
        t = techs[name]
        if name in mapping:
            entry = mapping[name]
            blips.append({"name": name, "ring": entry["ring"], "quadrant": entry["quadrant"],
                          "isNew": "FALSE", "description": describe(t, entry.get("catatan"))})
        else:
            unmapped.append(unmapped_entry(name, t))
            if args.include_unmapped:
                blips.append({"name": name, "ring": DEFAULT_RING, "quadrant": DEFAULT_QUADRANT,
                              "isNew": "FALSE", "description": describe(t)})

    manual = 0
    stale = []
    for name, entry in sorted(mapping.items(), key=lambda kv: kv[0].lower()):
        if name in techs:
            continue
        if entry.get("manual"):
            blips.append({"name": name, "ring": entry["ring"], "quadrant": entry["quadrant"],
                          "isNew": "FALSE", "description": entry.get("catatan") or "Ditambahkan manual."})
            manual += 1
        else:
            stale.append(name)

    write_json(args.out, blips)
    write_json(args.unmapped, unmapped)

    print(f"\nSelesai: {len(blips)} blip -> {args.out} ({manual} manual)", file=sys.stderr)
    print(f"Belum terpetakan: {len(unmapped)} teknologi -> {args.unmapped}", file=sys.stderr)
    if stale:
        print(f"Ada di mapping tapi tidak ada di data: {', '.join(stale)}", file=sys.stderr)
    if len({b["quadrant"] for b in blips}) > 4:
        print("PERINGATAN: lebih dari 4 quadrant berbeda, BYOR hanya menampilkan 4.", file=sys.stderr)

    print("\nKomposisi component per jenis paket:", file=sys.stderr)
    all_types = by_type + filtered_type
    total = sum(all_types.values()) or 1
    for ptype, n in all_types.most_common():
        status = "difilter" if ptype in filtered_type else "dipakai"
        print(f"  {ptype or 'unknown':<10} {n:>6}  ({n * 100 / total:.1f}%)  {status}", file=sys.stderr)
    print(f"  ({skipped} component difilter, termasuk entri bukan library)", file=sys.stderr)


if __name__ == "__main__":
    main()
