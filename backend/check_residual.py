import sqlite3
conn = sqlite3.connect('D:/Neurones-IA/data/local_db/neurones.db')
cur = conn.cursor()

cur.execute("SELECT COUNT(*) total, COUNT(CASE WHEN amount_residual > 0 THEN 1 END) avec_residual, ROUND(SUM(amount_residual)/1e9,3) total_Mds FROM invoices")
row = cur.fetchone()
print(f"Factures total: {row[0]}, avec amount_residual > 0: {row[1]}, total residuel: {row[2]} Mds XOF")

cur.execute("""
SELECT c.name client, ROUND(SUM(i.amount_residual)/1e6,1) M_restant, COUNT(*) n,
       MAX(CAST(julianday('now')-julianday(i.due_date) AS INTEGER)) retard_max
FROM invoices i JOIN clients c ON i.client_id=c.client_id
WHERE i.status='pending' AND julianday('now')-julianday(i.due_date)>90
GROUP BY c.name ORDER BY SUM(i.amount_residual) DESC LIMIT 10
""")
print("\nTop 10 impayes >90j (amount_residual):")
for r in cur.fetchall():
    print(f"  {r}")

cur.execute("SELECT ROUND(SUM(amount_residual)/1e9,3) FROM invoices WHERE status='pending' AND julianday('now')-julianday(due_date)>90")
print(f"\nTotal impayes >90j: {cur.fetchone()[0]} Mds XOF")

# Comparer avec amount (avant fix)
cur.execute("SELECT ROUND(SUM(amount)/1e9,3) FROM invoices WHERE status='pending' AND julianday('now')-julianday(due_date)>90")
print(f"Total impayes >90j (amount brut): {cur.fetchone()[0]} Mds XOF")

conn.close()
