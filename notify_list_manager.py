import json
from pathlib import Path

class NotifyListManager:
    """管理启用番剧推送的会话"""
    def __init__(self, plugin_data_path: Path): # 填入插件数据存储目录 Path
        self.__plugin_data_path = plugin_data_path
        self.__path = self.__plugin_data_path / "notify_list.json"
        self.__notify_list = []
        
        if self.__path.exists():
            self.__read_json()
        else:
            self.__create_json()

    @property
    def notify_list(self) -> list:
        """外部获取列表的接口"""
        return self.__notify_list

    def add(self, unified_msg_origin: str):
        """添加一项 unified_msg_origin 到 notify_list"""
        if unified_msg_origin not in self.__notify_list:
            self.__notify_list.append(unified_msg_origin)
            self.__update_json()

    def remove(self, unified_msg_origin: str):
        """从 notify_list 删除一项 unified_msg_origin"""
        if unified_msg_origin in self.__notify_list:
            self.__notify_list.remove(unified_msg_origin)
            self.__update_json()

    def __update_json(self):
        """更新写入JSON"""
        with open(self.__path, "w", encoding="utf-8") as f:
            json.dump(self.__notify_list, f, ensure_ascii=False, indent=4)

    def __read_json(self):
        """读取JSON"""
        try:
            with open(self.__path, "r", encoding="utf-8") as f:
                self.__notify_list = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            self.__notify_list = []

    def __create_json(self):
        """创建JSON"""
        self.__notify_list = []
        self.__update_json()