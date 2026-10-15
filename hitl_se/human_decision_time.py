"""Calculate per-person HITL checkpoint decision latency from an engine audit export.

Usage:
    python human_decision_time.py demo_output/audit.json
    python human_decision_time.py demo_output/audit.json --out decision_times.csv
"""
import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def parse_timestamp(value):
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError(f'Timestamp lacks timezone: {value}')
    return timestamp.astimezone(timezone.utc)


def calculate(audit):
    gates = {gate['id']: gate for gate in audit['gates']}
    decisions_by_gate = defaultdict(list)
    for decision in audit['decisions']:
        decisions_by_gate[decision['gate_id']].append(decision)

    rows = []
    for gate_id, decisions in decisions_by_gate.items():
        gate = gates.get(gate_id)
        if gate is None:
            continue
        opened = parse_timestamp(gate['created'])
        # 'info' requests do not close the gate. A subsequent decision may do so.
        for decision in sorted(decisions, key=lambda d: parse_timestamp(d['created'])):
            if decision['action'] == 'info':
                continue
            submitted = parse_timestamp(decision['created'])
            seconds = (submitted - opened).total_seconds()
            if seconds < 0:
                raise ValueError(f'Decision timestamp precedes gate opening: {gate_id}')
            rows.append({
                'project': gate['project'],
                'gate_id': gate_id,
                'state': gate['state'],
                'actor': decision['actor'],
                'action': decision['action'],
                'gate_opened_utc': opened.isoformat(),
                'decision_submitted_utc': submitted.isoformat(),
                'latency_seconds': round(seconds, 3),
            })
    rows.sort(key=lambda r: (r['gate_opened_utc'], r['gate_id']))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audit', type=Path, help='Path to exported audit.json')
    parser.add_argument('--out', type=Path, default=Path('human_decision_times.csv'))
    args = parser.parse_args()
    audit = json.loads(args.audit.read_text(encoding='utf-8'))
    rows = calculate(audit)
    columns = ['project', 'gate_id', 'state', 'actor', 'action',
               'gate_opened_utc', 'decision_submitted_utc', 'latency_seconds']
    with args.out.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    by_actor = defaultdict(list)
    for row in rows:
        by_actor[row['actor']].append(row['latency_seconds'])
    print(f'Wrote {len(rows)} completed human decisions to {args.out}')
    print(f'{"Person":<24} {"Decisions":>10} {"Total (s)":>12} {"Average (s)":>13}')
    for actor, durations in sorted(by_actor.items()):
        print(f'{actor:<24} {len(durations):>10} {sum(durations):>12.3f} {sum(durations)/len(durations):>13.3f}')
    if rows:
        print(f'Overall elapsed checkpoint latency: {sum(r["latency_seconds"] for r in rows):.3f} s')


if __name__ == '__main__':
    main()
