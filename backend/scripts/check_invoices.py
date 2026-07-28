import sqlite3
conn = sqlite3.connect("D:/Neurones-IA/data/local_db/neurones.db")
cur = conn.cursor()

# Structure réelle
cur.execute("PRAGMA table_info(invoices)")
cols = [r[1] for r in cur.fetchall()]
print("Colonnes invoices:", cols)

# Jointure avec clients pour trouver MTN CI
cur.execute("""
    SELECT i.invoice_id, i.amount, i.currency, i.due_date, i.status, i.synced_at, c.name
    FROM invoices i
    JOIN clients c ON c.client_id = i.client_id
    WHERE c.name LIKE '%MTN%'
    LIMIT 5
""")
rows = cur.fetchall()
print(f"\nExemples factures MTN:")
for r in rows:
    print(r)

# Vérifier les champs disponibles
cur.execute("""
    SELECT COUNT(*), MIN(i.due_date), MAX(i.due_date)
    FROM invoices i
    JOIN clients c ON c.client_id = i.client_id
    WHERE c.name LIKE '%MTN%'
""")
r = cur.fetchone()
print(f"\nTotal: {r[0]}, due_date de {r[1]} à {r[2]}")

conn.close()
