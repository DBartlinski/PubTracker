import pandas as pd, io, re

vamc_display = 'VA Central Office; United States Department of Veterans Affairs; Veterans Health Administration'

def get_search_terms(vamc_display):
    parts = str(vamc_display).split(';')
    terms = []
    for part in parts:
        cleaned = part.strip()
        cleaned = re.sub(r'\s*\(Not in VA Dimensions\)\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+\([^()]+\)\s*$', '', cleaned).strip()
        if cleaned:
            terms.append(cleaned)
    return terms

terms = get_search_terms(vamc_display)
print('Search terms for station 101:')
for t in terms:
    print(f'  - "{t}"')

with open('Dimensions-for-Veterans-Affairs-Publication-2026-06-11_19-02-02.csv', 'r', encoding='utf-8-sig', errors='replace') as f:
    lines = f.readlines()
header_idx = next(i for i, l in enumerate(lines[:20]) if 'Rank' in l and 'Publication ID' in l)
df = pd.read_csv(io.StringIO(''.join(lines[header_idx:])))

org_col = next(c for c in df.columns if 'research organizations' in c.lower() and 'standardized' in c.lower())

matches = 0
matched_examples = []
terms_lower = [t.lower() for t in terms]

for _, row in df.iterrows():
    orgs_raw = str(row[org_col] or '')
    orgs = [o.strip().lower() for o in orgs_raw.split(';') if o.strip()]
    for term in terms_lower:
        if any(term in org or org in term for org in orgs):
            matches += 1
            if len(matched_examples) < 3:
                matched_examples.append(orgs_raw[:120])
            break

print(f'\nMatches found in current Dimensions file: {matches}')
print('\nExample matched orgs:')
for ex in matched_examples:
    print(f'  {ex}')

print('\nAll orgs containing "veterans affairs" or "central office":')
all_orgs = set()
for orgs_raw in df[org_col].dropna():
    for org in orgs_raw.split(';'):
        o = org.strip()
        if 'veterans affairs' in o.lower() or 'central office' in o.lower():
            all_orgs.add(o)
for o in sorted(all_orgs):
    print(f'  - {o}')
