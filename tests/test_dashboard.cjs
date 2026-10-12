// Run with Node.js. No packages or browser dependencies are needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..', 'static');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(root, 'app.js'), 'utf8').split('\ndocument.addEventListener')[0], context);
vm.runInContext(fs.readFileSync(path.join(root, 'dashboard.js'), 'utf8'), context);
const run = code => vm.runInContext(code, context);
function fixture(values) {
  context.rows = values.map((income, i) => ({team_id:i+1,name:`Team ${String(i+1).padStart(2,'0')}`,
    share:1/values.length,policies:1234+i,income,cumulative:income*10,next_state:{assets:500000+i,surplus:income*5},overall_rank:i+1}));
  run("user={role:'teacher'};game={id:'QA',name:'Chart QA',total_rounds:5,history:[{period:1,published:true,results:rows}]};periodView=1;view='dashboard';");
}
fixture([-100, 0, 300]);
let html = run('instructorDashboard()');
assert(html.includes('Market share by team'));
assert(html.includes('Policies written by team'));
assert(html.includes('Profit / loss by team'));
assert(html.includes('Total assets by team'));
assert(html.includes('Cumulative weighted surplus by team'));
assert(html.includes('Team 01: -100 CU'));
assert(html.includes('Team 01: 1,234 policies'));
assert(html.includes('Team 01: 500,000 CU'));
assert(!/NaN|Infinity|undefined/.test(html));
let bars = run("comparisonBars(rows,'income','Profit / loss','CU')");
const zero = Number(bars.match(/y1="([^"]+)" y2="[^"]+" class="chart-zero"/)[1]);
const rects = [...bars.matchAll(/<rect x="[^"]+" y="([^"]+)" width="[^"]+" height="([^"]+)"/g)];
assert.equal(Number(rects[0][1]), zero); // Loss extends downwards from zero.
assert(Number(rects[0][2]) > 0);
assert.equal(Number(rects[1][2]), 0);
assert(Number(rects[2][1]) < zero); // Positive profit rises above zero.
for (const values of [[0,0],[-10,-20],[10,20],Array.from({length:20},(_,i)=>i-10)]) {
  fixture(values);
  html = run('instructorDashboard()');
  assert(!/NaN|Infinity|undefined/.test(html));
  assert.equal((run('marketSharePie(rows)').match(/data-compare-team=/g)||[]).length,values.length);
  assert.equal((run("comparisonBars(rows,'income','Profit / loss','CU')").match(/<rect /g)||[]).length,values.length);
}
fixture([10,20]);
run('game.history.push({period:2,published:false,results:rows.map(r=>({...r,policies:9876}))});periodView=2;');
html=run('instructorDashboard()');
assert(html.includes('Round 2 of 5'));
assert(html.includes('Instructor preview · unpublished'));
assert(html.includes('9,876 policies'));
run("rows[0].name='<img src=x onerror=alert(1)>';periodView=1;");
assert(!run('instructorDashboard()').includes('<img src=x'));
run('game.history=[];');
assert(run('instructorDashboard()').includes('Calculate a round'));
run("user={role:'student'};");
assert(run('instructorDashboard()').includes('Instructor access required'));
console.log('Dashboard checks passed: data mapping, negative/zero/positive bars, 20 teams, round selection, empty state, escaping, and instructor access.');
