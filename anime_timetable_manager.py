import asyncio
import json
import httpx
from pathlib import Path
from datetime import datetime, timedelta, timezone
from astrbot.api import logger

class AnimeTimetableManager:
    """管理 bgm.wiki 获取番剧时间表数据"""

    def __init__(self, plugin_data_path: Path, api_token: str):
        # 确保传入的是 Path 对象，方便路径操作
        self.__plugin_data_path = Path(plugin_data_path)
        self.__api_token = api_token
        self.__beijing_tz = timezone(timedelta(hours=8)) # 北京时间

    async def fetch_daily(self):
            """从 bgm.wiki 获取今日番剧 JSON 数据，并直接触发同步清洗存储"""
            # 1. 计算日本时间（UTC+9）的当前时间窗基准日期
            jst_tz = timezone(timedelta(hours=9))
            now_jst = datetime.now(jst_tz)
            base_date = now_jst - timedelta(days=1) if now_jst.hour < 4 else now_jst
            date_str = base_date.strftime("%Y%m%d")
            
            file_path = self.__plugin_data_path / f"{date_str}_timetable.json"

            # 如果原始数据本地缓存已经存在，直接读取并进入清洗逻辑
            if file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                    self.save_schedule(raw_data)
                    return
                except json.JSONDecodeError:
                    pass

            if not self.__api_token:
                    logger.error("缺失 api_token，无法发起网络请求。")
                    return

            # 2. 计算时间窗时间戳 (日本时间 04:00 ~ 次日 04:00)
            start_time = datetime(base_date.year, base_date.month, base_date.day, 4, 0, 0, tzinfo=jst_tz)
            end_time = start_time + timedelta(days=1)
            
            # 毫秒级别的时间戳
            from_timestamp = int(start_time.timestamp() * 1000)
            to_timestamp = int(end_time.timestamp() * 1000)

            # 3. 发起网络请求
            url = "https://bgm.wiki/api/schedule/window"
            headers = {
                "Authorization": f"Bearer {self.__api_token}",
                "User-Agent": "AstrBot-AnimeNotifyPlugin/1.0",
                "Accept-Language": "zh-CN,en;q=0.9,ja;q=0.8"
            }
            params = {"from": from_timestamp, "to": to_timestamp}

            # 引入重试机制
            max_retries = 3
            retry_delay = 5  # 等待 5 秒
            raw_data = None  # 在外部定义变量用于接收数据

            async with httpx.AsyncClient() as client:
                for attempt in range(1, max_retries + 1):
                    try:
                        response = await client.get(url, headers=headers, params=params, timeout=10.0)
                        response.raise_for_status() 
                        raw_data = response.json()
                        
                        # 存储原始数据
                        with open(file_path, "w", encoding="utf-8") as f:
                            json.dump(raw_data, f, ensure_ascii=False, indent=4)
                        
                        break  # 请求并保存成功，跳出重试循环
                        
                    except Exception as e:
                        logger.warning(f"请求 bgm.wiki 失败 (尝试 {attempt}/{max_retries}): {e}")
                        if attempt == max_retries:
                            # 耗尽重试次数，抛出异常让外部守护任务感知
                            raise RuntimeError(f"请求 bgm.wiki 连续失败 {max_retries} 次，放弃。")
                        
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # 阻塞等待时间翻倍 (5s -> 10s)

            # 触发数据清洗
            if raw_data is not None:
                self.save_schedule(raw_data)
                return  # 成功后直接退出函数

    def save_schedule(self, raw_data: dict):
        """
        从 fetch_daily 获取的字典数据中清洗番剧时间表，仅保留各剧集最早播放时间和巴哈姆特动画疯时间，
        并按 airingId 从小到大排序保存至本地 YYYYMMDD_schedule.json (支持本地缓存检查)
        """
        from_ms = raw_data.get("from", 0)
        jst_tz = timezone(timedelta(hours=9))
        base_date = datetime.fromtimestamp(from_ms / 1000, tz=jst_tz)
        date_str = base_date.strftime("%Y%m%d")
        
        file_path = self.__plugin_data_path / f"{date_str}_schedule.json"

        # 如果清洗后的缓存已存在，直接跳过计算
        if file_path.exists():
            return
        
        events = raw_data.get("events", [])
        min_airing_map = {}
        animad_map = {}

        for item in events:
            ep_id = item.get("episodeId")
            if ep_id is None:
                continue
            if ep_id not in min_airing_map or item.get("airingId", float('inf')) < min_airing_map[ep_id].get("airingId", float('inf')):
                min_airing_map[ep_id] = item
            if item.get("platform", {}).get("key") == "animad":
                animad_map[ep_id] = item

        # 1. 借助字典，用 (bgmId, episodeSort, platform.text) 作为共同唯一标识符进行去重
        merged_events = {}
        for item in list(min_airing_map.values()) + list(animad_map.values()):
            # 提取三项组合标志符
            bgm_id = item.get("bgmId")
            ep_sort = item.get("episodeSort")
            platform_text = item.get("platform", {}).get("text", "")
            
            # 组合成元组作为唯一标志符的 key
            unique_key = (bgm_id, ep_sort, platform_text)
            
            # 只有当三项完全一致时，才会被视为同一个 event 并覆盖去重
            merged_events[unique_key] = item

        # 2. 对合并后的列表按 eventTsMs 排序并清洗
        cleaned_events = [
            {
                "eventTsMs": item.get("eventTsMs"),
                "eventAt": datetime.fromtimestamp(item.get("eventTsMs") / 1000, tz=beijing_tz).strftime("%m/%d %H:%M:%S") if item.get("eventTsMs") else "",
                "bgmId": item.get("bgmId"),
                "episodeDisplay": item.get("episodeDisplay"),
                "title": item.get("titles", {}).get("main", ""),
                "platform": item.get("platform", {}).get("text", "")
            }
            # 直接对字典的值按 eventTsMs 排序
            for item in sorted(merged_events.values(), key=lambda x: x.get("eventTsMs", 0))
        ]

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_events, f, ensure_ascii=False, indent=4)
        
        logger.info(f"完成番剧表整理，今日共{len(cleaned_events)}项。")

    def clear_expired_cache(self):
        """检查并清理过时的缓存文件（只保留昨天和今天以后的数据）"""
        try:
            jst_tz = timezone(timedelta(hours=9))
            now_jst = datetime.now(jst_tz)
            # 定义过期的分界线：昨天的 00:00 之前算过期
            yesterday = now_jst - timedelta(days=1)
            expire_date_str = yesterday.strftime("%Y%m%d")

            # 遍历数据目录下所有 json 文件
            for file in self.__plugin_data_path.glob("*.json"):
                # 过滤出符合规则的缓存文件，形如 20260705_timetable.json 或 20260705_schedule.json
                if "_timetable.json" in file.name or "_schedule.json" in file.name:
                    file_date_str = file.name.split("_")[0]
                    # 如果文件日期字符串长度为8且早于昨天，则删除
                    if len(file_date_str) == 8 and file_date_str < expire_date_str:
                        file.unlink()
                        logger.info(f"[清理进程] 已成功删除过时的番剧缓存文件: {file.name}")
        except Exception as e:
            logger.error(f"[清理进程] 清理过时缓存时发生错误: {e}")