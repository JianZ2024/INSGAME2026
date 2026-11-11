# INSGAME2026 · Rules version 2026.6

This is a synthetic classroom insurance model based on the original INSGAME.xls. Regional loss assumptions are teaching choices, not estimates of a real insurance market. Amounts are currency units (CU). One round represents one year. The interface is entirely English.

## 1. Objective and weighted surplus

The objective is to maximize **cumulative weighted surplus**:

    contribution in round t = closing surplus in round t × round weight t
    cumulative weighted surplus = sum of contributions through that round

The highest cumulative weighted surplus wins. The round rank compares closing surplus; the overall rank compares cumulative weighted surplus. Equal values share a rank (relative tolerance 1e-12). Negative surplus reduces the cumulative total. Assets and written premium do not contribute separate score points. Stored `score` means closing surplus; `cumulative` means cumulative weighted surplus.

The instructor chooses 1–99 rounds, default 5, before the first calculation. For N rounds, L=floor((N+1)/2), R=ceil((N+1)/2), using one-based indexing. Set both middle raw weights to 1. Before L, use 0.8^(L-i); after R, use 1.2^(i-R). Divide all raw weights by their sum. An even number of rounds has two equal middle weights. Five rounds use 16:20:25:30:36, divided by 127; six use 16:20:25:25:30:36, divided by 152. Display rounding never changes calculation precision.

## 2. Opening company and market

Each company starts with **3,000,000 surplus and 1,000 gross policies**:

| Region | Policies | Historical opening premium | Gross premium |
|---|---:|---:|---:|
| Low risk | 750 | 4,000 | 3,000,000 |
| High risk | 250 | 8,000 | 2,000,000 |
| Total | 1,000 | weighted average 5,000 | 5,000,000 |

The initial market premium benchmark is **5,000,000 × number of teams**. This is not a fixed premium pool for later calculations. An opening 10% reinsurance share gives net premium of 4,500,000. Opening loss reserve is 1.1 × net premium = 4,950,000; unearned premium reserve is 27% × net premium = 1,215,000. Assets therefore equal 3,000,000 + these reserves = **9,165,000**. Surplus is net capital, not total assets. Opening assets are 10% cash, 70% bonds, and 20% stocks. Advertising history and the cumulative score start at zero.

The historical opening book and reserves retain that benchmark. New-round default and reference premiums are now **100 CU for low risk and 150 CU for high risk**. At 1,000 policies and a 75%/25% mix, these produce **112,500 CU** written premium, not 5 million. The lower new-round prices do not revalue opening balances; first-round reserve movements still compare new business with the historical book. Marketing budgets and unit operating costs are not rescaled.

## 3. Regional choices and changing demand

Each team chooses:

- Low-risk premium, from 50 to 10,000 per policy, default 100.
- High-risk premium, from 75 to 20,000 per policy, default 150.
- Low-risk and high-risk policy proportions, each 0–100%, totaling 100%.
- Separate underwriting screening budgets for each region.

These are exact proportions of the team's modeled gross policy count. Fractional policy counts are permitted for smooth classroom calculations; the UI rounds counts for readability. Market share is the team's actual gross premium divided by all teams' actual gross premium.

Market volume responds to decisions. Let M be effective marketing spending, S underwriting strategy, CN new commission, CR renewal commission, and rating range from 1 (best) to 5. The non-price appeal driver is:

    D = .12 × (CN/15 − 1) + .06 × (CR/10 − 1)
        + .35 × (S−4)/4
        + .30 × [ln(1 + M/57,500) − ln(2)]
        + .12 × (1/rating − 1)

For region r:

    log appeal = sensitivity[r] × D
                 + price elasticity[r] × ln(reference premium[r] / chosen premium[r])
    appeal[r] = exp(clamp(log appeal, −4, 4))
    company appeal = low proportion × low appeal + high proportion × high appeal

| Region | Non-price appeal sensitivity | Price elasticity |
|---|---:|---:|
| Low risk | 1.0 | 1.4 |
| High risk | 1.6 | 1.1 |

Thus more generous acceptance and stronger marketing lift high-risk appeal more strongly. Low risk responds more to price. Adverse non-price choices also have a stronger effect in high risk.

Initial customer potential is 1,000 × number of teams. In each round:

    demand multiplier = clamp(sqrt(mean company appeal), .75, 1.25)
    actual market policies = customer potential × demand multiplier
    company policies = actual market policies × company appeal / total appeal
    regional policies = company policies × selected regional proportion
    regional gross premium = regional policies × selected regional premium
    next customer potential = actual market policies × (1 + market growth)

The instructor sets annual customer market growth, default 2%, allowed range −20% to 20%. Actual premium changes with demand, pricing, and the chosen mix; it is not conserved across teams or rounds. The regions are business segments without separate fixed population caps. Team decisions influence both market size and competitors' shares.

## 4. Underwriting and loss distributions

Higher underwriting strategies accept more applicants. They increase appeal and expected losses. Every base loss ratio has been reduced by **10 percentage points** from the prior version:

| Strategy | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Base ratio | 39% | 44% | 47% | 51% | 56% | 62% | 67% | 73% | 80% |

The region's risk factor and reference premium determine expected claim cost. A team's quoted premium changes its loss ratio, not the claim cost itself.

| Region | Risk factor | Annual loss multiplier and probability |
|---|---:|---|
| Low risk | 0.85 | 0.8× with 25%; 1.0× with 50%; 1.2× with 25% |
| High risk | 1.25 | 0.6× with 60%; 1.2× with 30%; 2.8× with 10% |

Both multiplier distributions have mean 1. Their variances are 0.02 and 0.432, respectively. High risk has both higher average claim costs and a much heavier aggregate loss tail. Reference premiums used for claim severity and price appeal are **100 low risk / 150 high risk**. At Strategy 4, before screening/catastrophe increments, expected claim cost is **43.35 per low-risk policy** and **95.625 per high-risk policy**. At reference premiums, expected loss ratios are 43.35% and 63.75%.

One independent region-wide shock is drawn per round. Every team receives the same shock in that region, allowing fair comparison of decisions. This is an aggregate annual loss distribution, not an individual claim-frequency simulation. A private game seed and the round/region identifiers generate the draw through SHA-256; calculation retries never reroll. Students cannot access the seed or unpublished shocks.

## 5. Underwriting screening spending

For screening budget U and regional gross premium G:

    reference-ratio reduction = .05 × U / (U + .01 × G)

If G is zero, the reduction is zero, but the entire entered budget remains an expense. Spending 1% of G gives a 2.5-percentage-point reduction at the reference premium. The reduction approaches, but cannot exceed, 5 percentage points. Larger budgets have diminishing benefit. Screening affects only its own region and does not add customer appeal.

    reference loss ratio = max(.01, base ratio × regional risk factor
                                    + catastrophe increment − screening reduction)
    expected claim cost per policy = reference premium × reference loss ratio
    expected loss ratio = expected claim cost / chosen premium
    actual loss ratio = expected loss ratio × regional annual shock

The instructor's catastrophe increment is entered in percentage points and added before the regional shock. Final realized ratios may exceed 100%. The full two-region screening budget is deducted in the current round. The student form's expected-cost previews are before screening; settlement reports show the actual screening reduction and post-screening expected ratio.

## 6. Marketing and policy costs

Advertising contributes 75% of current spending, 50% of last round, and 25% from two rounds ago. When previous net premium is positive, current and last-round amounts are each capped at 6.5% of that premium for marketing effect; the oldest term is uncapped. Full current spending is expensed.

Promotion contributes only this round. With previous net premium P > 0: start with min(promotion, .4P); add .0015P for each exceeded threshold in [.42,.44,.46,.48,.50,.52,.54,.60] × P; add .001P for each exceeded threshold in [.62,.64,.66,.68,.70,.72,.74] × P; then add 20% of spending above .74P. With zero previous net premium, use raw promotion. These bands retain the prior teaching model.

New and renewal commissions are 0–50 CU per policy. The renewal cost factor xp is .5 below commission 7; then linearly interpolate these nodes: 7/.42, 8/.37, 9/.34, 10/.29, 11/.25, 12/.20, 13/.16, 14/.12, 15/.09, 16/.07, 17/.05, 18/.045, 19/.042, 20/.04. Above 20, xp=.04.

With current gross policies q and previous gross policies o:

    renewal commission = min(q,o) × renewal rate × (1−xp)
    new commission = [max(q−o,0) + xp × min(q,o)] × new rate
    new operating cost = [max(q−o,0) + xp × o] × new-policy unit cost
    renewal operating cost = (1−xp) × o × renewal-policy unit cost

At q below 180,000 / 225,000 / 350,000 / otherwise, new unit costs are 19 / 18 / 17 / 16.5, and renewal costs 9 / 8 / 7 / 6.5. Advertising, promotion, and each screening budget permit 0–1 billion CU; spending is not free simply because it exceeds its effective marketing/screening limit.

## 7. Accounting and surplus

The reserve and investment accounting retains the prior model's structure. Let P be current net written premium, P0 previous net premium, and ΔP=P−P0. Reinsurance applies equally to both regions.

    gross premium = low-risk gross + high-risk gross
    ceded premium = gross premium × reinsurance share
    net premium P = gross − ceded
    ceding commission cash = ceded premium × instructor's ceding rate
    closing UPR = opening UPR + .27 × ΔP
    earned premium = P − change in UPR
    regional earned premium = earned premium × region gross / total gross
    regional incurred losses = regional earned premium × region actual loss ratio
    loss adjustment expense = .10 × gross premium
    pretax underwriting = earned premium − commissions − operating costs
                          − advertising − promotion − screening
                          − incurred losses − loss adjustment expense
    after-tax underwriting = .66 × pretax underwriting
    closing loss reserve = .6 × P + .5 × P0
    closing surplus = total assets − closing loss reserve − closing UPR

Negative underwriting income produces an immediate 34% model tax credit. Ceding commission enters cash but is excluded from the displayed total income, preserving the prior convention. Consequently, total income and the change in surplus are not interchangeable. This is a classroom accounting model, not a regulatory capital standard.

Opening assets are allocated to cash C0, bonds B, and stocks S. Rebalancing cost T=.005 × (|previous bonds−B| + |previous stocks−S|). If securities allocation is positive, let b=bond fraction/(bond+stock fractions), s=1−b:

    investment base = B + S + .3 × ΔP
    bond income = b × bond return × investment base × .85
    stock income = s × stock return × investment base × .66
    closing bonds = B + b × .6 × ΔP + bond income
    closing stocks = S + s × .6 × ΔP + stock income
    closing cash = C0 − T + after-tax underwriting + .1 × ΔP + ceding cash

With all cash, securities and investment income are zero and cash also receives .6 × ΔP. Total assets sum cash, bonds, and stocks. Total income sums after-tax underwriting, bond income, and stock income. Negative cash/surplus or high leverage triggers a warning; no automatic bankruptcy or elimination is added. The formula continues even for negative opening assets, an explicit model limitation.

## 8. Investment choices and cash

Cash allocation must be **at least 10%**; cash, bonds, and stocks total 100%. This applies to opening allocations. Subsequent expenses and operating flows may reduce the closing cash ratio.

- Bond strategy 1: fixed annual return 4%.
- Bond strategy 2: 8% if strictly fewer than 30% of all teams choose it, otherwise 2%. Exactly 30% earns 2%. Teams selecting it count even with zero bond allocation. In a 3-team game, any selection receives 2%.
- Stock strategies 1–5: 80%, 100%, 120%, 140%, or 200% of the instructor's base annual stock return (set privately by the instructor in Market Overview during an open round; permitted −100% to 100%). Students choose a multiplier without seeing the configured base or the resulting annual rates. A negative base multiplies the loss. These choices add no independent random risk.
- Rates are before investment tax. Bond income retains 85%; stock income retains 66%. Strategy changes alone add no fee; the 0.5% fee applies to changes in the amounts of securities held.

## 9. Workflow, privacy, and upgrade

Only instructors set classroom conditions, ratings, and length. Teams can save drafts, submit, and edit until locking. All teams must submit before locking. The instructor calculates once, reviews, publishes, and opens the next round. Calculated financial results are immutable. Next-round decisions become drafts.

Students see only their own decisions and full published financial results. Published leaderboards show all teams' market shares, surplus scores, weighted surplus, and ranks. The private seed, other companies' detailed regional results, and unpublished results stay hidden. Teacher dashboards, CSV/JSON exports, and printing use stored settlement results.

On upgrading from the single-market model, the server backs up the database as `insgame.sqlite3.before-regions-2026.5-<id>.bak`. Classrooms without calculated rounds receive the new opening books. The current converter maps old premium ×1 for low risk and ×1.5 for high risk (the original 2026.5 converter used ×40 / ×80). New policy mix is 75%/25%; screening defaults to zero. Other numeric choices remain saved. Uncalculated locked rounds reopen, and open-round submissions require review and resubmission.

Classrooms with financial history retain their financial results and balances. Their historical scoring is recalculated as weighted surplus, while original score figures are retained as `legacy_score` and `legacy_cumulative`; calculation-version metadata remains. A notice explains the retained opening book. Their new regional customer potential starts at 1,000 × team count; create a new classroom for a fully uniform 2026.5 run. Classroom codes, passwords, and recoverable deletion status remain unchanged. Migration is idempotent.

The 2026.6 premium update first saves `insgame.sqlite3.before-premiums-2026.6-<id>.bak`. It replaces 4,000 / 8,000 only in untouched, unsubmitted starting drafts without financial history. Saved quotes and all historical decisions, financial results, ranks, seeds, opening balances, credentials, and deletion status remain intact. Existing uncalculated rounds reopen and require resubmission because future claims and appeal use the new references. Stale forms are rejected. New regular classrooms default to 100 / 150; demo quotes vary around them. The old upper input bounds remain so saved choices remain editable. This upgrade is idempotent.

## 10. Verification

Automated checks cover independently calculated symmetric accounts, weights for 1–99 rounds, exact policy splits including single-region books, seeded shared shocks and distribution means, dynamic premium/demand, price versus claim severity, screening bounds and expense, surplus scoring, investment thresholds, 10% cash enforcement, lifecycle/privacy/export behavior, concurrency, recoverable deletion, and backed-up migration. Browser checks cover student entry and submission, reports, and responsive layouts. Exact numerical equivalence with original VBA is not claimed.

## Roster changes

In any open round, an instructor can add or remove a team within the 2–50 active team limit. Existing numbers and all calculated history are preserved. Late entrants start with the standard opening book and earn no score for missed rounds. The current round’s policy potential scales by the new team count divided by the old count. Before the first settlement the opening premium benchmark also scales to 5 million CU per team. Roster edits or changes to the base stock return reopen submissions without discarding the surviving teams’ decisions.


## Optional common catastrophe event

The manual catastrophe adjustment affects the reference-price loss ratio before the usual regional shock. Alternatively the instructor can enable a random catastrophe for one open round. In this mode the manual adjustment is ignored. At settlement the server draws a single uniformly distributed integer from 5 through 20. For both regions of every team, actual loss ratio = ordinary realized loss ratio + draw / 100. Thus a 40% realized ratio becomes 52% with a 12-point event. The event changes losses on retained earned premium, not customer demand. The stored event is not redrawn when viewing or publishing. The next round starts with the random event off.
