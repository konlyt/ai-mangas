import pymysql

conn = pymysql.connect(
    host="localhost",
    user="root",
    password="123456",
    database="AnimeWorld",
    charset="utf8mb4",
)

cursor = conn.cursor()
cursor.execute("SELECT id, provider, model_name, capability, user_id, project_id FROM model_configs ORDER BY id")
rows = cursor.fetchall()

print("model_configs 表中的配置:")
print(f"{'ID':<5} {'provider':<15} {'model_name':<25} {'capability':<15} {'user_id':<8} {'project_id':<10}")
print("-" * 80)
for r in rows:
    print(f"{r[0]:<5} {r[1]:<15} {r[2]:<25} {r[3]:<15} {str(r[4]):<8} {str(r[5]):<10}")

cursor.close()
conn.close()
