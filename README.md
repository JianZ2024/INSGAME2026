# INSGAME2026

**An interactive insurance market simulation for classroom teaching.**

Students manage competing insurance companies in a browser. An instructor controls the classroom, reviews decisions, calculates rounds, and publishes results. Python and SQLite handle the server and data; plain HTML/CSS/JavaScript provide the English interface.

Current rules: **2026.6**. This repository contains source code and synthetic examples. Each installation creates its own classroom database and credentials.

## 1. Project purpose

INSGAME2026 turns the classroom workflow of the legacy `INSGAME.xls` VBA game into a standalone web application. Students explore how pricing, underwriting, marketing, reinsurance, and investments affect growth, claims, capital, and performance relative to competitors.

The objective is to maximize **cumulative weighted surplus**:

```text
Round contribution = closing surplus × round weight
Overall score       = sum of round contributions
```

The largest overall score wins. Assets and premium volume do not add separate points. Each round represents one year; CU means currency units.

This is a synthetic teaching model, not an estimate of a real insurance market. Exact numerical equivalence with the original VBA workbook is not claimed. Excel and VBA are not required; the application does not read or modify the original workbook. See [RULES.md](RULES.md) for complete formulas and limitations.

## 2. Main features

| Area | Implemented functionality |
|---|---|
| Classrooms | Multiple classrooms; 2–20 teams; 1–99 rounds, default 5; a five-team demo; recoverable deletion and restoration |
| Instructor controls | Team passwords, entry on behalf of teams, conditions and ratings, locking, once-only calculation, publication, and round progression |
| Student workspace | Game code / team number / team password login; private decisions; drafts, submission, and resubmission before locking |
| Two markets | Separate low/high-risk premiums, exact policy proportions totaling 100%, different losses, and regional screening budgets |
| Business decisions | Advertising, sales promotion, new and renewal commissions, underwriting strategy, and reinsurance |
| Investments | Cash/bond/stock allocation, two bond strategies, five stock multipliers, and at least 10% opening cash allocation |
| Reports | Regional losses, balance sheets, underwriting/investment income, round history, rankings, and score trends |
| Instructor dashboard | Market-share pie chart; bars for policies, profit/loss, assets, and cumulative weighted surplus; exact-value table |
| Exports | Role-filtered CSV, instructor JSON records with team passwords removed, and browser printing |
| Storage | SQLite persistence, transactions, stale-form protection, carryforward, and versioned upgrades with database backups |
| Interface | Responsive English pages, with charts and assets served locally without a CDN dependency |

### Current game settings

- Each team starts with **3,000,000 CU surplus and 1,000 policies**. Total opening assets are **9,165,000 CU**, including assets backing reserves.
- New-round default and reference premiums are **100 CU low risk / 150 CU high risk**, with a **75% / 25%** default policy mix.
- Underwriting strategies 1–9 use base ratios of **39%, 44%, 47%, 51%, 56%, 62%, 67%, 73%, and 80%**. Higher strategies attract customers and increase expected losses.
- Screening is fully expensed and has diminishing returns: spending 1% of regional premium reduces the reference-price loss ratio by 2.5 percentage points, approaching a 5-point cap.
- Total market premium responds to demand, prices, and policy mix. Customer growth defaults to 2% and is editable by the instructor.
- Bond 1 earns 4%. Bond 2 earns 8% when **strictly fewer than 30% of all teams** select it; otherwise it earns 2%. Selection counts even with zero bond allocation.
- Stock choices are **80%, 100%, 120%, 140%, or 200% of the base return**. At an example 12% base, the rates are **9.6%, 12%, 14.4%, 16.8%, and 24%**. A negative base also multiplies losses.
- Round weights start at 1 in the middle, multiply by 0.8 moving backward and 1.2 moving forward, then normalize to 100%. Even round counts have equal middle weights. Five rounds use **16:20:25:30:36**, divided by 127.

**Opening book versus new prices:** the historical opening premium benchmark remains **5 million CU per team**, with its associated reserves. At 1,000 policies, a 75%/25% mix and 100/150 prices, new written premium is **112,500 CU**. Opening balances, marketing budgets, and unit costs are not rescaled; first-round reserve movements reflect that change. See [RULES.md](RULES.md).

## 3. Installation

### Requirements

- **Python 3.10 or later**, with its standard `sqlite3` module.
- A modern browser, such as Edge, Chrome, Firefox, or Safari.
- Optional: VS Code for editing and Git for cloning/publishing.

All server dependencies are included with Python. **No `pip install`, Node.js, Excel, or database server setup is required to run the game.** `requirements.txt` is informational. Node.js is optional for frontend checks only.

### Download and start

1. Download this repository using **Code → Download ZIP**, or clone your GitHub repository.
2. Extract it and open the directory containing **`app.py`**. In VS Code, use **File → Open Folder**, then **Terminal → New Terminal**.
3. Run:

   ```powershell
   python --version
   python app.py
   ```

   On Windows, `py -3 app.py` also works. On macOS/Linux, use `python3 app.py` if the executable is named `python3`.

4. Open **<http://localhost:2026/>**. Keep the terminal running. Opening `app.py` in an editor alone does not start the server.
5. Stop with **Ctrl+C**. Saved classrooms remain available after restarting.

With the VS Code Python extension installed, **F5 → Run INSGAME2026** uses `.vscode/launch.json`. Open the application folder itself for this configuration to work.

### Startup options

| Setting | Default | Purpose |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address; `0.0.0.0` allows trusted LAN access |
| `--port` | `2026` | HTTP port |
| `--data-dir` | `data/` beside `app.py` | Database and teacher-password directory |
| Environment variable `INSGAME_ADMIN_KEY` | Read `data/admin_key.txt` | Override teacher password; at least 8 characters |

If the port is busy, use `python app.py --port 2027` and open <http://localhost:2027/>. To try the game separately from existing classrooms:

```powershell
python app.py --port 2027 --data-dir ./data-demo
```

## 4. Usage

### Instructor workflow

1. Select **Instructor**. Open `data/admin_key.txt` on the server computer and enter its contents as the **Teacher password**. It is generated on first startup. If you set `INSGAME_ADMIN_KEY`, use that value instead; for a custom `--data-dir`, read `admin_key.txt` in that directory. The terminal reports the password source without printing the password.
2. Choose **New classroom**, specify the round-one base annual stock return, enter a name, choose 2–20 teams, and set 1–99 rounds (default 5).
3. In **Classroom Overview**, distribute the game code, team number, and each team's own password. **Copy access details** copies the address and game code; distribute team passwords separately. After a team sets its own password, you see **Set by team** instead of its password. Use **Reset password** on that team's row to issue a new temporary password and sign out that team. Resetting does not change decisions or results.
4. Review **Company Decisions**. Normal classrooms begin with drafts; all teams must submit before **Lock decisions** becomes available. The instructor may enter decisions on behalf of teams.
5. Choose **Lock decisions → Calculate round**. Review **Instructor Dashboard** and **Performance Reports** before publishing.
6. Choose **Publish results → Open next round**. Balances and marketing history carry forward. Teams must submit again. Publishing the final round finishes the game.

In **Classroom Overview**, use **Add team** or **Remove team** while decisions are open (2–20 active teams). Removal signs that team out. Surviving team numbers and completed reports remain unchanged; new teams start with the standard opening book and zero cumulative score. The current customer pool scales with the active team count, preserving potential customers per team. Roster changes and base stock return changes preserve decision values but require fresh submissions. The stock base carries forward until edited.

The round count is editable while submissions are open and before the first calculation. Conditions and ratings are editable while the current round is open. A locked but uncalculated round can be unlocked; calculated rounds cannot be recalculated through the interface.

### Student workflow

1. Open the instructor's website. Select **Read the game rules before signing in** for the public guide, or select **Student** to play.
2. Enter the **game code**, **team number**, and **team password** provided by the instructor. On first sign-in, choose a shared password (8–128 characters, case-sensitive), or **Skip for now** to keep the assigned password. Skipping applies to the whole team; use **Set team password** in Classroom Overview if you change your mind. Share a new password with your teammates: their previous sessions are signed out. Existing classrooms keep their assigned passwords until a team changes one or the instructor resets it.
3. Set regional prices and policy proportions, screening, marketing, commissions, underwriting, reinsurance, and investments.
4. Make regional proportions total 100%, make asset allocations total 100%, and allocate at least 10% to cash.
5. Choose **Save draft** or **Submit decisions**. Submitted decisions remain editable until locking.
6. After publication, read the team's own report and the public leaderboard.

Students cannot access other teams' detailed decisions or financial reports. For teacher/student testing on one computer, use a separate browser or private window; a browser session has one role at a time.

### Multiple devices on a trusted LAN

```powershell
python app.py --host 0.0.0.0
```

Use `ipconfig` on Windows to find the server computer's local IPv4 address. Students open `http://SERVER-IP:2026`, for example `http://192.168.1.25:2026`. Keep the server running and allow access through the firewall and school network. School Wi-Fi may isolate devices. `localhost` always means the device opening the page. Open the instructor page using its LAN address before using **Copy access details**.

### Dashboard, exports, and recovery

The instructor dashboard compares calculated rounds, including unpublished instructor previews. Select a round, click a team in the pie legend to highlight it across charts, or use **View report** to inspect the team's accounts.

Market share measures **gross premium**. Policies sum the two regions' gross policy counts. Profit/loss matches report **Total income**: after-tax underwriting plus bond and stock income. Total income is not necessarily the change in surplus because of the model's reserve and ceding-commission accounting.

**Performance Reports** offers CSV, instructor JSON, and printing. JSON omits team passwords but can contain private teaching and simulation data; it is not a directly importable database backup. The instructor's overview and dashboard refresh about every 10 seconds when there are no unsaved edits.

**Delete classroom** is available in **My Classrooms** and **Classroom Overview**, with a confirmation dialog. Deleted classrooms leave the active list and students lose access. **Deleted classrooms → Restore classroom** restores their saved progress and credentials. There is no permanent purge button.

## 5. Demonstration examples

### Try the real browser interface

1. Sign in as the instructor and choose **Create demo** (or **Start with a demo** in an empty installation).
2. Keep the default five rounds. Five teams already have different submitted decisions.
3. Choose **Lock decisions → Calculate round**.
4. Open **Instructor Dashboard** to see the market-share pie and four comparison bar charts.
5. Open **Performance Reports** to inspect regional losses and accounts, then publish the round.

The demo exercises the actual application; it does not import historical Excel results.

### Reproducible calculated example

```powershell
python examples/demo_round.py
```

This script uses the browser demo's starting decisions, the real engine, and a temporary database. A **public fixed seed** produces low/high first-round loss multipliers of **1.0 / 0.6**. Browser classrooms use their own private random seeds, so their results can differ. The script never reads your live `data/` directory.

<!-- example-results:start -->
| Team | Market share | Policies | Gross premium | Closing surplus | Weighted surplus | Rank |
|---|---:|---:|---:|---:|---:|---:|
| Team 01 | 15.17% | 791.27 | 88,423.98 | 4,543,297.97 | 572,384.00 | 2 |
| Team 02 | 18.39% | 936.99 | 107,168.55 | 4,508,185.41 | 567,960.37 | 3 |
| Team 03 | 27.82% | 1,312.93 | 162,147.05 | 4,412,404.25 | 555,893.45 | 5 |
| Team 04 | 14.52% | 743.97 | 84,589.44 | 4,552,991.34 | 573,605.21 | 1 |
| Team 05 | 24.10% | 1,125.32 | 140,439.96 | 4,470,184.10 | 563,172.80 | 4 |
<!-- example-results:end -->

Amounts are CU; policies retain fractional precision. This is round 1 of 5: weighted surplus = closing surplus × **16/127**. These are generated teaching results, not student records or forecasts. See [the complete example inputs and output](docs/EXAMPLE_RESULTS.md).

## Data, backups, and hosting scope

- `data/insgame.sqlite3` stores classrooms, credentials, decisions, results, audit records, and sessions. `data/admin_key.txt` contains the generated teacher password; keep it private.
- For a full backup or device transfer, stop the server and copy the entire `data/` folder. Stop the destination server before restoring. Do not run two servers against one Dropbox-synchronized database.
- Rules upgrades can back up and migrate older databases. Keep the application version alongside a backup if you need to restore an older ruleset; current code may apply migrations again. See [RULES.md](RULES.md).
- `.gitignore` excludes runtime data, credentials, database backups, local handoff notes, environments, and old previews. The clean source release does not include existing classrooms.

**Hosting scope:** this version uses Python's standard-library HTTP server for local or trusted-LAN teaching. It does not include a verified public Railway deployment, Docker setup, or production hosting configuration. Before public hosting, adapt the server and authentication: configure HTTPS, add login rate limiting and secure cookies, and persist SQLite on a volume. GitHub stores source; GitHub Pages alone cannot run this Python backend.

## Tests and development

```powershell
python -m unittest discover -s tests -v
python examples/demo_round.py --check
```

The Python tests cover team password setup and reset, calculations, 1–99 round weights, investment thresholds, cash validation, regional losses and screening, migrations, concurrency, privacy, lifecycle actions, deletion/restoration, HTTP endpoints, and exports.

With Node.js installed, run these optional checks. They use built-in modules and need no npm packages:

```powershell
node tests/test_dashboard.cjs
node tests/test_market.cjs
```

The included [GitHub Actions workflow](.github/workflows/checks.yml) is configured for Windows/Linux with Python 3.10 and 3.12, example verification, source packaging, and frontend checks. Remote CI results will be available after you push the repository; a successful remote run is not claimed here.

After an intentional rules change, run `python examples/demo_round.py --write`, review the updated documentation, and rerun the tests. Keep browser previews and [RULES.md](RULES.md) aligned with the engine.

```text
app.py                     HTTP service, authentication, static files, exports
engine.py                  Validation, market and financial calculations
store.py                   SQLite, lifecycle, migrations, access filtering
static/                    English browser interface and charts
tests/                     Python and optional Node checks
examples/demo_round.py     Reproducible example using the real engine
docs/EXAMPLE_RESULTS.md    Generated example inputs and results
docs/GITHUB_UPLOAD.md      Clean upload and update instructions
tools/build_release.py     Allowlisted source ZIP builder
.github/workflows/         GitHub Actions checks
.vscode/launch.json        Optional VS Code debug configuration
RULES.md                   Complete model formulas and limitations
```

See [Publishing this project](docs/GITHUB_UPLOAD.md) for GitHub instructions. To rebuild the clean package, run `python tools/build_release.py`; the result is `releases/INSGAME2026-github.zip`.

## License

The INSGAME2026 source code is distributed under the [MIT License](LICENSE), copyright 2026 INSGAME2026 contributors. The original Excel workbook is not included in this repository or covered by this license.
