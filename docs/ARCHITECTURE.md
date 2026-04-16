# 系统架构

## 整体架构

```
┌─────────────────────────────────────────────────┐
│                   Web UI (Flask)                │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ 推文列表  │  │ RSS 资讯  │  │  日志/控制面板 │  │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘  │
│       │              │               │          │
│  ┌────┴──────────────┴───────────────┴───────┐  │
│  │              REST API Layer               │  │
│  └───────────────────┬───────────────────────┘  │
└──────────────────────┼──────────────────────────┘
                       │
          ┌────────────┴────────────┐
          │                         │
    ┌─────┴──────┐           ┌─────┴──────┐
    │  Scraper   │           │ Translator │
    │  Pipeline  │           │  Pipeline  │
    └─────┬──────┘           └─────┬──────┘
          │                        │
    ┌─────┴──────────┐       ┌─────┴────────┐
    │ 4-Tier Source   │       │ Google Trans  │
    │ Fallback Chain  │       │ + Glossary    │
    └────────────────┘       └──────────────┘
```

## 推文抓取降级链路

```
        ┌───────────────┐
        │ 开始抓取       │
        └───────┬───────┘
                │
        ┌───────▼───────┐     有 Bearer Token?
        │ Twitter API v2 ├──── 是 → 调用官方 API
        └───────┬───────┘     否 → 跳过
                │ 失败/跳过
        ┌───────▼───────────┐
        │ Syndication       │  获取推文 ID 列表
        │ + fxtwitter       ├── → fxtwitter 取内容
        └───────┬───────────┘  429？连续 3 次放弃
                │ 失败
        ┌───────▼───────────┐
        │ fxtwitter 刷新     │  用缓存中已知推文 ID
        │ (纯 fxtwitter)    ├── 逐条刷新内容
        └───────┬───────────┘
                │ 失败（无缓存 ID）
        ┌───────▼───────┐
        │ Nitter RSS    │  需要 TWITTER_ALLOW_NITTER_FALLBACK=1
        └───────┬───────┘
                │ 失败
        ┌───────▼───────┐
        │ 缓存回退       │  显示上次成功抓取的数据
        └───────────────┘
```

## 翻译流水线

```
原文推文 ──→ expand_twitter_slang() ──→ Google Translate ──→ POST_TRANSLATION_FIXES ──→ 中文输出
  │              │                          │                       │
  │     口语展开：                    机器翻译             术语后处理修正：
  │     W → Win                                          砖块 → 打铁
  │     PTS → points                                     海报 → 隔扣
  │     ngl → not gonna lie                              烹饪 → 大杀四方
  │     (仅大写: TO → turnovers)                          阿德托昆博 → 安特托昆博
```

## 数据模型

### Tweet

```python
@dataclass
class Tweet:
    tweet_id: str           # 推文 ID
    player_name: str        # 球员名
    player_handle: str      # Twitter handle
    content: str            # 英文原文
    content_cn: str | None  # 中文翻译
    url: str                # 推文链接
    tweet_date: datetime    # 发布时间
    media_urls: list[str]   # 媒体附件
    cover_image_path: str | None  # 封面截图路径
    retweet_count: int
    like_count: int
    reply_count: int
    tweet_type: str         # original/retweet/quote/reply
    translation_status: str # pending/completed/failed
```

### Article (RSS)

```python
@dataclass
class Article:
    title: str
    url: str
    summary: str
    source: str             # Yahoo/ESPN/CBS
    publish_date: datetime
    title_cn: str | None
    summary_cn: str | None
    translation_status: str
```

## 并发模型

- Web 服务：Flask 单线程 + 后台 daemon 线程
- 抓取任务：`threading.Thread(daemon=True)` + `asyncio.new_event_loop()`
- 推文锁：`threading.Lock()` (`_tweets_lock`) 保护共享状态
- 并发抓取：`asyncio.Semaphore(3)` 限制同时抓取球员数

## 安全设计

| 威胁 | 防护 |
|------|------|
| 路径遍历 | 正则白名单校验文件名（`/covers/`, `/video/`） |
| XSS | 前端 `esc()` 函数转义所有用户内容 |
| 注入 | 无 SQL 拼接，JSON 存储或 SQLite 参数化 |
| 参数篡改 | `?days=abc` → HTTP 400 |
| 并发冲突 | 抓取运行时重复请求 → HTTP 409 |
