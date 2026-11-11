"""Optional instructor debrief. Only an allowlisted numeric summary leaves the server."""
import json
import os
import urllib.request


def round_facts(record):
    rows = record['results']
    def span(values):
        nums = [round(x, 3) for x in values if isinstance(x, (int, float))]
        return [min(nums), max(nums)] if nums else None
    return dict(
        round=record['period'], teams=len(rows), currency="CU",
        premium_share_pct_range=span(100*r['share'] for r in rows),
        low_premium_range=span(r.get('regions', {}).get('low', {}).get('premium') for r in rows),
        high_premium_range=span(r.get('regions', {}).get('high', {}).get('premium') for r in rows),
        total_policies=round(sum(r['policies'] for r in rows), 2),
        investment_income_range=span(r['bond_income']+r['stock_income'] for r in rows),
        total_investment_income=round(sum(r['bond_income']+r['stock_income'] for r in rows), 2),
        closing_surplus_range=span(r['next_state']['surplus'] for r in rows),
        total_profit=round(sum(r['income'] for r in rows), 2),
        random_catastrophe_percentage_points=record.get('catastrophe_event_pp', 0))


def generate_commentary(record):
    key = os.environ.get('OPENAI_API_KEY')
    model = os.environ.get('OPENAI_MODEL')
    if not key or not model:
        raise ValueError('AI commentary is not configured. Set OPENAI_API_KEY and OPENAI_MODEL on the server. The statistical summary is available.')
    body = dict(model=model, store=False, max_output_tokens=800,
                instructions="Write a short English classroom debrief (2-3 sentences, under 75 words) about this simulated insurance market. Use only the supplied numbers. Compare pricing, market shares, investment income or capital where informative. Do not infer causes, trends or winners from ranges. Omit missing values. A catastrophe increment is in percentage points.",
                input=json.dumps(round_facts(record), allow_nan=False))
    request = urllib.request.Request('https://api.openai.com/v1/responses', data=json.dumps(body).encode(),
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            result = json.load(response)
        text = ' '.join(c['text'].strip() for item in result.get('output', []) if item.get('type')=='message'
                        for c in item.get('content', []) if c.get('type')=='output_text').strip()
        if result.get('status')!='completed' or not text: raise ValueError()
    except (ValueError, OSError, TypeError, KeyError) as exc:
        raise ValueError('AI commentary is unavailable. Check the server model, API key and billing, or try later. The round results are unchanged.') from exc
    return text
