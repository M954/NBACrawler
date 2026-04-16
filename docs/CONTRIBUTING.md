# 开发指南

## 开发环境搭建

```bash
# 克隆仓库
git clone <repo-url>
cd basketball-news-scraper

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/macOS

# 安装依赖（含开发工具）
pip install -r requirements.txt
```

## 运行测试

```bash
# 全量测试
python -m pytest tests/ -q

# 带覆盖率
python -m pytest tests/ --cov=. --cov-report=term-missing

# 单模块测试
python -m pytest tests/test_web_app.py -v
```

## 代码结构约定

### 模块职责

| 模块 | 职责 | 依赖方向 |
|------|------|---------|
| `web/` | HTTP 路由、页面渲染 | → scraper, translator, config |
| `cli/` | 命令行入口 | → scraper, translator, config |
| `scraper/` | 数据抓取 | → browser, config, models |
| `translator/` | 翻译服务 | → config (glossary) |
| `models/` | 数据模型 | → utils (exceptions) |
| `storage/` | 持久化 | → models |
| `config/` | 配置加载 | 无外部依赖 |
| `utils/` | 通用工具 | 无外部依赖 |

### 数据流

```
Twitter/RSS  ──→  scraper/  ──→  models/  ──→  translator/  ──→  storage/
                                                                    │
                                                              web/  ←──┘
                                                              (API + UI)
```

## 添加新的推文源

1. 在 `web/app.py` 中添加 `async def _fetch_tweets_via_<name>(players)` 函数
2. 在 `_async_scrape_tweets()` 的降级链路中注册
3. 函数需返回 `list[dict]`，每项包含 `tweet_id`, `player_handle`, `content`, `tweet_date` 等字段
4. 在 `tests/test_web_app.py` 中 mock 新源并更新 `test_async_scrape_tweets_falls_back_to_cached_snapshot`

## 添加新球星

编辑 `config/players.json`：

```json
{
  "name": "球员全名",
  "handle": "TwitterHandle",
  "team": "球队名"
}
```

## 翻译术语维护

编辑 `config/glossary.py`：

- `POST_TRANSLATION_FIXES` — 翻译后修正（机翻错误 → 正确术语）
- `BASKETBALL_GLOSSARY` — 篮球专业术语映射
- `TWITTER_SLANG_EXPAND` — 推文口语展开（翻译前）
- `TWITTER_POST_FIXES` — 推文翻译后修正

**注意**：`CASE_SENSITIVE_KEYS` 中的缩写（TO/W/L 等）仅匹配全大写，避免破坏常见英文单词。

## API 开发

所有 API 端点定义在 `web/app.py`。约定：

- GET 用于查询，POST 用于状态变更
- 返回 JSON，错误时附带 `{"error": "描述"}` + 对应 HTTP 状态码
- 参数校验失败返回 400
- 并发冲突返回 409
