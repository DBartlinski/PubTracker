import sqlite3
import csv

def export_clean_authority_csv(db_path, output_path):
    """Export facility names and aliases in a clean, simple format for Excel."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    
    query = '''
    SELECT 
        f.canonical_name,
        fn.name as alias,
        fn.name_kind
    FROM facility f
    JOIN facility_name fn ON f.id = fn.facility_id
    ORDER BY f.canonical_name, fn.name_kind DESC, fn.name
    '''
    
    rows = con.execute(query).fetchall()
    con.close()
    
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['Facility', 'Alias', 'Type'])
        for row in rows:
            writer.writerow([
                row['canonical_name'],
                row['alias'],
                row['name_kind']
            ])

export_clean_authority_csv('data/facility_authority.db', 'output/facility_names_clean.csv')
print("✓ Created: output/facility_names_clean.csv")
