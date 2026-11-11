"""Seeded two-region teaching model, version 2026.6. See RULES.md."""
import hashlib
import math

RULES_VERSION = "2026.6"
PREMIUM_RULE = "regional-premiums-100-150-v1"
MODEL_RULE = "two-regions-weighted-surplus-v1"
INVESTMENT_RULE = "bond-choice-stock-multipliers-v1"
STOCK_MULTIPLIERS = (.80, 1., 1.20, 1.40, 2.)
MIN_CASH = .10
WEIGHT_RULE = "median-80-120-v1"
DEFAULT_ROUNDS = 5
MAX_ROUNDS = 99
MAX_TEAMS = 50
LOSS_RATIOS = [.39, .44, .47, .51, .56, .62, .67, .73, .80]
REGIONS = {
    'low': dict(name='Low risk', reference_premium=100, risk_factor=.85,
                appeal_sensitivity=1., price_elasticity=1.4,
                shocks=[(.25, .8), (.5, 1.), (.25, 1.2)]),
    'high': dict(name='High risk', reference_premium=150, risk_factor=1.25,
                 appeal_sensitivity=1.6, price_elasticity=1.1,
                 shocks=[(.6, .6), (.3, 1.2), (.1, 2.8)])}
DEFAULT_ENV = dict(market_growth=.02, catastrophe=0, stock_return=.05, ceding_rate=.50)
DEFAULT_DECISION = dict(low_premium=100, high_premium=150,
                        low_pct=.75, high_pct=.25, low_screening=0, high_screening=0,
                        advertising=50_000, promotion=20_000,
                        new_commission=15, renewal_commission=10, strategy=4,
                        reinsurance=.10, cash_pct=.10, bond_pct=.70, stock_pct=.20,
                        bond_strategy=1, stock_strategy=2)


def number(value, label, low, high, integer=False):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number.")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number.") from None
    if not math.isfinite(x) or not low <= x <= high:
        raise ValueError(f"{label} must be between {low:g} and {high:g}.")
    if integer and x != int(x):
        raise ValueError(f"{label} must be an integer.")
    return int(x) if integer else x


def validate_env(data):
    env = {k: number(data.get(k), name, lo, hi) for k, name, lo, hi in [
        ('market_growth', 'Annual customer market growth', -.20, .20), ('catastrophe', 'Catastrophe increment', 0, 1),
        ('stock_return', 'Base annual stock return', -1, 1),
        ('ceding_rate', 'Ceding commission rate', 0, 1)]}
    if 'random_catastrophe' in data:
        if not isinstance(data['random_catastrophe'], bool):
            raise ValueError('Invalid catastrophe setting.')
        env['random_catastrophe'] = data['random_catastrophe']
    return env


def round_weights(total_rounds=DEFAULT_ROUNDS):
    total_rounds = number(total_rounds, 'Number of rounds', 1, MAX_ROUNDS, True)
    left, right = (total_rounds - 1) // 2, total_rounds // 2
    raw = [.8 ** (left - i) if i < left else 1.2 ** (i - right) if i > right else 1.
           for i in range(total_rounds)]
    total = math.fsum(raw)
    return [weight / total for weight in raw]


def rank_results(results):
    for r in results:
        r['rank'] = 1 + sum(x['score'] > r['score'] and not math.isclose(x['score'], r['score'], rel_tol=1e-12) for x in results)
        r['overall_rank'] = 1 + sum(x['cumulative'] > r['cumulative'] and not math.isclose(x['cumulative'], r['cumulative'], rel_tol=1e-12) for x in results)
    return results


def validate_decision(data):
    # Lower bounds follow the new reference prices; retain the old upper bounds
    # so existing saved choices remain editable after the defaults change.
    specs = [('low_premium', 'Low-risk premium', 50, 10000),
             ('high_premium', 'High-risk premium', 75, 20000),
             ('low_pct', 'Low-risk policy share', 0, 1), ('high_pct', 'High-risk policy share', 0, 1),
             ('low_screening', 'Low-risk screening spending', 0, 1e9),
             ('high_screening', 'High-risk screening spending', 0, 1e9),
             ('advertising', 'Advertising', 0, 1e9),
             ('promotion', 'Promotion', 0, 1e9), ('new_commission', 'New business commission', 0, 50),
             ('renewal_commission', 'Renewal commission', 0, 50), ('strategy', 'Underwriting strategy', 1, 9),
             ('reinsurance', 'Reinsurance share', 0, 1), ('cash_pct', 'Cash allocation (minimum 10%)', MIN_CASH, 1),
             ('bond_pct', 'Bond allocation', 0, 1), ('stock_pct', 'Stock allocation', 0, 1),
             ('bond_strategy', 'Bond strategy', 1, 2), ('stock_strategy', 'Stock strategy', 1, 5)]
    result = {k: number(data.get(k), name, lo, hi, k.endswith('strategy')) for k, name, lo, hi in specs}
    if abs(sum(result[k] for k in ('cash_pct', 'bond_pct', 'stock_pct')) - 1) > 1e-8:
        raise ValueError('Cash, bond, and stock allocations must total 100%.')
    if abs(result['low_pct'] + result['high_pct'] - 1) > 1e-8:
        raise ValueError('Low-risk and high-risk policy shares must total 100%.')
    return result


def initial_state():
    # Historical opening book: 750 * 4,000 + 250 * 8,000 = 5m gross premium.
    # Preserve the requested opening benchmark independently of new-round prices.
    # Capital is surplus, not assets: the opening book also carries reserves.
    net = 5_000_000 * (1 - DEFAULT_DECISION['reinsurance'])
    reserve, upr = 1.1 * net, .27 * net
    assets = 3_000_000 + reserve + upr
    return dict(assets=assets, bonds=.70*assets, stocks=.20*assets,
                cash=.10*assets, policies=1000, low_policies=750, high_policies=250,
                loss_reserve=reserve, upr=upr, net_premium=net,
                ad_last=0, ad_previous=0, cumulative=0, surplus=3_000_000)


def regional_shock(seed, period, region):
    """One reproducible region-wide shock; never reroll on refresh/retry."""
    digest = hashlib.sha256(f'{seed}:{period}:{region}'.encode()).digest()
    u = int.from_bytes(digest[:8], 'big') / 2**64
    cumulative = 0.
    for probability, multiplier in REGIONS[region]['shocks']:
        cumulative += probability
        if u < cumulative:
            return multiplier
    return REGIONS[region]['shocks'][-1][1]


def regional_appeal(decision, state, rating, region):
    r = REGIONS[region]
    # Absolute appeal allows collective choices to expand or contract demand.
    # Relative competition is applied after combining the chosen regional mix.
    driver = (.12*(decision['new_commission']/15-1)
              + .06*(decision['renewal_commission']/10-1)
              + .35*(decision['strategy']-4)/4
              + .30*(math.log1p(marketing(decision, state)/57_500)-math.log(2))
              + .12*(1/rating-1))
    log_appeal = (r['appeal_sensitivity']*driver
                  + r['price_elasticity']*math.log(r['reference_premium']/decision[region+'_premium']))
    return math.exp(max(-4, min(4, log_appeal)))


def regional_loss(decision, region, policies, catastrophe, shock):
    r = REGIONS[region]
    premium = decision[region+'_premium']
    gross = policies*premium
    spending = decision[region+'_screening']
    reduction = .05*spending/(spending+.01*gross) if gross > 0 else 0.
    reference_ratio = max(.01, LOSS_RATIOS[decision['strategy']-1]*r['risk_factor'] + catastrophe - reduction)
    cost = r['reference_premium']*reference_ratio
    return dict(name=r['name'], policies=policies, premium=premium, gross=gross,
                screening=spending, screening_reduction=reduction,
                expected_loss_per_policy=cost, expected_loss_ratio=cost/premium,
                shock=shock, loss_ratio=cost/premium*shock)


def marketing(decision, state):
    """Continuous, capped ad carryover; first round uses raw weighted spending."""
    base = state['net_premium']
    current, last = decision['advertising'], state['ad_last']
    promotion = decision['promotion']
    if base > 0:
        current, last = min(current, .065 * base), min(last, .065 * base)
        # Preserve the old 40%–74% promotion bands, correcting the final .074 typo.
        promo = min(promotion, .4 * base)
        promo += sum(base * .0015 for t in (.42, .44, .46, .48, .50, .52, .54, .60) if promotion > t * base)
        promo += sum(base * .001 for t in (.62, .64, .66, .68, .70, .72, .74) if promotion > t * base)
        promo += max(0, promotion - .74 * base) * .2
    else:
        promo = promotion
    return .75 * current + .50 * last + .25 * state['ad_previous'] + promo


def renewal_factor(commission):
    # Original Internal data A:B, reproduced as breakpoints; continuous in 2026.1.
    if commission < 7:
        return .5
    knots = [(7, .42), (8, .37), (9, .34), (10, .29), (11, .25),
             (12, .20), (13, .16), (14, .12), (15, .09), (16, .07),
             (17, .05), (18, .045), (19, .042), (20, .04)]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if commission <= x1:
            return y0 + (y1 - y0) * (commission - x0) / (x1 - x0)
    return .04


def relative(values):
    total = sum(values)
    return [len(values) * v / total for v in values] if total else [1.] * len(values)


def calculate_round(env, teams, decisions, period, total_rounds=DEFAULT_ROUNDS,
                    market_policies=None, risk_seed='test-seed', catastrophe_event_pp=0):
    env = validate_env(env)
    weights = round_weights(total_rounds)
    period = number(period, 'Round', 1, len(weights), True)
    ds = [validate_decision(decisions[str(t['id'])]['values']) for t in teams]
    ratings = [number(t['rating'], 'Rating', 1, 5, True) for t in teams]
    n = len(teams)
    if not 2 <= n <= MAX_TEAMS:
        raise ValueError(f'The number of teams must be between 2 and {MAX_TEAMS}.')
    # Count selected strategies, including teams with zero bond allocation.
    # Integer arithmetic makes the strict 30% boundary exact.
    bond_strategy_2_count = sum(d['bond_strategy'] == 2 for d in ds)
    conditional_bond_return = .08 if 10 * bond_strategy_2_count < 3 * n else .02
    appeals = [{key:regional_appeal(d,t['state'],ratings[i],key) for key in REGIONS}
               for i,(d,t) in enumerate(zip(ds,teams))]
    attraction = [sum(d[key+'_pct']*a[key] for key in REGIONS) for d,a in zip(ds,appeals)]
    potential = number(market_policies if market_policies is not None else n*1000,
                       'Market policy potential', 1e-100, 1e100)
    demand_factor = max(.75, min(1.25, math.sqrt(sum(attraction)/n)))
    volumes = [potential*demand_factor*a/sum(attraction) for a in attraction]
    gross_by_team = [q*sum(d[key+'_pct']*d[key+'_premium'] for key in REGIONS)
                     for q,d in zip(volumes,ds)]
    shocks = {key:regional_shock(risk_seed,period,key) for key in REGIONS}
    results = []
    for i, (t, d) in enumerate(zip(teams, ds)):
        s = t['state']
        gross = gross_by_team[i]
        share = gross / sum(gross_by_team)
        ceded = gross * d['reinsurance']
        net = gross - ceded
        ceding = ceded * env['ceding_rate']
        units = volumes[i]
        regions = {key:regional_loss(d,key,units*d[key+'_pct'],0 if catastrophe_event_pp else env['catastrophe'],shocks[key])
                   for key in REGIONS}
        for key,r in regions.items():
            r['appeal'] = appeals[i][key]
            r['loss_ratio'] += catastrophe_event_pp / 100
        delta = net - s['net_premium']
        upr = s['upr'] + .27 * delta
        earned = net - (upr - s['upr'])
        xp = renewal_factor(d['renewal_commission'])
        old_units = s['policies']
        old_comm = min(units, old_units) * d['renewal_commission'] * (1 - xp)
        new_comm = (max(0, units - old_units) + xp * min(units, old_units)) * d['new_commission']
        new_cost, old_cost = next((a, b) for limit, a, b in [
            (180000, 19, 9), (225000, 18, 8), (350000, 17, 7), (math.inf, 16.5, 6.5)] if units < limit)
        new_expense = (max(0, units - old_units) + xp * old_units) * new_cost
        old_expense = (1 - xp) * old_units * old_cost
        ads = d['advertising'] + d['promotion']
        for r in regions.values():
            r['earned'] = earned * r['gross']/gross
            r['losses'] = r['earned'] * r['loss_ratio']
            r['expected_losses'] = r['earned'] * r['expected_loss_ratio']
        losses = sum(r['losses'] for r in regions.values())
        loss_ratio = sum(r['gross']/gross*r['loss_ratio'] for r in regions.values())
        screening = d['low_screening'] + d['high_screening']
        adjustment = .1 * gross
        pretax = earned - old_comm - new_comm - new_expense - old_expense - ads - screening - losses - adjustment
        tax = .34 * pretax
        underwriting = pretax - tax
        bonds, stocks = s['assets'] * d['bond_pct'], s['assets'] * d['stock_pct']
        transaction = .005 * (abs(s['bonds'] - bonds) + abs(s['stocks'] - stocks))
        cash = s['assets'] * d['cash_pct'] - transaction
        invested_pct = d['bond_pct'] + d['stock_pct']
        pb = d['bond_pct'] / invested_pct if invested_pct else 0
        ps = d['stock_pct'] / invested_pct if invested_pct else 0
        investment_base = bonds + stocks + .3 * delta if invested_pct else 0
        bond_return = .04 if d['bond_strategy'] == 1 else conditional_bond_return
        stock_multiplier = STOCK_MULTIPLIERS[d['stock_strategy'] - 1]
        stock_return = env['stock_return'] * stock_multiplier
        bond_income = pb * bond_return * investment_base * .85
        stock_income = ps * stock_return * investment_base * .66
        cash += underwriting + .1 * delta + ceding
        if not invested_pct:
            cash += .6 * delta
        bonds += pb * .6 * delta + bond_income
        stocks += ps * .6 * delta + stock_income
        assets = cash + bonds + stocks
        reserve = .6 * net + .5 * s['net_premium']
        surplus = assets - reserve - upr
        score = surplus
        cumulative = s['cumulative'] + weights[period - 1] * score
        warnings = []
        if cash < 0: warnings.append('Negative cash balance')
        if surplus <= 0: warnings.append('Non-positive surplus: insufficient solvency')
        elif net / surplus >= 3: warnings.append('Net written premium / surplus ≥ 3')
        if upr < 0: warnings.append('Negative unearned premium reserve')
        next_state = dict(assets=assets, cash=cash, bonds=bonds, stocks=stocks,
                          policies=units, low_policies=regions['low']['policies'], high_policies=regions['high']['policies'],
                          loss_reserve=reserve, upr=upr,
                          net_premium=net, ad_last=d['advertising'], ad_previous=s['ad_last'],
                          cumulative=cumulative, surplus=surplus)
        results.append(dict(team_id=t['id'], name=t['name'], share=share, gross=gross,
                            bond_strategy=d['bond_strategy'], stock_strategy=d['stock_strategy'],
                            bond_return=bond_return, stock_return=stock_return,
                            stock_multiplier=stock_multiplier, stock_base_return=env['stock_return'],
                            bond_strategy_2_count=bond_strategy_2_count, team_count=n,
                            net=net, policies=units, retained_policies=units*(1-d['reinsurance']),
                            regions=regions, screening=screening,
                            market_policies=potential, demand_factor=demand_factor,
                            ceded=ceded, ceding=ceding, earned=earned, loss_ratio=loss_ratio,
                            losses=losses, adjustment=adjustment, advertising=ads,
                            old_commission=old_comm, new_commission=new_comm,
                            old_expense=old_expense, new_expense=new_expense,
                            transaction=transaction, pretax=pretax, tax=tax,
                            underwriting=underwriting, bond_income=bond_income,
                            stock_income=stock_income, income=underwriting+bond_income+stock_income,
                            score=score, cumulative=cumulative, warnings=warnings,
                            next_state=next_state))
    return rank_results(results)
