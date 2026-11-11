import copy
import csv
import io
import json
import math
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from app import Server
from engine import DEFAULT_DECISION, DEFAULT_ENV, calculate_round, validate_decision, validate_env, renewal_factor, round_weights, WEIGHT_RULE, RULES_VERSION
from store import Store, reweight_game

TEACHER = {'role':'teacher'}


class GameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'game.db')
        self.g = self.store.create({'name':'Test','teams':5})

    def tearDown(self): self.temp.cleanup()

    def move(self, action, **kw):
        self.g = self.store.mutate(self.g['id'],TEACHER,action,dict(period=self.g['period'],revision=self.g['revision'],**kw))
        return self.g

    def test_roster_and_return_across_rounds(self):
        self.g = self.store.create(dict(teams=3, demo=True, stock_return=-.08))
        removed = dict(role='student', game_id=self.g['id'], team_id=2)
        self.move('lock')
        with self.assertRaises(ValueError): self.move('remove_team', team_id=2)
        self.move('settle')
        previous = copy.deepcopy(self.g['history'][0]['results'])
        self.assertAlmostEqual(previous[0]['stock_base_return'], -.08)
        self.move('publish')
        self.move('next')
        potential = self.g['market']['policies']
        self.move('remove_team', team_id=2)
        with self.assertRaises(PermissionError): self.store.view(self.g, removed)
        self.assertAlmostEqual(self.g['market']['policies'], potential * 2 / 3)
        with self.assertRaises(ValueError): self.move('remove_team', team_id=1)
        self.move('add_team')
        self.assertEqual([t['id'] for t in self.g['teams']], [1,3,4])
        self.assertAlmostEqual(self.g['market']['policies'], potential)
        self.assertEqual(self.store.view(self.g, dict(removed, team_id=4))['history'], [])
        self.assertEqual(self.g['teams'][-1]['state']['cumulative'], 0)
        self.submit_all()
        self.move('environment', env=dict(self.g['env'], stock_return=.20))
        self.assertFalse(any(d['submitted'] for d in self.g['decisions'].values()))
        self.submit_all()
        self.move('lock')
        self.move('settle')
        self.assertEqual(previous, self.g['history'][0]['results'])
        for row in self.g['history'][1]['results']:
            self.assertAlmostEqual(row['stock_return'], .2 * row['stock_multiplier'])
        self.assertEqual({r['team_id'] for r in self.g['history'][1]['results']}, {1,3,4})

    def test_roster_limits_and_access(self):
        self.g = self.store.create(dict(teams=20, demo=True))
        with self.assertRaises(ValueError): self.move('add_team')
        actor = dict(role='student', game_id=self.g['id'], team_id=1)
        with self.assertRaises(PermissionError):
            self.store.mutate(self.g['id'], actor, 'remove_team', dict(period=1, revision=0, team_id=2))
        self.move('remove_team', team_id=20)
        self.assertEqual(self.g['market'], dict(initial_premium=95_000_000, policies=19000))
        self.move('add_team')
        self.assertEqual(self.g['teams'][-1]['id'],21)
        self.assertEqual(len(self.g['decisions']),20)
        with self.assertRaises(ValueError): self.store.create(dict(stock_return=1.01))

    def submit_all(self):
        for t in self.g['teams']:
            d = self.g['decisions'][str(t['id'])]
            self.move('decision',team_id=t['id'],values=d['values'],saved_at=d['saved_at'],submitted=True)

    def test_symmetric_hand_calculation(self):
        # Independently calculated equal five-company case from RULES.md.
        with patch('engine.regional_shock', return_value=1.):
            rs = calculate_round(DEFAULT_ENV,self.g['teams'],self.g['decisions'],1)
        for r in rs:
            self.assertAlmostEqual(r['share'],.2)
            # 750 * 100 + 250 * 150 = 112,500 gross. Opening net is 4.5m;
            # earned = 101,250 - .27 * (101,250 - 4,500,000).
            self.assertAlmostEqual(r['net'],101_250)
            self.assertAlmostEqual(r['earned'],1_288_912.5)
            self.assertAlmostEqual(r['underwriting'],355_029.101625)
            self.assertAlmostEqual(r['bond_income'],183_230.25)
            self.assertAlmostEqual(r['stock_income'],121_948.2)
            self.assertAlmostEqual(r['next_state']['assets'],6_751_707.551625)
            self.assertAlmostEqual(r['next_state']['surplus'],4_413_620.051625)
            self.assertAlmostEqual(r['score'],4_413_620.051625)
            self.assertEqual(r['rank'],1)

    def test_zero_spending_full_cash_and_reinsurance(self):
        for d in self.g['decisions'].values():
            d['values'].update(advertising=0,promotion=0,new_commission=0,renewal_commission=0,
                               cash_pct=1,bond_pct=0,stock_pct=0,reinsurance=1)
        rs = calculate_round(DEFAULT_ENV,self.g['teams'],self.g['decisions'],1)
        self.assertAlmostEqual(sum(r['share'] for r in rs),1)
        for r in rs:
            self.assertEqual(r['net'],0)
            self.assertEqual(r['bond_income']+r['stock_income'],0)
            self.assertEqual(r['next_state']['bonds']+r['next_state']['stocks'],0)
            self.assertAlmostEqual(r['next_state']['assets'],r['next_state']['cash'])

    def test_validation(self):
        for k,v in [('low_premium',49),('strategy',2.5),('advertising',-1),('cash_pct',.5),('low_premium',float('nan'))]:
            with self.subTest(k=k,v=v),self.assertRaises(ValueError):
                validate_decision(dict(DEFAULT_DECISION,**{k:v}))
        self.assertEqual(renewal_factor(7),.42)
        self.assertAlmostEqual(renewal_factor(7.5),.395)
        self.assertEqual(renewal_factor(21),.04)
        with self.assertRaises(ValueError): validate_env(dict(DEFAULT_ENV,catastrophe=float('inf')))

    def test_round_count_validation_and_default(self):
        self.assertEqual(self.g['total_rounds'], 5)
        for actual, numerator in zip(self.g['round_weights'], (16,20,25,30,36)):
            self.assertAlmostEqual(actual,numerator/127)
        for invalid in (0, -1, 100, 1.5, True, False, None, '', 'abc', float('nan'), float('inf')):
            with self.subTest(total_rounds=invalid):
                with self.assertRaises(ValueError): self.store.create({'total_rounds': invalid})
                with self.assertRaises(ValueError): round_weights(invalid)
        for count in (1, 3, 6, 99):
            weights = round_weights(count)
            self.assertEqual(len(weights), count)
            self.assertAlmostEqual(sum(weights), 1)
            self.assertTrue(all(w > 0 for w in weights))
            for invalid_period in (0, count+1, 1.5):
                with self.assertRaises(ValueError):
                    calculate_round(DEFAULT_ENV,self.g['teams'],self.g['decisions'],invalid_period,count)

    def test_round_schedule_permissions_and_freeze(self):
        student = dict(role='student', game_id=self.g['id'], team_id=1)
        payload = dict(period=1, revision=0, total_rounds=6)
        with self.assertRaises(PermissionError): self.store.mutate(self.g['id'],student,'rounds',payload)
        self.move('rounds', total_rounds=6)
        for actual, numerator in zip(self.g['round_weights'], (16,20,25,25,30,36)):
            self.assertAlmostEqual(actual,numerator/152)
        with self.assertRaises(ValueError): self.store.mutate(self.g['id'],TEACHER,'rounds',payload)
        with self.assertRaises(ValueError): self.move('rounds', total_rounds=100)
        self.assertEqual(self.store.read(self.g['id'])['total_rounds'],6)
        self.submit_all(); self.move('lock')
        with self.assertRaises(ValueError): self.move('rounds', total_rounds=3)
        self.move('unlock'); self.move('rounds', total_rounds=3)
        self.assertEqual(self.g['total_rounds'],3)
        self.move('lock'); self.move('settle')
        before = copy.deepcopy(self.g)
        with self.assertRaises(ValueError): self.move('rounds', total_rounds=6)
        self.assertEqual(self.store.read(self.g['id']), before)
        self.move('publish'); self.move('next')
        with self.assertRaises(ValueError): self.move('rounds', total_rounds=6)

    def test_custom_round_lifecycles(self):
        for count in (1, 3, 6, 99):
            with self.subTest(total_rounds=count):
                self.g = self.store.create({'teams':2,'total_rounds':count})
                expected = {1:0, 2:0}
                for period in range(1,count+1):
                    self.submit_all(); self.move('lock'); self.move('settle')
                    h = self.g['history'][-1]
                    self.assertEqual(h['weight'],round_weights(count)[period-1])
                    for r in h['results']:
                        expected[r['team_id']] += r['score']*round_weights(count)[period-1]
                        self.assertAlmostEqual(r['cumulative'],expected[r['team_id']],delta=max(1,abs(r['cumulative']))*1e-12)
                    self.move('publish')
                    self.assertEqual(self.g['phase'],'finished' if period==count else 'published')
                    if period<count: self.move('next')
                self.assertEqual(len(self.g['history']),count)
                with self.assertRaises(ValueError): self.move('next')
                with self.assertRaises(ValueError): self.move('settle')
                restored = Store(Path(self.temp.name)/'game.db').read(self.g['id'])
                self.assertEqual(restored,self.g)
                student = Store.view(restored,dict(role='student',game_id=self.g['id'],team_id=1))
                self.assertEqual(student['total_rounds'],count)
                self.assertEqual(len(student['history']),count)
                self.assertEqual(student['history'][-1]['weight'],round_weights(count)[-1])

    def test_median_weight_examples_and_all_lengths(self):
        # Independent hand-derived integer ratios, including the even middle pair.
        examples = {1:([1],1),2:([1,1],2),3:([4,5,6],15),
                    4:([4,5,5,6],20),5:([16,20,25,30,36],127),
                    6:([16,20,25,25,30,36],152)}
        for count,(numerators,denominator) in examples.items():
            for actual,numerator in zip(round_weights(count),numerators):
                self.assertAlmostEqual(actual,numerator/denominator)
        for count in range(1,100):
            with self.subTest(total_rounds=count):
                w=round_weights(count)
                self.assertAlmostEqual(math.fsum(w),1)
                self.assertTrue(all(math.isfinite(x) and x>0 for x in w))
                left,right=(count-1)//2,count//2
                for i in range(left): self.assertAlmostEqual(w[i]/w[i+1],.8)
                for i in range(right+1,count): self.assertAlmostEqual(w[i]/w[i-1],1.2)
                self.assertEqual(w[left],w[right])

    def test_saved_games_reweighted_with_backup_and_resume(self):
        for count in (5,6):
            for phase in ('open','locked','settled','published','finished'):
                with self.subTest(total_rounds=count,phase=phase):
                    self.g=self.store.create(dict(teams=2,total_rounds=count,demo=True))
                    completed=count if phase=='finished' else 2
                    for period in range(1,completed+1):
                        self.submit_all(); self.move('lock'); self.move('settle')
                        if period<completed or phase!='settled': self.move('publish')
                        if period<completed: self.move('next')
                    if phase in ('open','locked'):
                        self.move('next')
                        if phase=='locked': self.submit_all(); self.move('lock')
                    current=copy.deepcopy(self.g)
                    legacy=copy.deepcopy(current)
                    old_weights=[.15,.15,.2,.2,.3] if count==5 else [1/count]*count
                    legacy.pop('weight_rule')
                    legacy['round_weights']=old_weights
                    legacy['rules']='2026.1' if count==5 else '2026.2'
                    if count==5: legacy.pop('total_rounds'); legacy.pop('round_weights')
                    old_sums={1:0,2:0};opening=old_sums.copy()
                    for h in legacy['history']:
                        for t in h['starting_teams']: t['state']['cumulative']=old_sums[t['id']]
                        h['rules']=legacy['rules']
                        h['weight']=old_weights[h['period']-1]
                        for r in h['results']:
                            old_sums[r['team_id']]+=r['score']*h['weight']
                            r['cumulative']=r['next_state']['cumulative']=old_sums[r['team_id']]
                        if h['period']<legacy['period']: opening=old_sums.copy()
                        if count==5: h.pop('weight')
                    for t in legacy['teams']: t['state']['cumulative']=opening[t['id']]
                    with self.store.connection() as db:
                        db.execute('UPDATE games SET body=? WHERE id=?',(json.dumps(legacy),legacy['id']))
                    previous_backups=set(Path(self.temp.name).glob('*.bak'))
                    self.store=Store(Path(self.temp.name)/'game.db')
                    self.g=self.store.read(legacy['id'])
                    backups=set(Path(self.temp.name).glob('*.bak'))-previous_backups
                    self.assertEqual(len(backups),1)
                    with closing(sqlite3.connect(next(iter(backups)))) as db:
                        saved=json.loads(db.execute('SELECT body FROM games WHERE id=?',(legacy['id'],)).fetchone()[0])
                    self.assertEqual(saved,legacy)
                    self.assertEqual(self.g['phase'],phase)
                    self.assertEqual(self.g['weight_rule'],WEIGHT_RULE)
                    self.assertEqual(self.g['rules'],RULES_VERSION)
                    self.assertEqual(self.g['revision'],legacy['revision']+1)
                    self.assertEqual(self.g['decisions'],legacy['decisions'])
                    self.assertEqual(self.g['teams'],current['teams'])
                    for upgraded,original in zip(self.g['history'],current['history']):
                        self.assertEqual(upgraded['results'],original['results'])
                        self.assertEqual(upgraded['starting_teams'],original['starting_teams'])
                        self.assertEqual(upgraded['weight'],original['weight'])
                        self.assertEqual(upgraded['published'],original['published'])
                        self.assertEqual(upgraded['decisions'],original['decisions'])
                    self.assertEqual(Store(Path(self.temp.name)/'game.db').read(self.g['id']),self.g)
                    self.assertEqual(set(Path(self.temp.name).glob('*.bak')),previous_backups|backups)
                    # Continue from the restored opening cumulative score.
                    if phase=='settled': self.move('publish')
                    if phase in ('settled','published'): self.move('next')
                    if phase!='finished':
                        if self.g['phase']=='open': self.submit_all(); self.move('lock')
                        opening=self.g['teams'][0]['state']['cumulative']
                        self.move('settle')
                        r=self.g['history'][-1]['results'][0]
                        self.assertAlmostEqual(r['cumulative'],opening+r['score']*round_weights(count)[self.g['period']-1])

    def test_reweighting_recomputes_ranks_and_preserves_round_scores(self):
        # A leads under the former weights; B leads under the median schedule.
        g=dict(total_rounds=5,period=5,phase='finished',rules='2026.2',revision=4,audit=[],
               teams=[dict(id=i,state=dict(cumulative=0,assets=123)) for i in (1,2)],history=[])
        for period in range(1,6):
            scores=(1000 if period==1 else 0,470 if period==5 else 0)
            g['history'].append(dict(period=period,published=True,rules='2026.2',results=[
                dict(team_id=i,score=score,cumulative=150 if i==1 else 141,
                     rank=1,overall_rank=i,next_state=dict(cumulative=0,assets=123))
                for i,score in zip((1,2),scores)]))
        updated=reweight_game(g)
        a,b=updated['history'][-1]['results']
        self.assertAlmostEqual(a['cumulative'],1000*16/127)
        self.assertAlmostEqual(b['cumulative'],470*36/127)
        self.assertEqual((a['overall_rank'],b['overall_rank']),(2,1))
        self.assertEqual((a['score'],b['score']),(0,470))
        self.assertEqual(updated['teams'][0]['state']['assets'],123)

    def test_catastrophe_and_balance(self):
        with patch('engine.regional_shock', return_value=1.):
            base = calculate_round(DEFAULT_ENV,self.g['teams'],self.g['decisions'],1)[0]
            shock = calculate_round(dict(DEFAULT_ENV,catastrophe=.05),self.g['teams'],self.g['decisions'],1)[0]
        self.assertAlmostEqual(shock['losses']-base['losses'],base['earned']*.05)
        self.assertAlmostEqual(shock['underwriting']-base['underwriting'],-base['earned']*.05*.66)
        s=shock['next_state']
        self.assertAlmostEqual(s['assets'],s['surplus']+s['loss_reserve']+s['upr'])

    def test_lifecycle_privacy_restore_and_five_rounds(self):
        actor={'role':'student','game_id':self.g['id'],'team_id':1}
        for period in range(1,6):
            self.submit_all()
            self.move('lock')
            self.move('settle')
            self.assertEqual(len(self.g['history']),period)
            self.assertEqual(len(Store.view(self.g,actor)['history']),period-1)
            with self.assertRaises(ValueError): self.move('settle')
            old_cumulative=self.g['teams'][0]['state']['cumulative']
            r=self.g['history'][-1]['results'][0]
            self.assertAlmostEqual(r['cumulative'],old_cumulative+r['score']*[16/127,20/127,25/127,30/127,36/127][period-1])
            self.move('publish')
            v=Store.view(self.g,actor)
            self.assertEqual(list(v['decisions']),['1'])
            self.assertNotIn('pin',v['teams'][0])
            self.assertNotIn('state',v['teams'][1])
            self.assertEqual(len(v['history'][-1]['results']),1)
            self.assertEqual(len(v['history'][-1]['leaderboard']),5)
            if period<5:
                self.move('next')
                self.assertEqual(self.g['teams'][0]['state'],r['next_state'])
                self.assertTrue(all(not d['submitted'] for d in self.g['decisions'].values()))
        self.assertEqual(self.g['phase'],'finished')
        with self.assertRaises(ValueError): self.move('next')
        restored=Store(Path(self.temp.name)/'game.db').read(self.g['id'])
        self.assertEqual(restored,self.g)

    def test_access_and_stale_forms(self):
        actor={'role':'student','game_id':self.g['id'],'team_id':1}
        data=dict(period=1,team_id=2,values=DEFAULT_DECISION,submitted=True,saved_at=None)
        with self.assertRaises(PermissionError): self.store.mutate(self.g['id'],actor,'decision',data)
        with self.assertRaises(PermissionError): Store.view(self.g,dict(actor,game_id='OTHER'))
        with self.assertRaises(ValueError): self.move('lock')
        self.move('decision',team_id=1,values=DEFAULT_DECISION,submitted=True,saved_at=None)
        with self.assertRaises(ValueError): self.move('decision',team_id=1,values=DEFAULT_DECISION,submitted=True,saved_at=None)
        with self.assertRaises(ValueError): self.store.mutate(self.g['id'],TEACHER,'environment',dict(period=1,revision=0,env=DEFAULT_ENV))

    def test_concurrent_settle_once(self):
        self.submit_all();self.move('lock')
        data=dict(period=1,revision=self.g['revision'])
        def settle():
            try:self.store.mutate(self.g['id'],TEACHER,'settle',data);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:settle(),range(2)))
        self.assertEqual(sum(results),1)
        self.assertEqual(len(self.store.read(self.g['id'])['history']),1)

    def test_delete_restore_preserves_game_and_blocks_access(self):
        self.submit_all();self.move('lock');self.move('settle');self.move('publish')
        original=copy.deepcopy(self.g)
        student=dict(role='student',game_id=self.g['id'],team_id=1)
        other=self.store.create({'name':'Keep this classroom'})
        with self.assertRaises(PermissionError):
            self.store.classroom_action(self.g['id'],student,'delete',self.g['revision'])
        with self.assertRaises(ValueError):
            self.store.classroom_action(self.g['id'],TEACHER,'delete',self.g['revision']-1)
        deleted=self.store.classroom_action(self.g['id'],TEACHER,'delete',self.g['revision'])
        self.assertNotIn(self.g['id'],[g['id'] for g in self.store.list_games()])
        self.assertIn(other['id'],[g['id'] for g in self.store.list_games()])
        self.assertIn(self.g['id'],[g['id'] for g in self.store.list_games(deleted=True)])
        self.assertEqual(deleted['history'],original['history'])
        with self.assertRaises(ValueError):self.store.read(self.g['id'])
        with self.assertRaises(ValueError):Store.view(deleted,TEACHER)
        with self.assertRaises(ValueError):self.move('next')
        with self.assertRaises(ValueError):self.store.classroom_action(self.g['id'],TEACHER,'delete',deleted['revision'])
        restored=self.store.classroom_action(self.g['id'],TEACHER,'restore',deleted['revision'])
        for key in ('history','decisions','teams','phase','period','round_weights'):
            self.assertEqual(restored[key],original[key])
        self.assertNotIn('deleted_at',restored)
        self.assertEqual(restored['revision'],original['revision']+2)
        self.assertEqual(Store(Path(self.temp.name)/'game.db').read(self.g['id']),restored)
        self.assertEqual(Store.view(restored,student)['history'][0]['results'][0]['team_id'],1)
        self.g=restored;self.move('next')
        self.assertEqual(self.g['period'],2)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.server=Server(('127.0.0.1',0),Path(cls.temp.name),'testing-password')
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()

    def request(self,path,data=None,cookie=None,headers=None):
        h={'X-INSGAME':'1','Content-Type':'application/json',**(headers or {})}
        if cookie:h['Cookie']=cookie
        req=urllib.request.Request(self.url+path,data=json.dumps(data).encode() if data is not None else None,headers=h)
        try:
            with urllib.request.urlopen(req) as r:return r.status,r.headers,r.read()
        except urllib.error.HTTPError as r:return r.code,r.headers,r.read()

    def test_public_rules_and_removed_team_session(self):
        for path in ('/how-to-play','/rules'):
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(self.request('/api/games')[0], 403)
        _, h, _ = self.request('/api/login', dict(role='teacher', password='testing-password'))
        admin = h['Set-Cookie'].split(';')[0]
        _, _, b = self.request('/api/create', dict(teams=3), admin)
        g = json.loads(b)
        login = dict(role='student', code=g['id'], team_id=2, pin=g['teams'][1]['pin'])
        _, h, _ = self.request('/api/login', login)
        student = h['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('/api/action', dict(game_id=g['id'], action='remove_team',
                         team_id=2, period=1, revision=g['revision']), admin)[0], 200)
        self.assertEqual(self.request('/api/game?id='+g['id'], cookie=student)[0], 403)
        self.assertEqual(self.request('/api/login', login)[0], 403)

    def test_team_password_lifecycle(self):
        def sign_in(data):
            status, headers, _ = self.request('/api/login', data)
            self.assertEqual(status, 200)
            return headers['Set-Cookie'].split(';')[0]
        admin = sign_in(dict(role='teacher', password='testing-password'))
        _, _, body = self.request('/api/create', dict(teams=2, demo=True), admin)
        game = json.loads(body)
        gid = game['id']
        original = game['teams'][0]['pin']
        login = dict(role='student', code=gid, team_id=1, pin=original.lower())
        first, teammate = sign_in(login), sign_in(login)
        other = sign_in(dict(login, team_id=2, pin=game['teams'][1]['pin']))
        endpoint = '/api/team-password'
        change = dict(game_id=gid, team_id=1, password_revision=0, action='skip')
        def view(cookie):
            return self.request('/api/game?id='+gid, cookie=cookie)
        self.assertEqual(self.request(endpoint, change)[0], 403)
        self.assertEqual(self.request(endpoint, dict(change, team_id=2), first)[0], 403)
        self.assertEqual(self.request(endpoint, dict(change, action='reset'), first)[0], 403)
        self.assertEqual(self.request(endpoint, change, first)[0], 200)
        sign_in(login)
        self.assertEqual(json.loads(view(teammate)[2])['teams'][0]['password_setup'], 'skipped')
        custom = 'Mixed Case team pass!'
        setup = dict(change, password_revision=1, action='set', password=custom)
        self.assertEqual(self.request(endpoint, dict(setup, password='short'), first)[0], 400)
        self.assertEqual(self.request(endpoint, dict(setup, password_revision=0), first)[0], 400)
        self.assertEqual(self.request(endpoint, setup, first)[0], 200)
        self.assertEqual(view(first)[0], 200)
        self.assertEqual(view(teammate)[0], 403)
        self.assertEqual(self.request('/api/login', login)[0], 403)
        self.assertEqual(self.request('/api/login', dict(login, pin=custom.upper()))[0], 403)
        fresh = sign_in(dict(login, pin=custom))
        teacher_view = json.loads(view(admin)[2])
        self.assertNotIn('pin', teacher_view['teams'][0])
        for action in ('lock', 'settle'):
            status, _, b = self.request('/api/action', dict(game_id=gid,period=1,action=action,
                                          revision=teacher_view['revision']), admin)
            self.assertEqual(status, 200)
            teacher_view = json.loads(b)
        status, _, exported = self.request('/api/export?id='+gid+'&format=json', cookie=admin)
        self.assertEqual(status, 200)
        self.assertNotIn(custom.encode(), exported)
        self.assertNotIn(original.encode(), exported)
        self.assertNotIn('"pin"', exported.decode())
        status, _, b = self.request(endpoint, dict(change, password_revision=2, action='reset'), admin)
        self.assertEqual(status, 200)
        reset = json.loads(b)
        self.assertEqual(reset['history'], teacher_view['history'])
        self.assertEqual(reset['decisions'], teacher_view['decisions'])
        self.assertEqual(reset['teams'][0]['password_setup'], 'pending')
        self.assertEqual(self.request('/api/login', dict(login, pin=custom))[0], 403)
        self.assertEqual(view(fresh)[0], 403)
        self.assertEqual(view(first)[0], 403)
        self.assertEqual(view(other)[0], 200)
        sign_in(dict(login, pin=reset['teams'][0]['pin']))

    def test_http_role_isolation_export_and_csrf(self):
        status,_,_=self.request('/api/games');self.assertEqual(status,403)
        status,h,b=self.request('/api/login',{'role':'teacher','password':'testing-password'})
        self.assertEqual(status,200);admin=h['Set-Cookie'].split(';')[0]
        _,_,b=self.request('/api/create',{'teams':3,'demo':True},admin);g=json.loads(b)
        _,h,_=self.request('/api/login',{'role':'student','code':g['id'],'team_id':1,'pin':g['teams'][0]['pin']})
        student=h['Set-Cookie'].split(';')[0]
        _,_,b=self.request('/api/game?id='+g['id'],cookie=student);v=json.loads(b)
        self.assertNotIn('pin',v['teams'][1]);self.assertNotIn('2',v['decisions'])
        self.assertEqual(self.request('/api/create',{},student)[0],403)
        self.assertEqual(self.request('/api/create',{},admin,{'Origin':'https://elsewhere.example'})[0],403)
        for action in ('lock','settle','publish'):
            _,_,b=self.request('/api/action',dict(game_id=g['id'],action=action,period=1,revision=g['revision']),admin);g=json.loads(b)
        status,_,b=self.request('/api/export?id='+g['id'],cookie=student)
        self.assertEqual(status,200);self.assertIn('Team 01',b.decode('utf-8-sig'));self.assertNotIn('Team 02',b.decode('utf-8-sig'))
        _,_,b=self.request('/api/export?id='+g['id']+'&format=json',cookie=admin)
        self.assertNotIn('"pin"',b.decode())
        self.assertEqual(self.request('/../app.py')[0],404)

    def test_http_custom_round_count_and_export(self):
        _,h,_=self.request('/api/login',{'role':'teacher','password':'testing-password'})
        admin=h['Set-Cookie'].split(';')[0]
        for invalid in (0,100,2.5,True):
            self.assertEqual(self.request('/api/create',{'total_rounds':invalid},admin)[0],400)
        status,_,b=self.request('/api/create',{'teams':2,'demo':True,'total_rounds':6},admin)
        self.assertEqual(status,200);g=json.loads(b)
        self.assertEqual(g['total_rounds'],6)
        _,h,_=self.request('/api/login',{'role':'student','code':g['id'],'team_id':1,'pin':g['teams'][0]['pin']})
        student=h['Set-Cookie'].split(';')[0]
        payload=dict(game_id=g['id'],action='rounds',total_rounds=1,period=1,revision=g['revision'])
        self.assertEqual(self.request('/api/action',payload,student)[0],403)
        status,_,b=self.request('/api/action',payload,admin)
        self.assertEqual(status,200);g=json.loads(b)
        for action in ('lock','settle','publish'):
            status,_,b=self.request('/api/action',dict(game_id=g['id'],action=action,period=1,revision=g['revision']),admin)
            self.assertEqual(status,200);g=json.loads(b)
        self.assertEqual(g['phase'],'finished')
        _,_,b=self.request('/api/games',cookie=admin)
        self.assertEqual(next(x for x in json.loads(b)['games'] if x['id']==g['id'])['total_rounds'],1)
        _,_,b=self.request('/api/export?id='+g['id']+'&format=json',cookie=admin)
        exported=json.loads(b)
        self.assertEqual(exported['total_rounds'],1)
        self.assertEqual(exported['history'][0]['weight'],1)

    def test_http_delete_restore_revokes_only_target_student_sessions(self):
        _,h,_=self.request('/api/login',{'role':'teacher','password':'testing-password'})
        admin=h['Set-Cookie'].split(';')[0]
        _,_,b=self.request('/api/create',{'teams':2,'demo':True},admin);g=json.loads(b)
        _,_,b=self.request('/api/create',{'teams':2,'demo':True},admin);other=json.loads(b)
        login=dict(role='student',code=g['id'],team_id=1,pin=g['teams'][0]['pin'])
        _,h,_=self.request('/api/login',login);student=h['Set-Cookie'].split(';')[0]
        _,h,_=self.request('/api/login',dict(role='student',code=other['id'],team_id=1,pin=other['teams'][0]['pin']))
        other_student=h['Set-Cookie'].split(';')[0]
        payload=dict(game_id=g['id'],action='delete',revision=g['revision'])
        self.assertEqual(self.request('/api/classroom',payload,student)[0],403)
        self.assertEqual(self.request('/api/classroom',payload,admin,{'Origin':'https://elsewhere.example'})[0],403)
        self.assertEqual(self.request('/api/classroom',dict(payload,revision=-1),admin)[0],400)
        self.assertEqual(self.request('/api/classroom',payload,admin)[0],200)
        self.assertEqual(self.request('/api/game?id='+g['id'],cookie=student)[0],403)
        self.assertEqual(self.request('/api/game?id='+other['id'],cookie=other_student)[0],200)
        self.assertEqual(self.request('/api/export?id='+g['id'],cookie=admin)[0],400)
        self.assertEqual(self.request('/api/login',login)[0],403)
        self.assertEqual(self.request('/api/games?deleted=1',cookie=other_student)[0],403)
        _,_,b=self.request('/api/games?deleted=1',cookie=admin)
        deleted=next(x for x in json.loads(b)['games'] if x['id']==g['id'])
        self.assertEqual(self.request('/api/classroom',dict(payload,action='restore',revision=deleted['revision']),admin)[0],200)
        self.assertEqual(self.request('/api/login',login)[0],200)
        self.assertEqual(self.request('/api/game?id='+g['id'],cookie=student)[0],403)

    def test_dashboard_results_remain_private_to_instructor(self):
        _,h,_=self.request('/api/login',{'role':'teacher','password':'testing-password'})
        admin=h['Set-Cookie'].split(';')[0]
        _,_,b=self.request('/api/create',{'teams':5,'demo':True},admin);g=json.loads(b)
        _,h,_=self.request('/api/login',dict(role='student',code=g['id'],team_id=1,pin=g['teams'][0]['pin']))
        student=h['Set-Cookie'].split(';')[0]
        for action in ('lock','settle'):
            _,_,b=self.request('/api/action',dict(game_id=g['id'],action=action,period=1,revision=g['revision']),admin);g=json.loads(b)
        self.assertEqual(len(g['history'][0]['results']),5)
        self.assertFalse(g['history'][0]['published'])
        for r in g['history'][0]['results']:
            self.assertIn('policies',r);self.assertIn('income',r);self.assertIn('assets',r['next_state'])
            self.assertAlmostEqual(r['income'],r['underwriting']+r['bond_income']+r['stock_income'])
        _,_,b=self.request('/api/game?id='+g['id'],cookie=student)
        self.assertEqual(json.loads(b)['history'],[])
        self.request('/api/action',dict(game_id=g['id'],action='publish',period=1,revision=g['revision']),admin)
        _,_,b=self.request('/api/game?id='+g['id'],cookie=student);v=json.loads(b)
        self.assertEqual(len(v['history'][0]['results']),1)
        for r in v['history'][0]['leaderboard']:
            self.assertNotIn('income',r);self.assertNotIn('policies',r);self.assertNotIn('next_state',r)

    def test_investment_submission_report_and_csv(self):
        _,h,_=self.request('/api/login',{'role':'teacher','password':'testing-password'})
        admin=h['Set-Cookie'].split(';')[0]
        _,_,b=self.request('/api/create',{'teams':5,'demo':True},admin);g=json.loads(b)
        _,h,_=self.request('/api/login',dict(role='student',code=g['id'],team_id=1,pin=g['teams'][0]['pin']))
        student=h['Set-Cookie'].split(';')[0]
        payload=dict(game_id=g['id'],action='decision',period=1,team_id=1,
                     saved_at=g['decisions']['1']['saved_at'],submitted=True)
        invalid=dict(DEFAULT_DECISION,cash_pct=.09,bond_pct=.71)
        self.assertEqual(self.request('/api/action',dict(payload,values=invalid),student)[0],400)
        chosen=dict(g['decisions']['1']['values'],bond_strategy=2,stock_strategy=5)
        self.assertEqual(self.request('/api/action',dict(payload,values=chosen),student)[0],200)
        _,_,b=self.request('/api/game?id='+g['id'],cookie=admin);g=json.loads(b)
        for action in ('lock','settle','publish'):
            status,_,b=self.request('/api/action',dict(game_id=g['id'],action=action,period=1,revision=g['revision']),admin)
            self.assertEqual(status,200);g=json.loads(b)
        _,_,b=self.request('/api/game?id='+g['id'],cookie=student)
        own=json.loads(b)['history'][0]['results']
        self.assertEqual(len(own),1)
        self.assertEqual((own[0]['bond_return'],own[0]['stock_return']),(.08,.24))
        _,_,b=self.request('/api/export?id='+g['id'],cookie=student)
        rows=list(csv.DictReader(io.StringIO(b.decode('utf-8-sig'))))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['Bond strategy'],'2')
        self.assertEqual(rows[0]['Stock strategy'],'5')
        self.assertEqual(float(rows[0]['Annual stock return']),.24)
        self.assertEqual(float(rows[0]['Annual bond return']),.08)
        self.assertAlmostEqual(float(rows[0]['Low-risk policies'])+float(rows[0]['High-risk policies']),own[0]['policies'])
        self.assertEqual(float(rows[0]['Cumulative weighted surplus']),own[0]['cumulative'])
        self.assertEqual(float(rows[0]['Closing surplus score']),own[0]['next_state']['surplus'])


if __name__=='__main__': unittest.main()
