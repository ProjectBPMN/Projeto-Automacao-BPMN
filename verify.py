import json
from collections import Counter
data = [json.loads(l) for l in open(r'avaliacao/datasets/desenvolvimento_local_v2.jsonl', encoding='utf-8').readlines() if l.strip()]
print(f'Total: {len(data)}')
print(f'Dimensions: {dict(Counter(r["dimension"] for r in data))}')
if 'CLASSIFICACAO' in [r['dimension'] for r in data]:
    print(f'Classification classes: {dict(Counter(r["expected_classification"] for r in data if r["dimension"]=="CLASSIFICACAO"))}')
    cores = len(set(r['narrative_core_sha256'] for r in data if r['dimension']=="CLASSIFICACAO"))
    print(f'Unique classification cores: {cores}')
