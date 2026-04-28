from __future__ import annotations

import time

import schedule
from dotenv import load_dotenv

from ai_news_agent.config import load_config
from ai_news_agent.pipeline import DailyNewsPipeline


def main() -> None:
    load_dotenv()
    config = load_config()
    schedule_time = config.get("schedule", {}).get("daily_time", "09:00")

    def job() -> None:
        pipeline = DailyNewsPipeline(load_config())
        pipeline.run()

    schedule.every().day.at(schedule_time).do(job)
    print(f"定时任务已启动，每天 {schedule_time} 执行一次。")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
