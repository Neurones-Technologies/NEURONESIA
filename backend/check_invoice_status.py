import sqlite3
conn = sqlite3.connect('D:/Neurones-IA/data/local_db/neurones.db')
cur = conn.cursor()
cur.execute("SELECT status, COUNT(*) n, ROUND(SUM(amount)/1e9,3) amt FROM invoices GROUP BY status ORDER BY n DESC")
print("Statuts invoices:")
for row in cur.fetchall(): print(" ", row)

cur.execute("SELECT COUNT(*), ROUND(SUM(amount)/1e9,3) FROM invoices WHERE status IN ('pending','overdue') AND julianday('now')-julianday(due_date)>90")
print("Impayés >90j (pending+overdue):", cur.fetchone())

cur.execute("SELECT COUNT(*), ROUND(SUM(amount)/1e9,3) FROM invoices WHERE status='unpaid' AND julianday('now')-julianday(due_date)>90")
print("Impayés >90j (unpaid):", cur.fetchone())

# Vérifier si on a amount_residual
cur.execute("PRAGMA table_info(invoices)")
cols = [r[1] for r in cur.fetchall()]
print("\nColonnes invoices:", cols)
conn.close()
