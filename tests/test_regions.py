import copy
import json
import math
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from engine import (DEFAULT_DECISION, DEFAULT_ENV, LOSS_RATIOS, MODEL_RULE, PREMIUM_RULE, REGIONS,
                    calculate_round, initial_state, regional_appeal, regional_shock,
                    round_weights, validate_decision)
from store import Store


class RegionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'game.db'
        self.store=Store(self.path)
        self.g=self.store.create(dict(teams=5))

    def tearDown(self):self.temp.cleanup()

    def calculate(self):
        return calculate_round(self.g['env'],self.g['teams'],self.g['decisions'],1,
                               market_policies=self.g['market']['policies'],risk_seed=self.g['risk_seed'])

    def test_initial_books_and_market_scale(self):
        s=initial_state()
        self.assertEqual(s['surplus'],3_000_000)
        self.assertEqual(s['policies'],1000)
        self.assertEqual(s['low_policies']+s['high_policies'],1000)
        self.assertAlmostEqual(s['assets']-s['loss_reserve']-s['upr'],s['surplus'])
        for count in (2,5,20):
            g=self.store.create(dict(teams=count))
            self.assertEqual(g['market']['initial_premium'],5_000_000*count)
            rs=calculate_round(g['env'],g['teams'],g['decisions'],1)
            self.assertAlmostEqual(sum(r['policies'] for r in rs),1000*count)
            self.assertAlmostEqual(sum(r['gross'] for r in rs),112_500*count)
            for d in g['decisions'].values():
                self.assertEqual((d['values']['low_premium'],d['values']['high_premium']),(100,150))

    def test_loss_distributions_and_expected_costs(self):
        variances=[]
        for key,r in REGIONS.items():
            self.assertAlmostEqual(sum(p for p,m in r['shocks']),1)
            self.assertAlmostEqual(sum(p*m for p,m in r['shocks']),1)
            variances.append(sum(p*(m-1)**2 for p,m in r['shocks']))
        self.assertGreater(variances[1],variances[0])
        self.assertEqual(LOSS_RATIOS,[.39,.44,.47,.51,.56,.62,.67,.73,.80])
        r=self.calculate()[0]
        self.assertAlmostEqual(r['regions']['low']['expected_loss_per_policy'],43.35)
        self.assertAlmostEqual(r['regions']['high']['expected_loss_per_policy'],95.625)
        self.assertAlmostEqual(r['regions']['low']['expected_loss_ratio'],.4335)
        self.assertAlmostEqual(r['regions']['high']['expected_loss_ratio'],.6375)
        self.assertEqual(self.calculate(),self.calculate())
        for key in REGIONS:
            self.assertEqual(len({x['regions'][key]['shock'] for x in self.calculate()}),1)
            self.assertEqual(regional_shock(self.g['risk_seed'],1,key),r['regions'][key]['shock'])

    def test_exact_region_mix_zero_and_full_allocation(self):
        for fraction in (0,.25,.75,1):
            self.g['decisions']['1']['values'].update(low_pct=fraction,high_pct=1-fraction)
            r=self.calculate()[0]
            self.assertAlmostEqual(r['regions']['low']['policies'],r['policies']*fraction)
            self.assertAlmostEqual(sum(x['gross'] for x in r['regions'].values()),r['gross'])
            self.assertAlmostEqual(sum(x['losses'] for x in r['regions'].values()),r['losses'])
            self.assertAlmostEqual(r['next_state']['policies'],r['policies'])
            if fraction==0:self.assertEqual(r['regions']['low']['losses'],0)
        for changes in ({'low_pct':.7},{'high_pct':-1},{'low_premium':49},{'high_premium':74},{'high_premium':20001},{'high_screening':-1}):
            with self.assertRaises(ValueError):validate_decision(dict(DEFAULT_DECISION,**changes))

    def test_pricing_changes_demand_not_expected_claim_severity(self):
        before=self.calculate()[0]
        self.g['decisions']['1']['values']['low_premium']=150
        after=self.calculate()[0]
        self.assertLess(after['policies'],before['policies'])
        self.assertEqual(after['regions']['low']['expected_loss_per_policy'],before['regions']['low']['expected_loss_per_policy'])
        self.assertAlmostEqual(after['regions']['low']['expected_loss_ratio'],before['regions']['low']['expected_loss_ratio']*2/3)
        # The market premium is an outcome, not a fixed zero-sum pool.
        self.assertNotAlmostEqual(sum(r['gross'] for r in self.calculate()),562_500)

    def test_relaxed_strategy_increases_appeal_more_in_high_risk(self):
        state=initial_state()
        strict=dict(DEFAULT_DECISION,strategy=1)
        relaxed=dict(DEFAULT_DECISION,strategy=9)
        ratios={key:regional_appeal(relaxed,state,1,key)/regional_appeal(strict,state,1,key) for key in REGIONS}
        self.assertGreater(ratios['low'],1)
        self.assertGreater(ratios['high'],ratios['low'])
        self.g['decisions']['1']['values']=strict
        a=self.calculate()[0]
        self.g['decisions']['1']['values']=relaxed
        b=self.calculate()[0]
        for key in REGIONS:self.assertGreater(b['regions'][key]['expected_loss_per_policy'],a['regions'][key]['expected_loss_per_policy'])

    def test_screening_is_bounded_separate_and_expensed(self):
        with patch('engine.regional_shock',return_value=1.):
            before=self.calculate()[0]
            spending=before['regions']['low']['gross']*.01
            self.g['decisions']['1']['values']['low_screening']=spending
            after=self.calculate()[0]
            self.assertAlmostEqual(after['regions']['low']['screening_reduction'],.025)
            self.assertEqual(after['regions']['high']['loss_ratio'],before['regions']['high']['loss_ratio'])
            self.assertAlmostEqual(after['underwriting']-before['underwriting'],(before['losses']-after['losses']-spending)*.66)
            self.assertEqual(after['screening'],spending)
            self.g['decisions']['1']['values']['low_screening']=spending*100
            large=self.calculate()[0]['regions']['low']['screening_reduction']
            self.assertGreater(large,.025);self.assertLess(large,.05)

    def test_weighted_surplus_and_market_carryforward(self):
        g=self.g
        for d in g['decisions'].values():d['submitted']=True
        with self.store.connection() as db:db.execute('UPDATE games SET body=? WHERE id=?',(json.dumps(g),g['id']))
        for action in ('lock','settle','publish','next'):
            g=self.store.mutate(g['id'],{'role':'teacher'},action,dict(period=g['period'],revision=g['revision']))
        h=g['history'][0]
        self.assertAlmostEqual(g['market']['policies'],h['market']['total_policies']*1.02)
        for r,t in zip(h['results'],g['teams']):
            self.assertEqual(r['score'],r['next_state']['surplus'])
            self.assertAlmostEqual(r['cumulative'],r['score']*round_weights()[0])
            self.assertEqual(t['state'],r['next_state'])
        student=Store.view(g,dict(role='student',game_id=g['id'],team_id=1))
        self.assertNotIn('risk_seed',student)
        self.assertEqual(len(student['history'][0]['results']),1)
        for r in student['history'][0]['leaderboard']:
            self.assertNotIn('regions',r)
            self.assertEqual(r['surplus'],r['score'])

    def test_market_upgrade_preserves_history_and_access(self):
        for completed in (False,True):
            g=self.store.create(dict(teams=3,demo=True))
            if completed:
                for action in ('lock','settle','publish','next'):
                    g=self.store.mutate(g['id'],{'role':'teacher'},action,dict(period=g['period'],revision=g['revision']))
            g.pop('model_rule');g['rules']='2026.4'
            g['env'].pop('market_growth');g['env']['market']=1e9
            for d in g['decisions'].values():
                d['values']['price']=105
                for key in ('low_premium','high_premium','low_pct','high_pct','low_screening','high_screening'):d['values'].pop(key)
            for h in g['history']:
                for r in h['results']:r['score']=r['next_state']['assets']+3*r['next_state']['surplus']+r['net']
            before=copy.deepcopy(g)
            with self.store.connection() as db:db.execute('UPDATE games SET body=? WHERE id=?',(json.dumps(g),g['id']))
            self.store=Store(self.path);after=self.store.read(g['id'])
            self.assertEqual(after['model_rule'],MODEL_RULE)
            self.assertEqual(after['id'],before['id'])
            self.assertEqual([t['pin'] for t in after['teams']],[t['pin'] for t in before['teams']])
            self.assertTrue(all(not d['submitted'] for d in after['decisions'].values()))
            self.assertEqual(after['decisions']['1']['values']['low_premium'],105)
            self.assertEqual(after['decisions']['1']['values']['high_premium'],157.5)
            if completed:
                for new,old in zip(after['history'][0]['results'],before['history'][0]['results']):
                    self.assertEqual(new['score'],old['next_state']['surplus'])
                    self.assertEqual(new['legacy_score'],old['score'])
                    for key in ('gross','income','losses','regions'):self.assertEqual(new[key],old[key])
            else:self.assertEqual(after['teams'][0]['state'],initial_state())
            backups=list(Path(self.temp.name).glob('*.before-regions-*.bak'))
            self.assertTrue(backups)
            with closing(sqlite3.connect(max(backups,key=lambda p:p.stat().st_mtime))) as db:
                self.assertEqual(json.loads(db.execute('SELECT body FROM games WHERE id=?',(g['id'],)).fetchone()[0]),before)
            self.assertEqual(Store(self.path).read(g['id']),after)

    def test_premium_upgrade_preserves_saved_quotes_history_and_backup(self):
        for phase in ('open','locked','settled'):
            with self.subTest(phase=phase):
                g=self.store.create(dict(teams=3,demo=True))
                if phase in ('locked','settled'):
                    g=self.store.mutate(g['id'],{'role':'teacher'},'lock',dict(period=1,revision=g['revision']))
                if phase=='settled':
                    g=self.store.mutate(g['id'],{'role':'teacher'},'settle',dict(period=1,revision=g['revision']))
                g.pop('premium_rule');g['rules']='2026.5'
                for d in g['decisions'].values():
                    d['values'].update(low_premium=4000,high_premium=8000)
                if phase=='open':
                    g['decisions']['1'].update(saved_at=None,submitted=False)
                g['decisions']['2']['values']['low_premium']=4100
                before=copy.deepcopy(g)
                with self.store.connection() as db:
                    db.execute('UPDATE games SET body=? WHERE id=?',(json.dumps(g),g['id']))
                upgraded=Store(self.path);after=upgraded.read(g['id'])
                self.assertEqual(after['premium_rule'],PREMIUM_RULE)
                for key in ('teams','history','market','risk_seed','id'):
                    self.assertEqual(after[key],before[key])
                if phase=='settled':
                    self.assertEqual(after['decisions'],before['decisions'])
                    self.assertEqual(after['phase'],'settled')
                else:
                    self.assertEqual(after['phase'],'open')
                    self.assertTrue(all(not d['submitted'] for d in after['decisions'].values()))
                    # Keep deliberately saved quotes, even at the old default values.
                    for tid in ('2','3'):
                        self.assertEqual(after['decisions'][tid]['values'],before['decisions'][tid]['values'])
                    d=after['decisions']['1']['values']
                    self.assertEqual((d['low_premium'],d['high_premium']),
                                     (100,150) if phase=='open' else (4000,8000))
                    with self.assertRaisesRegex(ValueError,'another window'):
                        upgraded.mutate(g['id'],{'role':'teacher'},'decision',dict(
                            period=1,team_id=1,saved_at=before['decisions']['1']['saved_at'],
                            values=DEFAULT_DECISION,submitted=True))
                backups=list(Path(self.temp.name).glob('*.before-premiums-*.bak'))
                self.assertTrue(backups)
                with closing(sqlite3.connect(max(backups,key=lambda p:p.stat().st_mtime_ns))) as db:
                    self.assertEqual(json.loads(db.execute('SELECT body FROM games WHERE id=?',(g['id'],)).fetchone()[0]),before)
                self.assertEqual(Store(self.path).read(g['id']),after)
                self.assertEqual(len(list(Path(self.temp.name).glob('*.before-premiums-*.bak'))),len(backups))


if __name__=='__main__':unittest.main()
