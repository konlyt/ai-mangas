import pymysql

# 连接数据库
conn = pymysql.connect(
    host="localhost",
    user="root",
    password="123456",
    database="AnimeWorld",
    charset="utf8mb4",
)

cursor = conn.cursor()

# 先看看 storyboard_id=47 的视频任务有哪些
cursor.execute("SELECT id, status, result_url FROM tasks WHERE storyboard_id = 47 AND type = 'video' ORDER BY id DESC")
tasks = cursor.fetchall()
print("视频任务列表:")
for t in tasks:
    print(f"  task_id={t[0]}, status={t[1]}, result_url={t[2]}")

# 更新最新的那个任务
if tasks:
    task_id = tasks[0][0]
    new_url = "/static/videos/minimax_test.mp4"
    cursor.execute("UPDATE tasks SET status = 'DONE', result_url = %s WHERE id = %s", (new_url, task_id))
    conn.commit()
    print(f"\nUpdated task {task_id} to DONE with url: {new_url}")
    print(f"Rows affected: {cursor.rowcount}")

cursor.close()
conn.close()
