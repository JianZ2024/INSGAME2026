"""Transactional game lifecycle and role-filtered views."""
import copy
import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from engine import DEFAULT_DECISION, DEFAULT_ENV, DEFAULT_ROUNDS, MAX_ROUNDS, RULES_VERSION, WEIGHT_RULE, INVESTMENT_RULE, MODEL_RULE, PREMIUM_RULE, calculate_round, initial_state, number, round_weights, rank_results, validate_decision, validate_env


def now():
    return datetime.now(timezone.utc).isoformat()


def with_rounds(game):
    """Expose the current weight schedule; missing round counts default to five."""
    game.setdefault('total_rounds', DEFAULT_ROUNDS)
    game['round_weights'] = round_weights(game['total_rounds'])
    return game


def reweight_game(game):
    """Rebuild scoring from stored round scores without recalculating finances."""
    previous_rules = game.get('rules', '2026.1')
    game = with_rounds(game)
    cumulative = {t['id']: 0. for t in game['teams']}
    opening = cumulative.copy()
    for h in game['history']:
        for t in h.get('starting_teams', []):
            t['state']['cumulative'] = cumulative[t['id']]
        weight = game['round_weights'][h['period'] - 1]
        for r in h['results']:
            tid = r['team_id']
            cumulative[tid] += weight * r['score']
            r['cumulative'] = r['next_state']['cumulative'] = cumulative[tid]
        rank_results(h['results'])
        h['weight'] = weight
        h.setdefault('calculation_rules', h.get('rules', previous_rules))
        h['rules'] = RULES_VERSION
        if h['period'] < game['period']:
            opening = cumulative.copy()
    for t in game['teams']:
        t['state']['cumulative'] = opening[t['id']]
    game['rules'] = RULES_VERSION
    game['weight_rule'] = WEIGHT_RULE
    game['revision'] += 1
    game['audit'].append(dict(at=now(), action='reweighted', period=game['period'],
                             actor='system', previous_rules=previous_rules, weight_rule=WEIGHT_RULE))
    return game


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS games (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS team_passwords (game_id TEXT, team_id INTEGER, salt BLOB NOT NULL, digest BLOB NOT NULL, PRIMARY KEY(game_id,team_id))')
            db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, body TEXT NOT NULL, expires REAL NOT NULL)')
        self.upgrade_weights()
        self.upgrade_investments()
        self.upgrade_market_model()
        self.upgrade_premiums()

    def upgrade_premiums(self):
        """Replace untouched starting quotes; preserve saved choices and history."""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = [g for (body,) in db.execute('SELECT body FROM games')
                       if (g := json.loads(body)).get('premium_rule') != PREMIUM_RULE]
            if not pending:
                return
            backup = Path(self.path).with_name(Path(self.path).name + '.before-premiums-2026.6-' + secrets.token_hex(4) + '.bak')
            with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(backup)) as target:
                source.backup(target)
            for g in pending:
                if g['phase'] in ('open', 'locked'):
                    for d in g['decisions'].values():
                        if not g['history'] and not d['saved_at'] and not d['submitted']:
                            for key, old in (('low_premium', 4000), ('high_premium', 8000)):
                                if d['values'][key] == old:
                                    d['values'][key] = DEFAULT_DECISION[key]
                        # Claims and appeal use new reference prices: require review,
                        # and reject stale forms without replacing saved numeric inputs.
                        d['submitted'] = False
                        d['saved_at'] = now()
                    g['phase'] = 'open'
                    g['premium_updated_period'] = g['period']
                else:
                    g['premium_updated_period'] = g['period'] + 1
                g['premium_rule'] = PREMIUM_RULE
                g['rules'] = RULES_VERSION
                g['revision'] += 1
                g['audit'].append(dict(at=now(), action='premium_defaults_updated',
                                       period=g['period'], actor='system'))
                db.execute('UPDATE games SET body=? WHERE id=?', (json.dumps(g, allow_nan=False), g['id']))

    def upgrade_market_model(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = [g for (body,) in db.execute('SELECT body FROM games')
                       if (g := json.loads(body)).get('model_rule') != MODEL_RULE]
            if not pending:
                return
            backup = Path(self.path).with_name(Path(self.path).name + '.before-regions-2026.5-' + secrets.token_hex(4) + '.bak')
            with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(backup)) as target:
                source.backup(target)
            for g in pending:
                g['env'].pop('market', None)
                g['env'].setdefault('market_growth', DEFAULT_ENV['market_growth'])
                g['risk_seed'] = secrets.token_hex(16)
                g['market'] = dict(initial_premium=5_000_000*len(g['teams']), policies=1000*len(g['teams']))
                for d in g['decisions'].values():
                    old_price = d['values'].pop('price', 100)
                    d['values'].setdefault('low_premium',old_price)
                    d['values'].setdefault('high_premium',old_price*1.5)
                    for key in ('low_pct','high_pct','low_screening','high_screening'):
                        d['values'].setdefault(key,DEFAULT_DECISION[key])
                    d['saved_at'] = now()
                    if g['phase'] in ('open','locked'):d['submitted'] = False
                if not g['history']:
                    for t in g['teams']:t['state'] = initial_state()
                # Preserve financial results and the old scoring figures for audit.
                for h in g['history']:
                    for r in h['results']:
                        r.setdefault('legacy_score',r['score'])
                        r.setdefault('legacy_cumulative',r['cumulative'])
                        r['score'] = r['next_state']['surplus']
                g = reweight_game(g)
                if g['phase']=='locked':g['phase']='open'
                g['model_rule'] = MODEL_RULE
                g['model_updated_period'] = g['period']
                g['opening_book_preserved'] = bool(g['history'])
                g['audit'].append(dict(at=now(),action='two_region_model_updated',period=g['period'],actor='system'))
                db.execute('UPDATE games SET body=? WHERE id=?',(json.dumps(g,allow_nan=False),g['id']))

    def upgrade_investments(self):
        """Preserve calculated rounds; require confirmation of new decision fields."""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = [g for (body,) in db.execute('SELECT body FROM games')
                       if (g := json.loads(body)).get('investment_rule') != INVESTMENT_RULE]
            if not pending:
                return
            backup = Path(self.path).with_name(Path(self.path).name + '.before-investments-2026.4-' + secrets.token_hex(4) + '.bak')
            with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(backup)) as target:
                source.backup(target)
            for g in pending:
                previous_rules = g.get('rules', '2026.3')
                g['env'].pop('bond_return', None)
                g['env'].setdefault('stock_return', DEFAULT_ENV['stock_return'])
                for d in g['decisions'].values():
                    for key in ('bond_strategy', 'stock_strategy'):
                        d['values'].setdefault(key, DEFAULT_DECISION[key])
                    if g['phase'] in ('open', 'locked'):
                        d['submitted'] = False
                    # Reject stale forms, including ones opened before the upgrade.
                    d['saved_at'] = now()
                if g['phase'] == 'locked':
                    g['phase'] = 'open'
                g['investment_updated_period'] = g['period']
                g['investment_rule'] = INVESTMENT_RULE
                g['rules'] = RULES_VERSION
                g['revision'] += 1
                g['audit'].append(dict(at=now(), action='investment_rules_updated',
                                      period=g['period'], actor='system', previous_rules=previous_rules))
                db.execute('UPDATE games SET body=? WHERE id=?',
                           (json.dumps(g, allow_nan=False), g['id']))

    def upgrade_weights(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = [g for (body,) in db.execute('SELECT body FROM games')
                       if (g := json.loads(body)).get('weight_rule') != WEIGHT_RULE]
            if not pending:
                return
            # A separate read connection can back up committed data while this
            # transaction prevents concurrent writes. No game changes precede backup.
            backup = Path(self.path).with_name(Path(self.path).name + '.before-weights-2026.3-' + secrets.token_hex(4) + '.bak')
            with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(backup)) as target:
                source.backup(target)
            for game in pending:
                updated = reweight_game(game)
                db.execute('UPDATE games SET body=? WHERE id=?',
                           (json.dumps(updated, allow_nan=False), updated['id']))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self, game_id, db=None, include_deleted=False):
        if db is None:
            with self.connection() as conn:
                return self.read(game_id, conn, include_deleted)
        row = db.execute('SELECT body FROM games WHERE id=?', (game_id,)).fetchone()
        if not row: raise ValueError('Game not found.')
        game = with_rounds(json.loads(row[0]))
        if game.get('deleted_at') and not include_deleted:
            raise ValueError('This classroom has been deleted. Ask the instructor to restore it.')
        return game

    def verify_team(self, game_id, team_id, password):
        # Read one consistent snapshot. Password derivation does not hold a write lock.
        with self.connection() as db:
            db.execute('BEGIN')
            game = self.read(game_id, db)
            team = next(t for t in game['teams'] if t['id'] == team_id)
            revision = team.get('password_revision', 0)
            if team.get('pin'):
                valid = hmac.compare_digest(team['pin'].encode(), password.strip().upper().encode())
            else:
                row = db.execute('SELECT salt, digest FROM team_passwords WHERE game_id=? AND team_id=?',
                                 (game_id, team_id)).fetchone()
                valid = row and len(password) <= 128 and hmac.compare_digest(
                    row[1], hashlib.pbkdf2_hmac('sha256', password.encode(), row[0], 600_000))
        if not valid:
            raise ValueError('Invalid team credentials.')
        return revision

    def team_password(self, actor, token_digest, data):
        action = data.get('action')
        game_id, team_id = data.get('game_id'), data.get('team_id')
        if action == 'reset':
            if actor['role'] != 'teacher': raise PermissionError('Instructor access required.')
        elif action in ('set', 'skip'):
            if actor != dict(role='student', game_id=game_id, team_id=team_id):
                raise PermissionError('You can only set up your own team password.')
        else:
            raise ValueError('Unknown password action.')
        if action == 'set':
            password = data.get('password')
            if not isinstance(password, str) or not 8 <= len(password) <= 128 or not password.strip():
                raise ValueError('Use a team password of 8 to 128 characters.')
            salt = secrets.token_bytes(16)
            digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            # A reset in another request may have revoked this session.
            if not db.execute("SELECT 1 FROM sessions WHERE token=? AND expires>strftime('%s','now')", (token_digest,)).fetchone():
                raise PermissionError('Please sign in again.')
            game = self.read(game_id, db)
            team = next((t for t in game['teams'] if t['id'] == team_id), None)
            if not team: raise ValueError('Unknown team.')
            revision = team.get('password_revision', 0)
            if data.get('password_revision') != revision:
                raise ValueError('Team access changed. Refresh before trying again.')
            if action != 'reset' and team.get('password_setup') == 'custom':
                raise ValueError('Team password setup is already complete.')
            if action == 'reset':
                team['pin'] = secrets.token_hex(4).upper()
                db.execute('DELETE FROM team_passwords WHERE game_id=? AND team_id=?', (game_id, team_id))
            elif action == 'set':
                db.execute('INSERT INTO team_passwords VALUES (?, ?, ?, ?)', (game_id, team_id, salt, digest))
                team.pop('pin', None)
            if action != 'skip':
                target = dict(role='student', game_id=game_id, team_id=team_id)
                sessions = [(key,) for key, body in db.execute('SELECT token, body FROM sessions')
                            if key != token_digest and json.loads(body) == target]
                db.executemany('DELETE FROM sessions WHERE token=?', sessions)
            team['password_setup'] = {'set':'custom', 'skip':'skipped', 'reset':'pending'}[action]
            team['password_revision'] = revision + 1
            game['revision'] += 1
            game['audit'].append(dict(at=now(), action='team_password_' + action, team_id=team_id,
                                      actor=actor['role'], period=game['period']))
            db.execute('UPDATE games SET body=? WHERE id=?', (json.dumps(game), game_id))
            return self.view(game, actor)

    def list_games(self, deleted=False):
        with self.connection() as db:
            games = [json.loads(r[0]) for r in db.execute('SELECT body FROM games ORDER BY rowid DESC')]
        return [dict(id=g['id'], name=g['name'], period=g['period'], phase=g['phase'],
                     count=len(g['teams']), total_rounds=g.get('total_rounds', DEFAULT_ROUNDS),
                     revision=g['revision'], deleted_at=g.get('deleted_at'))
                for g in games if bool(g.get('deleted_at')) == deleted]

    def classroom_action(self, game_id, actor, action, revision):
        if actor.get('role') != 'teacher':
            raise PermissionError('Instructor access required.')
        if action not in ('delete', 'restore'):
            raise ValueError('Unknown classroom action.')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            g = self.read(game_id, db, include_deleted=True)
            if revision != g['revision']:
                raise ValueError('The classroom has changed. Refresh and try again.')
            if action == 'delete':
                if g.get('deleted_at'): raise ValueError('This classroom is already deleted.')
                g['deleted_at'] = now()
                # End only the deleted classroom's student sessions.
                tokens = [(token,) for token, body in db.execute('SELECT token,body FROM sessions')
                          if json.loads(body).get('game_id') == game_id]
                db.executemany('DELETE FROM sessions WHERE token=?', tokens)
            else:
                if not g.get('deleted_at'): raise ValueError('This classroom is not deleted.')
                g.pop('deleted_at')
            g['revision'] += 1
            g['audit'].append(dict(at=now(), action='classroom_' + action, period=g['period'], actor='teacher'))
            db.execute('UPDATE games SET body=? WHERE id=?', (json.dumps(g, allow_nan=False), game_id))
            return g

    def create(self, data):
        n = number(data.get('teams', 5), 'Number of teams', 2, 20, True)
        total_rounds = number(data.get('total_rounds', DEFAULT_ROUNDS), 'Number of rounds', 1, MAX_ROUNDS, True)
        name = str(data.get('name', '')).strip()[:60] or 'Insurance Market Lab'
        demo = data.get('demo') is True
        game = dict(id=secrets.token_hex(3).upper(), name=name, period=1, phase='open',
                    revision=0, rules=RULES_VERSION, created=now(), env=DEFAULT_ENV.copy(),
                    total_rounds=total_rounds, round_weights=round_weights(total_rounds), weight_rule=WEIGHT_RULE,
                    investment_rule=INVESTMENT_RULE,
                    premium_rule=PREMIUM_RULE,
                    model_rule=MODEL_RULE, risk_seed=secrets.token_hex(16),
                    market=dict(initial_premium=5_000_000*n, policies=1000*n),
                    teams=[], decisions={}, history=[], audit=[])
        for i in range(1, n+1):
            team = dict(id=i, name=f'Team {i:02}', pin=secrets.token_hex(4).upper(), rating=1, state=initial_state())
            game['teams'].append(team)
            d = DEFAULT_DECISION.copy()
            if demo:
                j=(i-1)%5
                d.update(low_premium=[105,100,95,110,98][j],
                         high_premium=[150,157.5,142.5,147,165][j],
                         low_pct=[.85,.75,.4,.9,.6][j], high_pct=1-[.85,.75,.4,.9,.6][j],
                         strategy=[3,4,6,2,5][j], advertising=25000+i*5000, promotion=i*5000)
            game['decisions'][str(i)] = dict(values=d, submitted=demo, saved_at=now() if demo else None)
        game['audit'].append(dict(at=now(), action='created', period=1, actor='teacher'))
        with self.connection() as db:
            db.execute('INSERT INTO games VALUES (?, ?)', (game['id'], json.dumps(game)))
        return game

    def mutate(self, game_id, actor, action, data):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            g = self.read(game_id, db)
            teacher = actor.get('role') == 'teacher'
            if not teacher and actor.get('game_id') != game_id:
                raise PermissionError('You do not have access to this game.')
            if data.get('period') != g['period']:
                raise ValueError('The round has changed. Refresh and try again.')
            # Team edits do not conflict with another team's submission. Teacher actions
            # require a fresh revision so configuration/settlement never uses a stale view.
            if action != 'decision' and data.get('revision') != g['revision']:
                raise ValueError('The game has changed. Refresh and try again.')
            if action == 'decision':
                if g['phase'] != 'open': raise ValueError('This round is locked. Decisions cannot be edited.')
                team_id = int(number(data.get('team_id'), 'Team', 1, len(g['teams']), True))
                if not teacher and team_id != actor.get('team_id'):
                    raise PermissionError('You can only edit your own team decisions.')
                current = g['decisions'][str(team_id)]
                if data.get('saved_at') != current['saved_at']:
                    raise ValueError('These decisions were edited in another window. Refresh and try again.')
                g['decisions'][str(team_id)] = dict(values=validate_decision(data.get('values', {})),
                                                    submitted=data.get('submitted') is True, saved_at=now())
            else:
                if not teacher: raise PermissionError('Instructor access required.')
                if action == 'rounds':
                    if g['phase'] != 'open' or g['history']:
                        raise ValueError('The number of rounds can only be changed before the first calculation, while submissions are open.')
                    g['total_rounds'] = number(data.get('total_rounds'), 'Number of rounds', 1, MAX_ROUNDS, True)
                    g['round_weights'] = round_weights(g['total_rounds'])
                    g['rules'] = RULES_VERSION
                elif action == 'environment':
                    if g['phase'] != 'open': raise ValueError('Market conditions can only be changed while submissions are open.')
                    g['env'] = validate_env(data.get('env', {}))
                    ratings = data.get('ratings', {})
                    for t in g['teams']:
                        t['rating'] = number(ratings.get(str(t['id']), t['rating']), 'Rating', 1, 5, True)
                elif action == 'lock':
                    if g['phase'] != 'open': raise ValueError('This round is already locked.')
                    if not all(d['submitted'] for d in g['decisions'].values()):
                        raise ValueError('All teams must submit first. The instructor may submit on their behalf.')
                    for d in g['decisions'].values():
                        validate_decision(d['values'])
                    g['phase'] = 'locked'
                elif action == 'unlock':
                    if g['phase'] != 'locked': raise ValueError('Only rounds that have not been calculated can be unlocked.')
                    g['phase'] = 'open'
                elif action == 'settle':
                    if g['phase'] != 'locked': raise ValueError('Lock decisions first. Each round can only be calculated once.')
                    results = calculate_round(g['env'], g['teams'], g['decisions'], g['period'], g['total_rounds'],
                                              g['market']['policies'], g['risk_seed'])
                    g['history'].append(dict(period=g['period'], env=copy.deepcopy(g['env']),
                        market=dict(potential_policies=g['market']['policies'],
                                    total_policies=sum(r['policies'] for r in results),
                                    total_premium=sum(r['gross'] for r in results),
                                    next_policies=sum(r['policies'] for r in results)*(1+g['env']['market_growth'])),
                        weight=g['round_weights'][g['period'] - 1],
                        starting_teams=[{k:v for k,v in t.items() if k not in ('pin','password_setup','password_revision')} for t in g['teams']], decisions=copy.deepcopy(g['decisions']),
                        results=results, published=False, settled_at=now(), rules=g['rules']))
                    g['phase'] = 'settled'
                elif action == 'publish':
                    if g['phase'] != 'settled': raise ValueError('Calculate the round first.')
                    g['history'][-1]['published'] = True
                    g['phase'] = 'finished' if g['period'] >= g['total_rounds'] else 'published'
                elif action == 'next':
                    if g['phase'] != 'published' or g['period'] >= g['total_rounds']:
                        raise ValueError('Publish results first. No round can follow the final round.')
                    by_id = {r['team_id']: r for r in g['history'][-1]['results']}
                    for t in g['teams']:
                        t['state'] = by_id[t['id']]['next_state']
                    g['period'] += 1
                    if 'market' in g['history'][-1]:
                        g['market']['policies'] = g['history'][-1]['market']['next_policies']
                    g['phase'] = 'open'
                    for d in g['decisions'].values():
                        d['submitted'] = False
                        d['saved_at'] = now()
                else:
                    raise ValueError('Unknown action.')
            g['revision'] += 1
            g['audit'].append(dict(at=now(), action=action, period=g['period'],
                                   actor='teacher' if teacher else f"team:{actor['team_id']}"))
            db.execute('UPDATE games SET body=? WHERE id=?', (json.dumps(g, allow_nan=False), game_id))
            return g

    @staticmethod
    def view(g, actor):
        if g.get('deleted_at'):
            raise ValueError('This classroom has been deleted. Ask the instructor to restore it.')
        g = with_rounds(copy.deepcopy(g))
        for h in g['history']:
            for t in h.get('starting_teams', []): t.pop('pin', None)
        if actor.get('role') == 'teacher': return g
        if actor.get('game_id') != g['id']: raise PermissionError('You do not have access to this game.')
        tid = actor['team_id']
        for t in g['teams']:
            t.pop('pin', None)
            if t['id'] != tid:
                t.pop('state', None)
        g['decisions'] = {str(tid): g['decisions'][str(tid)]}
        history = []
        for h in g['history']:
            if not h['published']: continue
            board = [dict(team_id=r['team_id'], name=r['name'], share=r['share'], surplus=r['next_state']['surplus'],
                          score=r['score'], cumulative=r['cumulative'], rank=r['rank'],
                          overall_rank=r['overall_rank']) for r in h['results']]
            history.append(dict(period=h['period'], env=h['env'], market=h.get('market'), published=True, rules=h['rules'],
                                weight=h.get('weight', g['round_weights'][h['period'] - 1]),
                                results=[r for r in h['results'] if r['team_id']==tid], leaderboard=board))
        g['history'] = history
        g.pop('audit', None)
        g.pop('risk_seed', None)
        return g
