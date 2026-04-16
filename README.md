# Basketball Pulse — NBA 球星动态聚合平台

NBA 球星推文抓取、中英双语翻译与 Web 展示系统。支持多源数据抓取（Twitter API / Syndication / fxtwitter / Nitter），自动翻译，以及视频生成集成。

## 功能特性

- **多源推文抓取** — 4 层降级链路保障高可用：
  1. Twitter API v2（需 Bearer Token）
  2. Syndication + fxtwitter 组合（无需 token）
  3. fxtwitter 刷新模式（基于已知推文 ID）
  4. Nitter RSS（兼容降级）
- **智能翻译** — Google 翻译 + 篮球术语表 + 口语预处理 + 后处理修正
- **Web 仪表盘** — 推文列表、球星筛选、搜索、亮/暗主题
- **RSS 资讯** — Yahoo Sports / ESPN / CBS Sports NBA 新闻聚合
- **视频生成** — 对接外部视频 API，为推文生成短视频
- **服务日志** — 实时运行日志面板

## 快速开始

### 环境要求

- Python 3.11+
- pip

### 安装

```bash
git clone <repo-url>
cd basketball-news-scraper
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 启动 Web 服务

```bash
python -m web.app --host 0.0.0.0 --port 5000
```

访问 http://localhost:5000

### CLI 使用

```bash
# 抓取 RSS 资讯
python main.py scrape

# 抓取球星推文
python main.py twitter

# 指定球星
python main.py twitter --player KingJames

# 翻译测试
python main.py translate-test
```

### 环境变量

| 变量 | 说明 | 必需 |
|------|------|------|
| `TWITTER_BEARER_TOKEN` | Twitter API v2 Bearer Token | 否（有则启用 API 直连） |
| `TWITTER_ALLOW_NITTER_FALLBACK` | 设为 `1` 启用 Nitter RSS 降级 | 否 |

## 项目结构

```
basketball-news-scraper/
├── main.py                    # CLI 入口
├── run_demo.py                # 快速演示
├── generate_covers.py         # 封面图生成
├── generate_demo_tweets.py    # Demo 数据生成
├── requirements.txt
├── pyproject.toml
│
├── web/                       # Flask Web 应用
│   ├── app.py                 #   路由 + 抓取逻辑
│   ├── static/                #   CSS / 图片
│   └── templates/             #   Jinja2 页面
│       └── index.html
│
├── scraper/                   # 抓取模块
│   ├── base.py                #   基类
│   ├── nba_scraper.py         #   NBA 页面爬虫
│   ├── rss_scraper.py         #   RSS/Atom 解析
│   └── twitter_scraper.py     #   Twitter API + Nitter
│
├── translator/                # 翻译模块
│   ├── base.py                #   翻译协议
│   └── google_translator.py   #   Google 翻译后端
│
├── config/                    # 配置
│   ├── settings.py            #   全局设置
│   ├── players.py             #   球星账号加载
│   ├── players.json           #   35 位球星配置
│   ├── glossary.py            #   篮球术语表 + 翻译修正
│   └── sites.py               #   RSS 站点配置
│
├── models/                    # 数据模型
│   ├── article.py             #   文章模型
│   └── tweet.py               #   推文模型
│
├── storage/                   # 存储
│   ├── base.py                #   存储协议
│   ├── json_storage.py        #   JSON 文件
│   └── sqlite_storage.py      #   SQLite
│
├── browser/                   # 浏览器服务
│   ├── fetcher.py             #   HTTP 请求
│   └── screenshot.py          #   Playwright 截图
│
├── utils/                     # 工具
│   ├── claude_ai.py           #   Claude AI 集成
│   ├── exceptions.py          #   自定义异常
│   ├── headers.py             #   请求头
│   ├── http.py                #   HTTP 工具
│   ├── mood.py                #   情绪分析
│   ├── proxy.py               #   代理
│   ├── rate_limiter.py        #   限流器
│   └── robots.py              #   robots.txt 解析
│
├── cli/                       # CLI 模块
│   └── app.py                 #   命令行应用
│
├── tests/                     # 测试 (98 tests)
│   ├── conftest.py
│   ├── test_cli.py
│   ├── test_integration.py
│   ├── test_models.py
│   ├── test_rate_limiter.py
│   ├── test_scraper.py
│   ├── test_storage.py
│   ├── test_translator.py
│   ├── test_twitter_scraper.py
│   ├── test_web_app.py
│   └── fixtures/              #   测试数据
│
└── .github/
    ├── copilot-instructions.md
    └── agents/                #   AI 协作角色
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Web 首页 |
| GET | `/api/tweets` | 推文列表（支持 `?player=`、`?type=`、`?days=30`） |
| GET | `/api/tweet-status` | 推文抓取状态（含来源模式、日志） |
| POST | `/api/scrape-tweets` | 触发推文抓取 |
| GET | `/api/logs` | 服务运行日志（`?limit=50`） |
| GET | `/api/players` | 球星列表 |
| GET | `/api/articles` | RSS 资讯列表（`?source=`） |
| GET | `/api/sources` | 可用来源列表 |
| POST | `/api/scrape` | 触发 RSS 抓取 |
| POST | `/api/stop` | 停止抓取 |
| GET | `/api/status` | RSS 爬虫状态 |
| GET | `/api/video-status` | 视频生成状态 |
| POST | `/api/generate-videos` | 触发视频生成 |
| GET | `/covers/<file>` | 封面图片 |
| GET | `/video/<file>` | 视频文件 |

## 球星覆盖

当前追踪 35 位 NBA 球星/媒体，包括 LeBron James、Stephen Curry、Kevin Durant、Giannis Antetokounmpo、Luka Doncic、Ja Morant、Jayson Tatum 等，以及 @NBA、@ESPNNBA、@BleacherReport、@ShamsCharania 等媒体账号。

完整列表见 [config/players.json](config/players.json)。

## 翻译系统

- **预处理**：将 Twitter 口语/缩写展开为标准英文（如 `W` → `Win`，`PTS` → `points`）
- **翻译**：Google Translate（通过 deep-translator）
- **后处理**：篮球术语修正（200+ 条映射规则），修正常见机翻错误

术语表位于 [config/glossary.py](config/glossary.py)。

## 测试

```bash
# 运行全部测试
python -m pytest tests/ -q

# 运行特定模块测试
python -m pytest tests/test_web_app.py -v
python -m pytest tests/test_twitter_scraper.py -v
```

当前 98 项测试全部通过。

## 安全特性

- 路径遍历防护（封面/视频文件路由）
- XSS 防护（模板输出转义）
- 输入参数校验（`?days=abc` → HTTP 400）
- 无 SQL 注入风险（JSON / SQLite 参数化）

## 技术栈

- **后端**: Python 3.11+ / Flask
- **抓取**: httpx / urllib / BeautifulSoup / lxml
- **翻译**: deep-translator (Google)
- **前端**: 原生 HTML/CSS/JS（Jinja2 模板）
- **存储**: JSON / SQLite
- **测试**: pytest / pytest-asyncio

## 协作模式

本项目采用三角色 AI 协作：
- **Developer** — 架构设计与代码实现
- **Tester** — 测试编写与质量验证
- **Product Manager** — 设计审阅与方向把控

详见 [.github/copilot-instructions.md](.github/copilot-instructions.md)。

## License

MIT
