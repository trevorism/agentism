import sqlite3
c = sqlite3.connect("memory.db")
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print(tables)
c.close()

