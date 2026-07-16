# astrbot-plugin-anime-notify

基于 bgm.wiki 的番剧开播提醒插件。在配置后自动监控新番更新，并在番剧开播时主动发送提醒到指定聊天。

## 功能特性

- 🎬 **自动番剧更新** - 每 60 分钟自动检查并更新番剧时间表
- 🔔 **开播提醒** - 支持自定义提醒时间（可提前 N 分钟）
- 🎯 **灵活控制** - 可为指定聊天频道开启/关闭提醒
- 📦 **自动清理** - 每 12 小时自动清理过期缓存
- 🎨 **自定义模板** - 支持自定义提醒消息格式

## 安装

1. 将插件文件夹放入 AstrBot 的 `data/plugins/` 目录
2. 重启 AstrBot

## 配置

### 必需配置

在 AstrBot 的插件配置中填写以下内容：

```json
{
  "bgm_api_token": "你的 bgm.wiki API Token"
}
```

#### 获取 API Token

1. 访问 [bgm.wiki](https://bgm.wiki) 官网
2. 登录或注册账户
3. 在设置中生成 API Token
4. 将 Token 复制到插件配置中

### 可选配置

```json
{
  "notify_advance_minutes": 5,
  "notify_template": "📣番剧开播提醒：\n《{title}》#{episodeDisplay}\n在{platform}开播了！\n开播时间：{eventAt}\nbgmId：{bgmId}"
}
```

**配置说明：**

| 配置项 | 说明 | 默认值 | 类型 |
|------|------|--------|------|
| `bgm_api_token` | bgm.wiki API Token | - | string |
| `notify_advance_minutes` | 提前几分钟发送提醒 | 5 | int |
| `notify_template` | 提醒消息模板 | 自定义提醒文字模板 | text |

**模板变量：**

- `{title}` - 番剧标题
- `{episodeDisplay}` - 集数显示
- `{platform}` - 放送平台
- `{eventAt}` - 开播时间
- `{bgmId}` - bgm.wiki ID

## 使用

### 启用提醒

在聊天中发送命令：

```
/anime_notify_on
```

启用后，该聊天频道将接收番剧开播提醒。首次启用会自动获取并缓存当日的番剧时间表。

### 禁用提醒

```
/anime_notify_off
```

禁用后，该聊天频道将不再接收番剧开播提醒。

## 工作流程

1. **初始化** - 启动时创建后台任务
2. **定时更新** - 每 60 分钟检查一次通知列表，若非空则获取最新番剧数据
3. **缓存清理** - 每 12 小时清理过期缓存文件
4. **自动提醒** - 根据配置的提前时间发送开播提醒

## 支持

- [AstrBot 仓库](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 插件开发文档 (中文)](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot 插件开发文档 (English)](https://docs.astrbot.app/en/dev/star/plugin-new.html)
- [bgm.wiki 官网](https://bgm.wiki)
