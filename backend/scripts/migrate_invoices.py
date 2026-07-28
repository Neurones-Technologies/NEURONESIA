"""Ajoute invoice_date et invoice_name à la table invoices."""
import sqlite3

conn = sqlite3.connect("D:/Neurones-IA/data/local_db/neurones.db")
cur = conn.cursor()

cur.execute("PRAGMA table_info(invoices)")
existing = [r[1] for r in cur.fetchall()]
print("Colonnes actuelles:", existing)

for col, typ in [("invoice_date", "DATETIME"), ("invoice_name", "VARCHAR(100)"), ("payment_date", "DATETIME")]:
    if col not in existing:
        cur.execute(f"ALTER TABLE invoices ADD COLUMN {col} {typ}")
        print(f"Colonne '{col}' ajoutée.")
    else:
        print(f"Colonne '{col}' déjà présente.")

conn.commit()
conn.close()
print("Migration OK.")
