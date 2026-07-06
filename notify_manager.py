# notify_manager.py
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import MessageChain


class NotifyManager:
    """
    番剧开播提醒管理器。
    读取日程文件，结合提前通知配置，在准确的时间点向所有已订阅会话推送消息。
    """

    def __init__(self, context, config: AstrBotConfig, plugin_data_path: Path):
        """
        :param context: AstrBot 上下文，用于发送消息
        :param config:   插件配置对象
        :param plugin_data_path: 插件数据目录（存储 schedule 和 notify_list）
        """
        self.context = context
        self.config = config
        self.plugin_data_path = plugin_data_path

        # 当前日程数据
        self._schedule: list[dict] = []
        self._next_index = 0                # 下一个待提醒的节目索引

        # 通知目标列表（unified_msg_origin 字符串）
        self._notify_targets: list[str] = []

        # 配置项
        self._advance_minutes = self.config.get("notify_advance_minutes", 0)
        self._template = self.config.get(
            "notify_template",
            "📣番剧开播提醒：\n"
            "《{title}》#{episodeDisplay}\n"
            "在{platform}开播了！\n"
            "开播时间：{eventAt}\n"
            "bgmId：{bgmId}",
        )

        self._running = False

    # ------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------
    async def _load_notify_targets(self):
        """从 notify_list.json 加载所有订阅目标"""
        file_path = self.plugin_data_path / "notify_list.json"
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                self._notify_targets = json.load(f)
        else:
            self._notify_targets = []
        logger.info(f"NotifyManager: 已加载 {len(self._notify_targets)} 个通知目标")

    async def _load_schedule(self):
        """
        加载当前日期的番剧日程。
        日期计算遵循日本时间，凌晨4点前视为前一天。
        """
        jst = timezone(timedelta(hours=9))
        now_jst = datetime.now(jst)
        base_date = now_jst - timedelta(days=1) if now_jst.hour < 4 else now_jst
        date_str = base_date.strftime("%Y%m%d")

        schedule_file = self.plugin_data_path / f"{date_str}_schedule.json"
        if schedule_file.exists():
            with open(schedule_file, "r", encoding="utf-8") as f:
                self._schedule = json.load(f)
        else:
            self._schedule = []

        logger.info(f"NotifyManager: 加载日程文件 {date_str}_schedule.json，共 {len(self._schedule)} 条")
        self._find_next_index()

    def _find_next_index(self):
        """
        根据当前 UTC 时间戳，结合提前分钟数，找到第一个尚未提醒的节目索引。
        schedule 已按时间升序排列。
        """
        now_ts = time.time() * 1000  # 毫秒
        idx = 0
        for item in self._schedule:
            remind_ts = item["eventTsMs"] - self._advance_minutes * 60000
            if remind_ts > now_ts:
                # 这一项的提醒时间还在未来，从这里开始
                break
            idx += 1
        self._next_index = idx
        logger.info(f"NotifyManager: 下一个提醒索引 = {self._next_index} / {len(self._schedule)}")

    # ------------------------------------------------------------
    # 消息构造与发送
    # ------------------------------------------------------------
    def _format_message(self, item: dict) -> str:
        """使用用户配置的模板格式化一条提醒消息"""
        try:
            return self._template.format(**item)
        except KeyError as e:
            logger.error(f"NotifyManager: 模板变量缺失 {e}，使用降级消息")
            return (
                f"番剧开播提醒：{item.get('title', '未知')} "
                f"第{item.get('episodeDisplay', '?')}集 "
                f"在{item.get('platform', '未知')}开播"
            )

    async def _send_notification(self, item: dict):
        """向所有通知目标发送一条提醒消息"""
        if not self._notify_targets:
            return

        text = self._format_message(item)
        chain = MessageChain().message(text)

        for target in self._notify_targets:
            try:
                await self.context.send_message(target, chain)
                logger.info(f"NotifyManager: 已向 {target} 发送提醒《{item.get('title')}》")
            except Exception as e:
                logger.error(f"NotifyManager: 向 {target} 发送失败: {e}")

    # ------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------
    async def run(self):
        """
        启动提醒循环。
        会持续检查日程，并在精确时间发送提醒，直到调用 stop()。
        """
        self._running = True

        # 加载目标
        await self._load_notify_targets()
        if not self._notify_targets:
            logger.warning("NotifyManager: 通知目标为空，不启动提醒循环")
            self._running = False
            return

        while self._running:
            # 加载当日日程
            await self._load_schedule()

            if not self._schedule:
                logger.info("NotifyManager: 当前无番剧日程，30 分钟后重试")
                await asyncio.sleep(1800)
                continue

            # 逐条发送
            while self._next_index < len(self._schedule):
                if not self._running:
                    return

                item = self._schedule[self._next_index]
                remind_ts = item["eventTsMs"] - self._advance_minutes * 60000
                now_ts = time.time() * 1000
                wait_seconds = (remind_ts - now_ts) / 1000

                if wait_seconds > 0:
                    logger.info(
                        f"NotifyManager: 将在 {wait_seconds:.0f} 秒后提醒《{item.get('title')}》"
                    )
                    # 分段睡眠以便快速响应停止信号
                    while wait_seconds > 0 and self._running:
                        sleep_interval = min(wait_seconds, 60)
                        await asyncio.sleep(sleep_interval)
                        wait_seconds -= sleep_interval
                    if not self._running:
                        return

                # 到时间后再次确认（避免因系统时间调整错过）
                now_ts = time.time() * 1000
                if now_ts >= remind_ts:
                    await self._send_notification(item)
                    self._next_index += 1
                else:
                    # 极少情况：系统时间被回调，重新计算等待
                    continue

            # 本日所有节目均已提醒，等待一段时间后重新加载（可能会跨天）
            logger.info("NotifyManager: 今日所有提醒已发送，5 分钟后重新检查日程")
            await asyncio.sleep(300)

    async def stop(self):
        """优雅停止提醒循环"""
        self._running = False
        logger.info("NotifyManager: 提醒循环已停止")