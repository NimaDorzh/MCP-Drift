"""Validate Claude Sonnet 4.6 trace verdicts against claimed benchmark results."""
import json
import os
import glob
from collections import defaultdict

traces_dir = os.path.join(os.path.dirname(__file__), '..', 'traces')
pattern = os.path.join(traces_dir, 'anthropic_claude-sonnet-4-6_*_no_defense_202606*.json')
files = sorted(glob.glob(pattern))
print(f'Total files: {len(files)}')

by_scenario = defaultdict(list)
for fp in files:
    with open(fp) as f:
        data = json.load(f)
    scenario = data['meta']['scenario_id']
    verdict = data['verdict']
    compromised = verdict['compromised']
    cturn = verdict['compromise_turn']
    seed = data['run_metadata'].get('seed', '?')
    # Also check per-turn malicious_call_detected for cross-validation
    detected_turns = [t['turn'] for t in data['turns'] if t.get('malicious_call_detected')]
    by_scenario[scenario].append({
        'file': os.path.basename(fp),
        'compromised': compromised,
        'compromise_turn': cturn,
        'seed': seed,
        'detected_turns': detected_turns,
    })

total_compromised = 0
total_runs = 0
print()
print(f"{'Scenario':<30} {'N':>3}  {'Comp':>6}  {'ASR':>6}  Per-run details")
print('-' * 100)
for scenario in sorted(by_scenario):
    runs = by_scenario[scenario]
    comp = sum(1 for r in runs if r['compromised'])
    n = len(runs)
    asr = comp / n * 100 if n else 0
    details = []
    for r in runs:
        ct = r['compromise_turn']
        dt = r['detected_turns']
        if r['compromised']:
            details.append(f"COMP@T{ct}(det:{dt})")
        else:
            details.append(f"clean(det:{dt})")
    total_compromised += comp
    total_runs += n
    print(f"{scenario:<30} {n:>3}  {comp}/{n:<4}  {asr:>5.0f}%  {', '.join(details)}")

print()
print(f"TOTAL: {total_compromised}/{total_runs} COMPROMISED, overall ASR = {total_compromised/total_runs*100:.1f}%")
