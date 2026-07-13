from datetime import time
from time import sleep
from radar import now_cn

target = now_cn().replace(hour=9, minute=0, second=0, microsecond=0)
seconds = (target - now_cn()).total_seconds()
if 0 < seconds <= 15 * 60:
    print(f"距离北京时间 09:00 还有 {int(seconds)} 秒，等待后发送。")
    sleep(seconds)
