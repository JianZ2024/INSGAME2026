"""INSGAME2026 local/LAN classroom server. Python 3.10+, no third-party packages."""
import argparse
import csv
import hashlib
import hmac
import io
import json
import mimetypes
import os
import secrets
import time
import threading
from commentary import generate_commentary
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from store import Store

ROOT = Path(__file__).resolve().parent


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, directory, admin_key):
        self.store = Store(directory / 'insgame.sqlite3')
        self.commentary_lock = threading.Lock()
        self.admin_key = admin_key
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'INSGAME2026'

    def log_message(self, fmt, *args):
        # Avoid logging query strings or credentials.
        pass

    def send(self, body, status=200, kind='application/json; charset=utf-8', cookie=None, filename=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if cookie: self.send_header('Set-Cookie', cookie)
        if filename: self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def session(self, required=True):
        c = SimpleCookie()
        try: c.load(self.headers.get('Cookie', ''))
        except Exception: pass
        token = c.get('insgame_session')
        if token:
            digest = hashlib.sha256(token.value.encode()).hexdigest()
            with self.server.store.connection() as db:
                row = db.execute('SELECT body FROM sessions WHERE token=? AND expires>?', (digest, time.time())).fetchone()
            if row: return json.loads(row[0])
        if required: raise PermissionError('Please sign in first.')
        return None

    def new_session(self, actor, credential_revision=None):
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.server.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if actor['role'] == 'student':
                game = self.server.store.read(actor['game_id'], db)
                team = next((t for t in game['teams'] if t['id'] == actor['team_id']), None)
                if not team: raise PermissionError('Team is no longer active.')
                if team.get('password_revision', 0) != credential_revision:
                    raise PermissionError('Team access changed. Please sign in again.')
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest, json.dumps(actor), time.time()+43200))
        return f'insgame_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'

    def do_GET(self):
        try:
            self.get()
        except PermissionError as exc: self.send({'error': str(exc)}, 403)
        except ValueError as exc: self.send({'error': str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception:
            self.send({'error': 'Unable to read server data. Check the data directory or restart the server.'}, 500)

    def get(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == '/api/session':
            self.send({'user': self.session(False)}); return
        if path == '/api/games':
            actor = self.session()
            if actor['role'] != 'teacher': raise PermissionError('Instructor access required.')
            deleted = parse_qs(parsed.query).get('deleted', ['0'])[0] == '1'
            self.send({'games': self.server.store.list_games(deleted=deleted)}); return
        if path in ('/api/game', '/api/export'):
            actor = self.session()
            query = parse_qs(parsed.query)
            game = self.server.store.read(query.get('id', [''])[0])
            visible = Store.view(game, actor)
            if path == '/api/game': self.send(visible); return
            fmt = query.get('format', ['csv'])[0]
            if fmt == 'json':
                if actor['role'] != 'teacher': raise PermissionError('Instructor access required.')
                # Export includes audit and decisions but deliberately excludes login PINs.
                for t in visible['teams']: t.pop('pin', None)
                for h in visible['history']:
                    for t in h.get('starting_teams', []): t.pop('pin', None)
                self.send(visible, filename=f'INSGAME2026-{game["id"]}.json'); return
            buf = io.StringIO(newline='')
            writer = csv.writer(buf)
            writer.writerow(['Round','Team','Market share','Net written premium','After-tax underwriting profit','Investment income','Cash','Total assets','Surplus','Closing surplus score','Cumulative weighted surplus','Round rank','Overall rank','Bond strategy','Annual bond return','Stock strategy','Stock multiplier',*(['Base annual stock return','Annual stock return'] if actor['role']=='teacher' else []),'Low-risk policies','High-risk policies','Low-risk premium','High-risk premium','Low-risk screening','High-risk screening','Low-risk loss ratio','High-risk loss ratio'])
            for h in visible['history']:
                for r in h['results']:
                    writer.writerow([h['period'], r['name'], r['share'], r['net'], r['underwriting'],
                        r['bond_income']+r['stock_income'], r['next_state']['cash'], r['next_state']['assets'],
                        r['next_state']['surplus'], r['score'], r['cumulative'], r['rank'], r['overall_rank'],
                        r.get('bond_strategy',''), r.get('bond_return',h['env'].get('bond_return','')),
                        r.get('stock_strategy',''), r.get('stock_multiplier',''),
                        *([r.get('stock_base_return',''),r.get('stock_return',h['env'].get('stock_return',''))] if actor['role']=='teacher' else []),
                        *[r.get('regions',{}).get(key,{}).get(field,'') for field in ('policies','premium','screening','loss_ratio') for key in ('low','high')]])
            self.send(buf.getvalue().encode('utf-8-sig'), kind='text/csv; charset=utf-8', filename=f'INSGAME2026-{game["id"]}.csv'); return
        files = {'/':'index.html', '/how-to-play':'index.html', '/app.js':'app.js', '/dashboard.js':'dashboard.js', '/investment.js':'investment.js', '/market.js':'market.js', '/style.css':'style.css', '/favicon.svg':'favicon.svg'}
        if path == '/rules':
            self.send((ROOT/'RULES.md').read_bytes(), kind='text/plain; charset=utf-8'); return
        if path not in files:
            self.send({'error':'Page not found.'},404); return
        file = ROOT/'static'/files[path]
        self.send(file.read_bytes(), kind=(mimetypes.guess_type(str(file))[0] or 'application/octet-stream')+'; charset=utf-8')

    def do_POST(self):
        try:
            # Custom same-origin header blocks cross-site form posts; no CORS is enabled.
            if self.headers.get('X-INSGAME') != '1': raise PermissionError('Invalid request origin.')
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                raise PermissionError('Invalid request origin.')
            size = int(self.headers.get('Content-Length', '0'))
            if size < 0 or size > 100000: raise ValueError('Request is too large.')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict): raise ValueError('Invalid request format.')
            self.post(urlsplit(self.path).path, data)
        except PermissionError as exc: self.send({'error':str(exc)},403)
        except (ValueError, KeyError, TypeError) as exc:
            self.send({'error':str(exc) if isinstance(exc, ValueError) else 'Missing or invalid input.'},400)
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception:
            self.send({'error':'The change was not saved. Refresh and try again.'},500)

    def post(self, path, data):
        if path == '/api/login':
            revision = None
            if data.get('role') == 'teacher':
                if not hmac.compare_digest(str(data.get('password', '')).encode(), self.server.admin_key.encode()):
                    raise PermissionError('Incorrect instructor password. Check admin_key.txt in the data directory or the configured INSGAME_ADMIN_KEY.')
                actor = {'role':'teacher'}
            else:
                try:
                    game_id = str(data.get('code', '')).strip().upper()
                    tid = int(data.get('team_id', 0))
                    revision = self.server.store.verify_team(game_id, tid, str(data.get('pin', '')))
                except (ValueError, StopIteration):
                    raise PermissionError('Incorrect game code, team number, or team password.') from None
                actor = {'role':'student','game_id':game_id,'team_id':tid}
            self.send({'user':actor},cookie=self.new_session(actor, revision)); return
        if path == '/api/logout':
            c = SimpleCookie(self.headers.get('Cookie',''))
            if c.get('insgame_session'):
                digest = hashlib.sha256(c['insgame_session'].value.encode()).hexdigest()
                with self.server.store.connection() as db: db.execute('DELETE FROM sessions WHERE token=?',(digest,))
            self.send({'ok':True},cookie='insgame_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'); return
        actor = self.session()
        if path == '/api/commentary':
            if actor['role'] != 'teacher': raise PermissionError('Instructor access required.')
            game_id, period = data.get('game_id'), data.get('period')
            if type(period) is not int: raise ValueError('Select a calculated round.')
            if not self.server.commentary_lock.acquire(blocking=False):
                raise ValueError('A commentary is being generated. Try again shortly.')
            try:
                store = self.server.store
                game = store.read(game_id)
                record = next((h for h in game['history'] if h['period']==period), None)
                if record is None: raise ValueError('Select a calculated round.')
                comment = record.get('ai_commentary')
                if not comment:
                    comment = generate_commentary(record)
                    # The provider call is outside the write transaction. Merge only the
                    # note into a fresh copy so concurrent decisions are never overwritten.
                    with store.connection() as db:
                        db.execute('BEGIN IMMEDIATE')
                        game = store.read(game_id, db)
                        next(h for h in game['history'] if h['period']==period)['ai_commentary'] = comment
                        game['revision'] += 1
                        db.execute('UPDATE games SET body=? WHERE id=?', (json.dumps(game),game_id))
            finally:
                self.server.commentary_lock.release()
            self.send({'commentary': comment}); return
        if path == '/api/team-password':
            token = SimpleCookie(self.headers.get('Cookie',''))['insgame_session'].value
            self.send(self.server.store.team_password(actor, hashlib.sha256(token.encode()).hexdigest(), data)); return
        if path == '/api/create':
            if actor['role'] != 'teacher': raise PermissionError('Instructor access required.')
            self.send(self.server.store.create(data)); return
        if path == '/api/classroom':
            g = self.server.store.classroom_action(str(data.get('game_id', '')), actor,
                                                  data.get('action'), data.get('revision'))
            self.send({'id': g['id'], 'deleted': bool(g.get('deleted_at'))}); return
        if path == '/api/action':
            g = self.server.store.mutate(str(data.get('game_id','')),actor,data.get('action'),data)
            self.send(Store.view(g,actor)); return
        self.send({'error':'Unknown action.'},404)


def main():
    parser = argparse.ArgumentParser(description='INSGAME2026 classroom insurance market')
    parser.add_argument('--host', default='127.0.0.1', help='Use 0.0.0.0 for classroom LAN access')
    parser.add_argument('--port', type=int, default=2026)
    parser.add_argument('--data-dir', type=Path, default=ROOT/'data')
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    keyfile = args.data_dir/'admin_key.txt'
    if not keyfile.exists(): keyfile.write_text(secrets.token_urlsafe(12),encoding='utf-8')
    key = os.environ.get('INSGAME_ADMIN_KEY') or keyfile.read_text(encoding='utf-8').strip()
    if len(key) < 8: parser.error('Teacher password must have at least 8 characters')
    try: server = Server((args.host,args.port),args.data_dir,key)
    except OSError as exc: parser.exit(1,f'Cannot start server: {exc}\nTry another --port.\n')
    key_source = ('environment variable INSGAME_ADMIN_KEY' if os.environ.get('INSGAME_ADMIN_KEY')
                  else 'admin_key.txt in the data directory')
    print(f'\nINSGAME2026\nBrowser: http://localhost:{args.port}\nTeacher password source: {key_source}\nData: {args.data_dir.resolve()}\nPress Ctrl+C to stop.\n',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == '__main__': main()
