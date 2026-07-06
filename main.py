import asyncio, time
from datetime import datetime, timedelta, timezone
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from pathlib import Path
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from .notify_list_manager import NotifyListManager
from .anime_timetable_manager import AnimeTimetableManager
from .notify_manager import NotifyManager 

@register("anime_notify", "YourName", "一个简单的番剧放送开播提醒插件", "1.0.0")
class AnimeNotifyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        # 用于获取插件用户配置
        self.config = config

        # 本地存储插件数据的文件夹
        self.plugin_data_path = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        self.plugin_data_path.mkdir(parents=True, exist_ok=True)

        # 初始化 NotifyListManager 并传入路径
        self.notify_list_manager = NotifyListManager(self.plugin_data_path)

        # 从配置中获取 api_token (假设配置项里叫 bgm_api_token，若没有则传空字符串)
        self.__api_token = self.config.get("bgm_api_token", "")
        # 初始化 TimetableManager
        self.timetable_manager = AnimeTimetableManager(self.plugin_data_path, self.__api_token)

        #初始化 NotifyManager
        self.notify_manager = NotifyManager(self.context, self.config, self.plugin_data_path)

        # 用于控制后台守护任务生存周期的标志位
        self.__running = False
        # 记录上一次清理过时缓存的时间戳（初始为 0 确保首次运行会触发清理）
        self.__last_cleanup_time = 0

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

        self.__running = True

        # 启动后台守护协程，负责长效定时检查更新
        asyncio.create_task(self.__timetable_update_loop())
        logger.info("番剧时间表自动更新任务已启动。")

        # 启动后台协程，清理过时缓存
        asyncio.create_task(self.__timetable_clear_cache_loop())
        logger.info("番剧时间表缓存清理任务已启动。")

        asyncio.create_task(self.notify_manager.run())
        logger.info("番剧开播提醒发送任务已启动。")

    async def __timetable_clear_cache_loop(self):
        while self.__running:
            current_timestamp = time.time()
            # 定时清理逻辑：每 12 小时 (43200 秒) 调用一次缓存清理
            if current_timestamp - self.__last_cleanup_time >= 43200:
                logger.info("[缓存清理进程] 开始检查并清理过时番剧缓存文件...")
                self.timetable_manager.clear_expired_cache()
                self.__last_cleanup_time = current_timestamp
            # 每隔 12 小时 (43200 秒) 自动检查一次
            await asyncio.sleep(43200)

    async def __timetable_update_loop(self):
        """后台守护任务：每 60 分钟检查一次是否需要执行更新"""
        while self.__running:
            try:
                # 条件 1：检查通知列表是否非空，若空则什么都不做
                if self.notify_list_manager.notify_list:
                    
                    # 计算当前时间窗口对应的应有文件名
                    jst_tz = timezone(timedelta(hours=9))
                    now_jst = datetime.now(jst_tz)
                    base_date = now_jst - timedelta(days=1) if now_jst.hour < 4 else now_jst
                    date_str = base_date.strftime("%Y%m%d")
                    timetable_file = self.plugin_data_path / f"{date_str}_timetable.json"
                    cleaned_file = self.plugin_data_path / f"{date_str}_schedule.json"

                    # 条件 2：如果今天的文件不存在（跨天了、或者之前失败了），则进行同步
                    if not cleaned_file.exists():
                        if not self.__api_token:
                            logger.error("缺失 api_token，更新进程将关闭。设置 api_token 并重启本插件。")
                            break
                        if not timetable_file.exists():
                            logger.info(f"[更新进程] 检测到今日({date_str})番剧时间表缺失，开始获取...")
                        else:
                            logger.info(f"[更新进程] 检测到今日({date_str})番剧时间表尚未做数据整理，开始整理...")
                            
                        await self.timetable_manager.fetch_daily() # 番剧时间表获取或整理

                        logger.info(f"[更新进程] 今日({date_str})番剧时间表本地同步成功。")
            
            except Exception as e:
                # 捕获 Manager 抛出的 3 次重试失败或其他未知异常，防止循环崩溃引发插件死机
                logger.error(f"[更新进程] 尝试更新今日番剧表时发生错误: {e}")

            # 每隔 3600 秒 (60分钟) 自动检查一次
            await asyncio.sleep(3600)

    @filter.command("test1")
    async def test(self, event: AstrMessageEvent):
        umo = event.unified_msg_origin
        message_chain = MessageChain().message("test!")
        await self.context.send_message(event.unified_msg_origin, message_chain)

    @filter.command("anime_notify_on")
    async def anime_notify_on(self, event: AstrMessageEvent):
        """为当前会话开启番剧开播提醒"""
        # 获取当前会话 ID
        umo = event.unified_msg_origin
        # 添加会话 ID 并自动同步到 JSON
        self.notify_list_manager.add(umo)

        # 1. 先把提示消息 yield 出去，用户会瞬间收到回复
        yield event.plain_result("已为当前聊天开启番剧开播提醒！")

        # 2. 定义一个并行的后台任务，让它在后台慢慢跑，不卡住当前的聊天
        async def background_fetch():
            try:
                self.timetable_manager.clear_expired_cache()
                await self.timetable_manager.fetch_daily()
                logger.info("用户开启提醒后，后台刷新番剧数据成功。")
            except Exception as e:
                logger.error(f"后台刷新番剧数据失败: {e}")

        # 3. 将任务丢进 asyncio 事件循环中（非阻塞）
        asyncio.create_task(background_fetch())

        # 清理缓存
        self.timetable_manager.clear_expired_cache()

        # notify manager 更新会话列表
        await self.notify_manager._load_notify_targets()

    @filter.command("anime_notify_off")
    async def anime_notify_off(self, event: AstrMessageEvent):
        """为当前会话关闭番剧开播提醒"""
        # 获取当前会话 ID
        umo = event.unified_msg_origin
        # 移除会话 ID 并自动同步到 JSON
        self.notify_list_manager.remove(umo)
        yield event.plain_result("已为当前聊天关闭番剧开播提醒！")

        # 清理缓存
        self.timetable_manager.clear_expired_cache()

        # notify manager 更新会话列表
        await self.notify_manager._load_notify_targets()


    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        self.__running = False          # 原有停止标志
        await self.notify_manager.stop()
