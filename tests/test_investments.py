import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from engine import DEFAULT_DECISION, DEFAULT_ENV, INVESTMENT_RULE, RULES_VERSION, calculate_round, validate_decision
from store import Store

TEACHER = {'role': 'teacher'}


class InvestmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.db'
        self.store = Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_bond_participation_strict_threshold_for_every_class_size(self):
        for count in range(2, 51):
            g = self.store.create(dict(teams=count, demo=True))
            for selected in range(count+1):
                for i, d in enumerate(g['decisions'].values()):
                    d['values']['bond_strategy'] = 2 if i < selected else 1
                rs = calculate_round(g['env'], g['teams'], g['decisions'], 1)
                for r in rs:
                    expected = .04 if r['bond_strategy'] == 1 else (.08 if selected/count < .3 else .02)
                    self.assertEqual(r['bond_return'], expected, (count, selected))
                    self.assertEqual(r['bond_strategy_2_count'], selected)
                    self.assertEqual(r['team_count'], count)

    def test_zero_bond_allocation_still_counts_strategy_choice(self):
        g = self.store.create(dict(teams=5))
        g['decisions']['1']['values']['bond_strategy'] = 2
        g['decisions']['2']['values'].update(bond_strategy=2, cash_pct=1, bond_pct=0, stock_pct=0)
        rs = calculate_round(g['env'], g['teams'], g['decisions'], 1)
        self.assertEqual(rs[0]['bond_return'], .02)
        self.assertEqual(rs[1]['bond_income'], 0)

    def test_all_stock_multipliers_and_tax_on_positive_zero_negative_base(self):
        g = self.store.create(dict(teams=5))
        for i, d in enumerate(g['decisions'].values(), 1):
            d['values']['stock_strategy'] = i
        for base in (.12, 0, -.12):
            rs = calculate_round(dict(DEFAULT_ENV, stock_return=base), g['teams'], g['decisions'], 1)
            for r, multiple in zip(rs, (.8, 1, 1.2, 1.4, 2)):
                self.assertAlmostEqual(r['stock_return'], base*multiple)
                self.assertEqual(r['stock_base_return'], base)
                self.assertEqual(r['stock_multiplier'], multiple)
                # 90% of 9.165m + .3 * (101,250 - 4.5m) = 6,928,875.
                self.assertAlmostEqual(r['stock_income'], (2/9)*6_928_875*base*multiple*.66)
                self.assertAlmostEqual(r['bond_income'], (7/9)*6_928_875*.04*.85)
                self.assertAlmostEqual(r['income'], r['underwriting']+r['bond_income']+r['stock_income'])

    def test_cash_and_strategy_validation(self):
        for cash in (0, .099, .0999999):
            with self.assertRaisesRegex(ValueError, 'minimum 10%'):
                validate_decision(dict(DEFAULT_DECISION, cash_pct=cash, bond_pct=1-cash, stock_pct=0))
        for cash in (.1, .5, 1):
            self.assertEqual(validate_decision(dict(DEFAULT_DECISION, cash_pct=cash, bond_pct=1-cash, stock_pct=0))['cash_pct'],cash)
        for key, maximum in (('bond_strategy',2),('stock_strategy',5)):
            for invalid in (None, True, 0, maximum+1, 1.5, float('nan')):
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                    validate_decision(dict(DEFAULT_DECISION, **{key:invalid}))
            missing = DEFAULT_DECISION.copy();missing.pop(key)
            with self.assertRaises(ValueError):validate_decision(missing)

    def test_invalid_student_changes_do_not_save_and_valid_choices_persist(self):
        g = self.store.create(dict(teams=3))
        actor = dict(role='student',game_id=g['id'],team_id=1)
        request = dict(period=1,team_id=1,saved_at=None,submitted=True)
        with self.assertRaises(ValueError):
            self.store.mutate(g['id'],actor,'decision',dict(request,values=dict(DEFAULT_DECISION,cash_pct=.09,bond_pct=.71)))
        self.assertEqual(self.store.read(g['id'])['decisions'],g['decisions'])
        g = self.store.mutate(g['id'],actor,'decision',dict(request,values=dict(DEFAULT_DECISION,bond_strategy=2,stock_strategy=5)))
        self.assertEqual(self.store.read(g['id'])['decisions']['1']['values']['stock_strategy'],5)
        self.assertNotIn('2',Store.view(g,actor)['decisions'])

    def test_upgrade_backs_up_preserves_history_and_requires_resubmission(self):
        for phase in ('open','locked','settled','published','finished'):
            with self.subTest(phase=phase):
                g = self.store.create(dict(teams=3,demo=True,total_rounds=1 if phase=='finished' else 5))
                def act(action):
                    nonlocal g
                    g = self.store.mutate(g['id'],TEACHER,action,dict(period=g['period'],revision=g['revision']))
                if phase!='open':act('lock')
                if phase in ('settled','published','finished'):act('settle')
                if phase in ('published','finished'):act('publish')
                g.pop('investment_rule')
                g['rules']='2026.3';g['env']['bond_return']=.08
                for d in g['decisions'].values():
                    d['values'].pop('bond_strategy');d['values'].pop('stock_strategy')
                # Preserve an old below-minimum allocation for the user to fix.
                g['decisions']['1']['values'].update(cash_pct=.05,bond_pct=.75)
                before = copy.deepcopy(g)
                with self.store.connection() as db:
                    db.execute('UPDATE games SET body=? WHERE id=?',(json.dumps(g),g['id']))
                backups = set(Path(self.temp.name).glob('*.bak'))
                self.store = Store(self.path)
                after = self.store.read(g['id'])
                new_backups = set(Path(self.temp.name).glob('*.bak'))-backups
                self.assertEqual(len(new_backups),1)
                with closing(sqlite3.connect(next(iter(new_backups)))) as db:
                    self.assertEqual(json.loads(db.execute('SELECT body FROM games WHERE id=?',(g['id'],)).fetchone()[0]),before)
                for key in ('history','teams','period','round_weights'):
                    self.assertEqual(after[key],before[key])
                self.assertEqual(after['rules'],RULES_VERSION)
                self.assertEqual(after['investment_rule'],INVESTMENT_RULE)
                self.assertEqual(after['phase'],'open' if phase=='locked' else phase)
                self.assertEqual(after['decisions']['1']['values']['cash_pct'],.05)
                self.assertEqual(after['decisions']['1']['values']['bond_strategy'],1)
                self.assertEqual(after['decisions']['1']['values']['stock_strategy'],2)
                self.assertNotIn('bond_return',after['env'])
                if phase in ('open','locked'):
                    self.assertTrue(all(not d['submitted'] for d in after['decisions'].values()))
                    with self.assertRaises(ValueError):
                        self.store.mutate(g['id'],TEACHER,'decision',dict(period=g['period'],team_id=1,
                            saved_at=before['decisions']['1']['saved_at'],values=DEFAULT_DECISION,submitted=True))
                self.assertEqual(Store(self.path).read(g['id']),after)
                self.assertEqual(set(Path(self.temp.name).glob('*.bak')),backups|new_backups)


if __name__=='__main__':unittest.main()
