'use strict';

// All charts use settled server results, including instructor-only previews.
const dashboardColor = id => colors[(id - 1) % colors.length];
function marketSharePie(rows){
 const total=rows.reduce((sum,r)=>sum+r.share,0);
 if(total<=0)return '<p class="empty muted">No market share data for this round.</p>';
 let angle=-Math.PI/2;
 const slices=rows.map(r=>{
  const start=angle,sweep=2*Math.PI*r.share/total;angle+=sweep;
  const point=a=>[160+132*Math.cos(a),160+132*Math.sin(a)];
  const [x1,y1]=point(start),[x2,y2]=point(angle),mid=start+sweep/2;
  const path=sweep>=2*Math.PI-1e-10?`M 160 28 A 132 132 0 1 1 160 292 A 132 132 0 1 1 160 28 Z`:`M 160 160 L ${x1} ${y1} A 132 132 0 ${sweep>Math.PI?1:0} 1 ${x2} ${y2} Z`;
  return `<g class="chart-mark" data-chart-team="${r.team_id}"><path d="${path}" fill="${dashboardColor(r.team_id)}" stroke="white" stroke-width="2"><title>${esc(r.name)}: ${pct(r.share)}</title></path>${r.share>=.06?`<text x="${160+91*Math.cos(mid)}" y="${165+91*Math.sin(mid)}" text-anchor="middle" class="pie-label">${pct(r.share)}</text>`:''}</g>`;
 }).join('');
 return `<div class="pie-layout"><svg class="market-pie" viewBox="0 0 320 320" role="img" aria-label="Market share by team">${slices}</svg><div class="pie-legend" aria-label="Highlight a team">${rows.map(r=>`<button class="legend-team" data-compare-team="${r.team_id}" aria-pressed="false"><i style="background:${dashboardColor(r.team_id)}"></i><span>${esc(r.name)}</span><strong>${pct(r.share)}</strong></button>`).join('')}</div></div>`;
}

function comparisonBars(rows,key,label,unit){
 const values=rows.map(r=>['assets','surplus'].includes(key)?r.next_state[key]:r[key]);
 let low=Math.min(0,...values),high=Math.max(0,...values);
 if(low===high)high=1;
 if(low<0)low*=1.16;if(high>0)high*=1.16;
 const width=Math.max(360,rows.length*62+85),left=72,right=18,top=32,bottom=238;
 const y=v=>top+(high-v)/(high-low)*(bottom-top),zero=y(0),slot=(width-left-right)/rows.length;
 const guides=Array.from({length:5},(_,i)=>{
  const value=low+(high-low)*i/4;
  return `<line x1="${left}" x2="${width-right}" y1="${y(value)}" y2="${y(value)}" class="chart-gridline"/><text x="${left-10}" y="${y(value)+4}" text-anchor="end" class="chart-axis">${compact(value)}</text>`;
 }).join('');
 const bars=rows.map((r,i)=>{
  const value=values[i],center=left+slot*(i+.5),barWidth=Math.min(48,slot*.64),valueY=y(value);
  const exact=`${r.name}: ${money(value)}${unit?' '+unit:''}`;
  return `<g class="chart-mark" data-chart-team="${r.team_id}" role="img" aria-label="${esc(exact)}"><title>${esc(exact)}</title><rect x="${center-barWidth/2}" y="${Math.min(zero,valueY)}" width="${barWidth}" height="${Math.abs(valueY-zero)}" rx="3" fill="${dashboardColor(r.team_id)}"/>${value===0?`<circle cx="${center}" cy="${zero}" r="3" fill="${dashboardColor(r.team_id)}"/>`:''}<text x="${center}" y="${valueY+(value<0?16:-8)}" text-anchor="middle" class="bar-value">${compact(value)}</text><text x="${center}" y="270" text-anchor="middle" class="chart-axis">${esc(r.name)}</text></g>`;
 }).join('');
 return `<div class="chart-scroll"><svg class="comparison-chart" style="min-width:${width}px" viewBox="0 0 ${width} 288" role="img" aria-label="${esc(label)} by team${unit?' ('+unit+')':''}">${guides}<line x1="${left}" x2="${width-right}" y1="${zero}" y2="${zero}" class="chart-zero"/>${bars}</svg></div>`;
}

function instructorDashboard(){
 if(!teacher())return '<section class="card empty"><h2>Instructor access required</h2></section>';
 const history=game.history;
 if(!history.length)return `<div class="page-title"><div><div class="eyebrow">All teams at a glance</div><h1>Instructor Dashboard</h1><p>${esc(game.name)}</p></div></div><section class="card empty"><h2>Calculate a round to see team performance</h2><p class="muted">Weighted surplus, market share, policy, profit, and asset charts appear after you lock decisions and calculate results. You can review them before publishing.</p><button class="primary" data-nav="overview">Go to classroom overview</button></section>`;
 const h=history.find(x=>x.period===periodView)||history.at(-1),rows=h.results.slice().sort((a,b)=>a.team_id-b.team_id);
 const sum=key=>rows.reduce((n,r)=>n+(['assets','surplus'].includes(key)?r.next_state[key]:r[key]),0);
 return `<div class="page-title"><div><div class="eyebrow">All teams at a glance</div><h1>Instructor Dashboard</h1><p>${esc(game.name)} · Round ${h.period} of ${totalRounds()} · ${h.published?'Published results':'Instructor preview · unpublished'}</p></div><div class="flex wrap"><div class="report-select"><select id="dashboard-period" aria-label="Dashboard round">${history.map(x=>`<option value="${x.period}" ${x.period===h.period?'selected':''}>Round ${x.period}${x.published?'':' · Preview'}</option>`).join('')}</select></div><button id="print">Print</button></div></div>
 <div class="metricrow">${metric('Weighted surplus leader',esc(rows.slice().sort((a,b)=>a.overall_rank-b.overall_rank)[0].name),'Highest cumulative weighted surplus',true)}${metric('Policies written',compact(sum('policies')),'Gross policies issued this round')}${metric('Total profit',compact(sum('income')),'After-tax underwriting + investment')}${metric('Closing surplus',compact(sum('surplus')),'Combined net capital at round end')}</div>
 <div class="dashboard-tools"><p class="caption">Select a team in the pie legend to highlight it across all charts. Hover over a bar or slice for its value.</p><button class="quiet small" id="clear-highlight" hidden>Show all teams</button></div><div id="dashboard-selection" class="dashboard-selection" role="status" hidden></div>
 <div class="grid2 dashboard-grid"><section class="card dashboard-score"><div class="chart-heading"><div><h2>Cumulative weighted surplus</h2><p class="caption">The ranking objective · Sum of closing surplus × round weight</p></div>${tag('SCORE','blue')}</div>${comparisonBars(rows,'cumulative','Cumulative weighted surplus','CU')}</section><section class="card"><div class="chart-heading"><div><h2>Market share</h2><p class="caption">Share of total market premium · %</p></div>${tag('ROUND '+h.period,'blue')}</div>${marketSharePie(rows)}</section>
 <section class="card"><div class="chart-heading"><div><h2>Policies written</h2><p class="caption">Gross policies issued during the selected round</p></div>${tag('POLICIES','gray')}</div>${comparisonBars(rows,'policies','Policies written','policies')}</section>
 <section class="card"><div class="chart-heading"><div><h2>Profit / loss</h2><p class="caption">After-tax underwriting profit + investment income</p></div>${tag('CU','gray')}</div>${comparisonBars(rows,'income','Profit / loss','CU')}<p class="chart-footnote">Losses appear below the zero line. This is the selected round's income, not cumulative profit.</p></section>
 <section class="card"><div class="chart-heading"><div><h2>Total assets</h2><p class="caption">Closing cash + bonds + stocks</p></div>${tag('CU','gray')}</div>${comparisonBars(rows,'assets','Total assets','CU')}<p class="chart-footnote">Each chart uses its own scale. Team colors are consistent across all four charts.</p></section></div>
 <section class="card flush dashboard-table"><div class="cardhead"><h2>Team performance · Round ${h.period}</h2><p class="caption">Exact values rounded to whole currency units or policies. Open a report for the full financial breakdown.</p></div><div class="table-scroll"><table><thead><tr><th>Team</th><th class="num">Market share</th><th class="num">Policies written</th><th class="num">Profit / loss (CU)</th><th class="num">Assets (CU)</th><th class="num">Surplus (CU)</th><th class="num">Weighted surplus (CU)</th><th class="num">Overall rank</th><th></th></tr></thead><tbody>${rows.map(r=>`<tr data-chart-team="${r.team_id}"><td><span class="teamname"><i class="teamdot" style="background:${dashboardColor(r.team_id)}"></i>${esc(r.name)}</span></td><td class="num">${pct(r.share)}</td><td class="num">${money(r.policies)}</td><td class="num ${r.income<0?'negative':'positive'}">${money(r.income)}</td><td class="num">${money(r.next_state.assets)}</td><td class="num">${money(r.next_state.surplus)}</td><td class="num"><b>${money(r.cumulative)}</b></td><td class="num">#${r.overall_rank}</td><td><button class="quiet small" data-inspect-team="${r.team_id}" data-inspect-period="${h.period}">View report</button></td></tr>`).join('')}</tbody></table></div></section>`;
}

function bindDashboard(){
 if(!teacher()||view!=='dashboard')return;
 const control=$('#dashboard-period');
 if(!control)return;
 control.onchange=e=>{periodView=Number(e.target.value);render();};
 let highlighted=null;
 const select=id=>{
  highlighted=highlighted===id?null:id;
  document.querySelectorAll('[data-chart-team]').forEach(el=>el.classList.toggle('chart-muted',highlighted!==null&&Number(el.dataset.chartTeam)!==highlighted));
  document.querySelectorAll('[data-compare-team]').forEach(el=>el.setAttribute('aria-pressed',String(Number(el.dataset.compareTeam)===highlighted)));
  $('#clear-highlight').hidden=highlighted===null;
  const info=$('#dashboard-selection');info.hidden=highlighted===null;
  if(highlighted!==null){const h=game.history.find(x=>x.period===Number(control.value)),r=h.results.find(x=>x.team_id===highlighted);info.textContent=`${r.name} · Market share ${pct(r.share)} · Policies ${money(r.policies)} · Profit / loss ${money(r.income)} CU · Surplus ${money(r.next_state.surplus)} CU · Weighted surplus ${money(r.cumulative)} CU`;}
 };
 document.querySelectorAll('[data-compare-team]').forEach(b=>b.onclick=()=>select(Number(b.dataset.compareTeam)));
 $('#clear-highlight').onclick=()=>select(null);
 document.querySelectorAll('[data-inspect-team]').forEach(b=>b.onclick=()=>{teamId=Number(b.dataset.inspectTeam);periodView=Number(b.dataset.inspectPeriod);view='results';render();});
}
