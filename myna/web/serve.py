#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""serve.py [--port N] [--host ADDR] [--pyodide DIR] [--relay URL] [--turnstile SITEKEY] [--log] [--cert PEM] [--write DIR]: Myna's phone page.

Serves this folder's page and everything a phone in it needs, from the repository it is in. Standard library only.

  /, /app.js, /app.css, /phone_worker.js, /manifest.webmanifest, /icons/icon-N.png, /icons/screen.png     this folder
  /fonts/Nunito-ExtraBold.ttf, /fonts/Nunito-Light.ttf     the phones' own font (OFL), from myna/assets/fonts, for the page's words
  /cell.js            the relay's client, myna/relay/client/cell.js
  /config.json        {"relay": URL, "turnstile": SITEKEY}: the first --relay ("" without one: the page uses the loopback
                      network) and the site key of the relay's person check (--turnstile; "": the page asks for none first)
  /devices.json       the phones with a firmware of our own (a profile with BOOT_ELF) whose ELF file is built
  /phone_src.json     the Python source a phone imports, one archive {"files": {path: text}}: the files of platform.txt
                      and the .py files of those device folders, made once when the server starts
  /firmware/NAME.elf  the ELF file of such a phone, read where its profile names it (BOOT_ELF) at each request
  /skin/NAME/FILE     skin.json and the .svg pictures of native/devices/NAME/skin/
  /pycore.js          native/core/web/pycore.js;  /dbcore.wasm: the WebAssembly core (native/core/build.sh; DBCORE_OUT)
  /phone3d.js, /phone3d.css, /vendor/three-0.186.1/*.js   the phone in 3D and three.js (native/core/web/)
  /pyodide/NAME       the files of an unpacked Pyodide release (--pyodide DIR, or MYNA_PYODIDE); not part of the repository
  /log (POST)         with --log only: one line from the page (?log=1), printed here. The lines hold the phone's number
Nothing else of the repository is read: no flash image, no stock firmware file, no flash state (the page keeps its own).
It listens on 127.0.0.1 unless --host says otherwise; it is a development server, not one for the internet. The page
needs a secure context for the relay's keys: 127.0.0.1 and localhost are one; another host needs --cert (PEM, key included).
--write DIR serves nothing: it writes every route above as a file into DIR, for a static host (README.md, "Hosting it").
"""
import argparse, http.server, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
NATIVE = os.path.join(ROOT, 'native')
RELAY_CLIENT = os.path.join(ROOT, 'myna', 'relay', 'client', 'cell.js')
FONTS = os.path.join(ROOT, 'myna', 'assets', 'fonts')
PYODIDE = {'pyodide.js': 'text/javascript; charset=utf-8', 'pyodide.asm.mjs': 'text/javascript; charset=utf-8',
           'pyodide.asm.wasm': 'application/wasm', 'python_stdlib.zip': 'application/zip', 'pyodide-lock.json': 'application/json'}
THREE = 'three-0.186.1'                         # the vendored three.js (native/core/web/vendor/)
CSP = ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'%s; worker-src 'self'; connect-src 'self'%s; style-src 'self'; "
       "font-src 'self'; img-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'%s")
# the relay's person check (Turnstile): Cloudflare's script and the frame it draws, allowed only when there is a relay
TURNSTILE = 'https://challenges.cloudflare.com'
JS, HTML, CSS = 'text/javascript; charset=utf-8', 'text/html; charset=utf-8', 'text/css; charset=utf-8'
SKIN_FILE = re.compile(r'^[a-z0-9_.-]+\.(svg|json)$')
ICON_FILE = re.compile(r'^(icon-(180|192|512)|screen)\.png$')
MAX_FILE = 1 << 20


def platform():
    """The paths of platform.txt, from the repository root."""
    with open(os.path.join(HERE, 'platform.txt'), encoding='utf-8') as f:
        return [l.strip() for l in f if l.strip() and not l.startswith('#')]


def phones():
    """{name: profile} of the devices with a firmware of our own (BOOT_ELF; a profile only names paths). Only a profile
    whose text names BOOT_ELF is imported: the others are never read."""
    out = {}
    sys.path.insert(0, NATIVE)
    try:
        import devices
        for name in devices.available():
            with open(os.path.join(NATIVE, 'devices', name, '__init__.py'), encoding='utf-8') as f:
                if 'BOOT_ELF' not in f.read():
                    continue
            try:
                p = devices.load(name)
            except Exception as e:
                print('profile %s not read: %s' % (name, e), flush=True)
                continue
            if getattr(p, 'BOOT_ELF', None):
                out[name] = p
    finally:
        sys.path.remove(NATIVE)
    return out


def archive(names):
    """{path: text}: the files of platform.txt and the .py files of the device folders `names` (not their skins)."""
    out = {}

    def take(rel):
        path = os.path.join(ROOT, rel)
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > MAX_FILE:
            raise SystemExit('serve.py: %s is not there (platform.txt names it)' % rel)
        with open(path, encoding='utf-8') as f:
            out[rel] = f.read()
    for rel in platform():
        take(rel)
    for name in names:
        top = os.path.join(NATIVE, 'devices', name)
        for e in sorted(os.listdir(top)):
            if e.endswith('.py') and not os.path.islink(os.path.join(top, e)):
                take(os.path.relpath(os.path.join(top, e), ROOT))
    return out


def write_site(out, static, made, firmware, csp):
    """Every route as a file under `out`, for a static host, and `_headers` (the format of Cloudflare Pages and Netlify)
    with the content security policy. Pyodide's files are written only when --pyodide was given."""
    if os.path.exists(out) and os.listdir(out):
        raise SystemExit('serve.py: %s is not empty' % out)
    files = {p: src for p, (src, _kind) in static.items() if p != '/'}
    for name, elf in firmware.items():
        files['/firmware/%s.elf' % name] = elf
        skin = os.path.join(NATIVE, 'devices', name, 'skin')
        files.update({'/skin/%s/%s' % (name, e): os.path.join(skin, e) for e in sorted(os.listdir(skin)) if SKIN_FILE.match(e)})
    files.update({'/icons/' + e: os.path.join(HERE, 'icons', e) for e in sorted(os.listdir(os.path.join(HERE, 'icons'))) if ICON_FILE.match(e)})
    for path, src in sorted(files.items()):
        if not os.path.isfile(src):
            raise SystemExit('serve.py: %s is not there (%s)' % (src, path))
        os.makedirs(os.path.dirname(out + path), exist_ok=True)
        shutil.copyfile(src, out + path)
    for path, data in made.items():
        with open(out + path, 'wb') as f:
            f.write(data)
    with open(os.path.join(out, '_headers'), 'w') as f:
        f.write('/*\n  Content-Security-Policy: %s\n  X-Content-Type-Options: nosniff\n' % csp)
    print('written: %d files to %s%s' % (len(files) + len(made) + 1, out, '' if '/pyodide/pyodide.js' in files else ' (no Pyodide: add its files under pyodide/)'), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--port', type=int, default=8940)
    ap.add_argument('--host', default='127.0.0.1', help='the address to listen on (default 127.0.0.1: this computer only)')
    ap.add_argument('--pyodide', default=os.environ.get('MYNA_PYODIDE'), metavar='DIR',
                    help='a folder with an unpacked Pyodide release (pyodide.js, pyodide.asm.wasm, ...); default: MYNA_PYODIDE')
    ap.add_argument('--relay', action='append', default=[], metavar='URL',
                    help='the text-message relay the page uses (ws:// or wss://); repeat to allow more in the page\'s policy')
    ap.add_argument('--turnstile', default='', metavar='SITEKEY',
                    help='the site key of the relay\'s person check (Turnstile): the page asks for the check before the first join')
    ap.add_argument('--log', action='store_true', help='print the lines a page sends with ?log=1')
    ap.add_argument('--cert', metavar='PEM', help='serve https with this certificate file (key included)')
    ap.add_argument('--write', metavar='DIR', help='do not serve: write the site into DIR (an empty folder) for a static host')
    a = ap.parse_args()

    own = phones()
    listing, firmware = [], {}
    for name, p in sorted(own.items()):
        if not os.path.isfile(p.BOOT_ELF):
            print('%s: no firmware at %s (%s): not offered' % (name, os.path.relpath(p.BOOT_ELF, ROOT), getattr(p, 'BUILD', 'build it first')), flush=True)
            continue
        firmware[name] = p.BOOT_ELF
        listing.append({'name': name, 'title': getattr(p, 'TITLE', name), 'firmware': getattr(p, 'FIRMWARE', ''), 'own': True,
                        'peer': getattr(p, 'PEER', None) or '', 'size': os.path.getsize(p.BOOT_ELF),
                        'etag': 'blank-' + (getattr(p, 'NAND_CHIP', None) or 'default')})
    packed = json.dumps({'files': archive(sorted(own))}).encode()
    config = json.dumps({'relay': a.relay[0] if a.relay else '', 'turnstile': a.turnstile if a.relay else ''}).encode()
    ts = bool(a.relay)
    csp = CSP % (' ' + TURNSTILE if ts else '', ''.join(' ' + u for u in a.relay), '; frame-src ' + TURNSTILE if ts else '')
    wasm = os.path.join(os.environ.get('DBCORE_OUT') or os.path.join(NATIVE, 'core', 'build'), 'dbcore.wasm')
    static = {
        '/': (os.path.join(HERE, 'index.html'), HTML), '/index.html': (os.path.join(HERE, 'index.html'), HTML),
        '/app.js': (os.path.join(HERE, 'app.js'), JS), '/app.css': (os.path.join(HERE, 'app.css'), CSS),
        '/phone_worker.js': (os.path.join(HERE, 'phone_worker.js'), JS), '/cell.js': (RELAY_CLIENT, JS),
        '/manifest.webmanifest': (os.path.join(HERE, 'manifest.webmanifest'), 'application/manifest+json'),
        '/pycore.js': (os.path.join(NATIVE, 'core', 'web', 'pycore.js'), JS), '/dbcore.wasm': (wasm, 'application/wasm'),
        '/phone3d.js': (os.path.join(NATIVE, 'core', 'web', 'phone3d.js'), JS),
        '/phone3d.css': (os.path.join(NATIVE, 'core', 'web', 'phone3d.css'), CSS),
    }
    for name in ('Nunito-ExtraBold.ttf', 'Nunito-Light.ttf'):
        static['/fonts/' + name] = (os.path.join(FONTS, name), 'font/ttf')
    for name in ('three.module.js', 'three.core.js'):         # three.js, loaded only when a skin has body3d
        static['/vendor/%s/%s' % (THREE, name)] = (os.path.join(NATIVE, 'core', 'web', 'vendor', THREE, name), JS)
    if a.pyodide:
        for name, kind in PYODIDE.items():
            static['/pyodide/' + name] = (os.path.join(os.path.abspath(a.pyodide), name), kind)
    if a.write:
        made = {'/devices.json': json.dumps(listing).encode(), '/phone_src.json': packed, '/config.json': config}
        return write_site(os.path.abspath(a.write), static, made, firmware, csp)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, fmt, *args):
            pass

        def handle(self):
            try:
                super().handle()
            except (ConnectionResetError, BrokenPipeError):
                pass                                # the page went away during a download (a reload): nothing to say

        def head(self, kind, length):
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(length))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', csp)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()

        def body(self, data, kind):
            self.head(kind, len(data))
            if self.command == 'GET':
                self.wfile.write(data)

        def file(self, path, kind):
            if not os.path.isfile(path):
                return self.send_error(404)
            self.head(kind, os.path.getsize(path))
            if self.command == 'GET':
                with open(path, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile, 1 << 20)

        def do_GET(self):
            path = self.path.split('?')[0]
            if path in static:
                return self.file(*static[path])
            if path == '/devices.json':
                return self.body(json.dumps(listing).encode(), 'application/json')
            if path == '/phone_src.json':
                return self.body(packed, 'application/json')
            if path == '/config.json':
                return self.body(config, 'application/json')
            parts = path[1:].split('/')
            if len(parts) == 2 and parts[0] == 'firmware' and parts[1][:-4] in firmware and parts[1].endswith('.elf'):
                return self.file(firmware[parts[1][:-4]], 'application/octet-stream')
            if len(parts) == 3 and parts[0] == 'skin' and parts[1] in firmware and SKIN_FILE.match(parts[2]):
                kind = 'image/svg+xml' if parts[2].endswith('.svg') else 'application/json'
                return self.file(os.path.join(NATIVE, 'devices', parts[1], 'skin', parts[2]), kind)
            if len(parts) == 2 and parts[0] == 'icons' and ICON_FILE.match(parts[1]):
                return self.file(os.path.join(HERE, 'icons', parts[1]), 'image/png')
            self.send_error(404)

        do_HEAD = do_GET

        def do_POST(self):
            n = min(int(self.headers.get('Content-Length') or 0), 4000)
            text = self.rfile.read(n).decode('utf-8', 'replace')
            if self.path != '/log' or not a.log:
                return self.send_error(404)
            print('%s  %s' % (self.client_address[0], text.replace('\n', ' | ')), flush=True)
            self.send_response(204)
            self.send_header('Content-Length', '0')
            self.end_headers()

    srv = http.server.ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    scheme = 'http'
    if a.cert:
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(a.cert)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        scheme = 'https'
    print('phones: %s' % (', '.join('%s (%d kB, %s)' % (p['name'], p['size'] // 1024, 'modem ' + p['peer'] if p['peer'] else 'no modem')
                                     for p in listing) or 'none (build one: make -C myna/firmware)'), flush=True)
    print('Python source: %d files, %d bytes; core: %s; Pyodide: %s' % (
        len(json.loads(packed)['files']), len(packed), wasm if os.path.isfile(wasm) else 'NOT BUILT (sh native/core/build.sh)',
        os.path.abspath(a.pyodide) if a.pyodide else 'NONE (give --pyodide DIR)'), flush=True)
    print('texts: %s' % ('relay ' + a.relay[0] if a.relay else 'loopback (no --relay)'), flush=True)
    print('%s://%s:%d/' % (scheme, a.host, a.port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
