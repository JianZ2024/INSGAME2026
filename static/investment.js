'use strict';
const stockMultipliers = [.8, 1, 1.2, 1.4, 2];

function investmentUpdateNotice(){
 return game?.investment_updated_period===game?.period && game?.phase==='open'
  ? '<div class="notice warn investment-update">Investment rules have changed. Existing entries are saved. Review the bond and stock strategies, keep cash at or above 10%, and submit again.</div>' : '';
}

function bondThresholdText(count){
 const maximum = Math.ceil(count * .3) - 1;
 return maximum===0 ? `With ${count} teams, any team choosing Strategy 2 receives 2%.`
  : `With ${count} teams: ${maximum===1?'1 team':`up to ${maximum} teams`} choosing Strategy 2 earns 8%; ${maximum+1} or more earns 2%.`;
}

function investmentControls(d,disabled){
 const base=game.env.stock_return, off=disabled?'disabled':'';
 return `<section class="card investment-card"><div class="eyebrow">04 / Investment</div><h2>Asset allocation &amp; strategies</h2>
 <div class="formgrid">${field('cash_pct','Cash (%)',d.cash_pct*100,{min:10,max:100,disabled,help:'Regulatory minimum: 10% of the opening asset allocation.'})}${field('bond_pct','Bonds (%)',d.bond_pct*100,{min:0,max:100,disabled})}${field('stock_pct','Stocks (%)',d.stock_pct*100,{min:0,max:100,disabled})}</div>
 <div id="allocation-preview"></div><p id="allocation-status" class="caption" role="status"></p>
 <div class="investment-strategies"><fieldset class="investment-options"><legend>Bond strategy</legend>
 <label class="investment-choice"><input type="radio" name="bond_strategy" value="1" ${d.bond_strategy===1?'checked':''} ${off} required><span><b>Strategy 1 · Fixed</b><small>Annual return</small></span><strong>4%</strong></label>
 <label class="investment-choice"><input type="radio" name="bond_strategy" value="2" ${d.bond_strategy===2?'checked':''} ${off} required><span><b>Strategy 2 · Participation-based</b><small>8% if fewer than 30% of all teams select it; otherwise 2%.</small></span><strong>8% / 2%</strong></label>
 <p class="caption">${bondThresholdText(game.teams.length)} Counts all teams selecting this strategy, even with 0% in bonds. Determined when the round is calculated.</p></fieldset>
 <fieldset class="investment-options"><legend>Stock strategy</legend>
 <p class="caption">Instructor-set base annual stock return for this round: <b>${pct(base)}</b>. Choose one multiplier:</p>
 ${stockMultipliers.map((m,i)=>`<label class="investment-choice"><input type="radio" name="stock_strategy" value="${i+1}" ${d.stock_strategy===i+1?'checked':''} ${off} required><span><b>Strategy ${i+1} · ${Math.round(m*100)}% of base</b><small>${pct(base)} × ${m.toFixed(1)}</small></span><strong>${pct(base*m)}</strong></label>`).join('')}
 </fieldset></div><p class="caption investment-footnote">Rates are annual, before investment tax; each round represents one year. Bond income retains 85% and stock income 66% after tax. Rebalancing fee: 0.5% of securities traded.</p></section>`;
}

function updateInvestmentPreview(form){
 const value=k=>Number(form.elements[k].value);
 const validTotal=Math.abs(value('cash_pct')+value('bond_pct')+value('stock_pct')-100)<=1e-6;
 const validCash=value('cash_pct')>=10;
 const status=$('#allocation-status');
 status.textContent=!validCash?'Cash must be at least 10%.':!validTotal?'Cash, bonds, and stocks must total 100%.':'Allocation meets the 10% cash minimum and totals 100%.';
 status.className='caption '+(validCash&&validTotal?'positive':'negative');
 form.elements.cash_pct.setCustomValidity(validCash?'':'Cash allocation must be at least 10%.');
 form.elements.stock_pct.setCustomValidity(validTotal?'':'Cash, bonds, and stocks must total 100%.');
 $('#bond-strategy-preview').textContent=value('bond_strategy')===1?'Strategy 1 · 4.0% fixed':'Strategy 2 · 8.0% or 2.0%';
 const m=stockMultipliers[value('stock_strategy')-1];
 $('#stock-strategy-preview').textContent=`${Math.round(m*100)}% of base · ${pct(game.env.stock_return*m)}`;
}

function investmentReport(r,h){
 if(r.bond_strategy===undefined) return `<section class="card"><h2>Investment returns</h2><p class="caption">Historical round · original investment rules</p>${line('Bond return',pct(h.env.bond_return))}${line('Stock return',pct(h.env.stock_return))}<p class="caption">This completed round retains its original rates and financial results.</p></section>`;
 return `<section class="card"><h2>Investment strategies &amp; returns</h2>${line('Bond strategy',r.bond_strategy===1?'1 · Fixed':'2 · Participation-based')}${line('Annual bond return',pct(r.bond_return))}${line('Teams choosing bond strategy 2',r.bond_strategy_2_count+' / '+r.team_count)}${line('Stock strategy',r.stock_strategy+' · '+Math.round(r.stock_multiplier*100)+'% of base')}${line('Base annual stock return',pct(r.stock_base_return))}${line('Annual stock return',pct(r.stock_return))}<p class="caption">Rates shown are before tax. Investment income in the financial report is after tax.</p></section>`;
}

function investmentRules(){
 const base=game?.env?.stock_return;
 const rateText=Number.isFinite(base)?`For this round the instructor set a base of ${pct(base)}. The five annual rates are ${stockMultipliers.map(m=>pct(base*m)).join(', ')}.`:'For example, at an instructor-set base of 8%, the five annual rates are 6.4%, 8%, 9.6%, 11.2% and 16%.';
 return `<section class="card"><h2>Investment strategies and cash requirement</h2><p>Each round represents one year. Cash must be at least 10% of the opening allocation; cash, bonds, and stocks must total 100%. Later trading costs and operating cash flows can reduce the closing cash ratio.</p><p><b>Bonds:</b> Strategy 1 returns 4%. Strategy 2 returns 8% only if fewer than 30% of all teams select it; at 30% or above it returns 2%. Selection counts even with zero bond allocation.</p><p><b>Stocks:</b> Strategies 1–5 apply 80%, 100%, 120%, 140%, or 200% of the instructor's base annual stock return. ${rateText} These are multipliers, not standalone annual returns. A negative base also has its loss multiplied.</p><p>Rates are before tax. Bond income retains 85% and stock income 66%. Rebalancing costs 0.5% of securities traded.</p></section>`;
}
