"""
Dump data MENTAH (apa adanya dari API) seluruh project di Dependency-Track.

Hasil di folder output (default: dump/):
    projects.json                 daftar semua project
    components/<project>.json     component per project (+ metrics, repositoryMeta, lisensi)
    all-components.json           gabungan: {"nama:versi (uuid)": [component, ...]}
    metrics/<project>.json        (opsional --with-metrics) metrik terkini per project
    findings/<project>.json       (opsional --with-findings) vulnerability per project

Hanya standard library Python 3.8+.

Contoh:
    export DT_KEY="odt_xxxxxxxx"
    python3 dtrack_dump.py --url http://localhost:8082 --with-metrics
"""
import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


def api_get(base, path, key, params=None, ctx=None):
    url = f"{base.rstrip('/')}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Api-Key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
            total = resp.headers.get("X-Total-Count")
            body = resp.read()
            return (json.loads(body) if body else None), (int(total) if total else None)
    except urllib.error.HTTPError as e:
        return {"__error__": f"HTTP {e.code}", "url": url}, None
    except urllib.error.URLError as e:
        sys.exit(f"Gagal konek ke {url}: {e.reason}\n  Cek --url (http vs https) dan port API server.")


def fetch_all(base, path, key, ctx, page_size=100, extra=None):
    items, page = [], 1
    while True:
        params = {"pageSize": page_size, "pageNumber": page}
        if extra:
            params.update(extra)
        data, total = api_get(base, path, key, params, ctx)
        if isinstance(data, dict) and "__error__" in data:
            sys.exit(f"{data['__error__']} pada {data['url']}\n"
                     f"  401/403 -> cek API key & permission (VIEW_PORTFOLIO)")
        if not data:
            break
        items.extend(data)
        if (total is not None and len(items) >= total) or len(data) < page_size:
            break
        page += 1
    return items


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def safe_name(p):
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{p['name']}_{p.get('version') or 'noversion'}")
    return f"{base}_{p['uuid'][:8]}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("DT_URL", "http://localhost:8082"),
                    help="Base URL API server (env: DT_URL, default http://localhost:8082)")
    ap.add_argument("--out", default="dump", help="Folder output (default: dump)")
    ap.add_argument("--include-inactive", action="store_true", help="Ikutkan project non-aktif")
    ap.add_argument("--with-metrics", action="store_true", help="Ambil juga metrik terkini tiap project")
    ap.add_argument("--with-findings", action="store_true", help="Ambil juga daftar vulnerability tiap project")
    ap.add_argument("--insecure", action="store_true", help="Abaikan validasi sertifikat TLS")
    args = ap.parse_args()

    key = os.environ.get("DT_KEY")
    if not key:
        sys.exit('Env DT_KEY belum di-set. Jalankan: export DT_KEY="<api key>"')

    ctx = None
    if args.insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    projects = fetch_all(args.url, "/api/v1/project", key, ctx)
    if not args.include_inactive:
        projects = [p for p in projects if p.get("active", True)]
    save(os.path.join(args.out, "projects.json"), projects)
    print(f"{len(projects)} project -> {args.out}/projects.json", file=sys.stderr)

    combined = {}
    for p in projects:
        fname = safe_name(p)
        label = f"{p['name']}:{p.get('version') or '-'} ({p['uuid']})"

        comps = fetch_all(args.url, f"/api/v1/component/project/{p['uuid']}", key, ctx)
        save(os.path.join(args.out, "components", fname + ".json"), comps)
        combined[label] = comps
        print(f"  {label}: {len(comps)} component", file=sys.stderr)

        if args.with_metrics:
            data, _ = api_get(args.url, f"/api/v1/metrics/project/{p['uuid']}/current", key, None, ctx)
            save(os.path.join(args.out, "metrics", fname + ".json"), data)
        if args.with_findings:
            data, _ = api_get(args.url, f"/api/v1/finding/project/{p['uuid']}", key, None, ctx)
            save(os.path.join(args.out, "findings", fname + ".json"), data)

    save(os.path.join(args.out, "all-components.json"), combined)
    total = sum(len(v) for v in combined.values())
    print(f"Selesai: {total} component dari {len(combined)} project -> {args.out}/", file=sys.stderr)


if __name__ == "__main__":
    main()
