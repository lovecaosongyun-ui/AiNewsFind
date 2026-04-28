# 每日 AI 资讯生成智能体

一个面向中文内部简报场景的 Python 智能体项目。它会自动抓取国内外 AI 资讯，完成筛选、去重、分类、摘要，并生成偏政府内部材料风格的 `docx` 日报。

## 当前能力

- 默认接入 Qwen API 做中文摘要与分类；未配置 `DASHSCOPE_API_KEY` 时自动降级为规则摘要，保证项目可跑。
- 内置 10+ 个国内外 AI 资讯源和 1 个论文源，采用 RSS 与网页抓取混合模式。
- 输出 5 大模块：AI应用、AI模型、AI安全、AI投融资、最新研究论文。
- `docx` 文档支持标题、分节、图片、表格和正文链接。
- 图片优先使用原资讯正文中的图片；若抓取失败或无合适图片，会自动跳过，不影响成文。
- 内置日志、重试、可配置输出路径和文件命名规则。

## 目录结构

```text
AiNewsFind-GPT/
├─ ai_news_agent/           # 核心代码
├─ config/default_config.yaml
├─ output/                  # 生成文档输出目录（运行后自动创建）
├─ logs/                    # 运行日志目录（运行后自动创建）
├─ run_daily_news.py        # 手动运行入口
├─ run_scheduler.py         # 定时运行入口
└─ requirements.txt
```

## 安装依赖

```powershell
pip install -r requirements.txt
```

## 配置 Qwen API

项目默认从环境变量 `DASHSCOPE_API_KEY` 读取百炼 API Key。

```powershell
$env:DASHSCOPE_API_KEY="你的百炼APIKey"
```

如果暂时不想调用 Qwen，也可以直接使用规则模式运行：

```powershell
python run_daily_news.py --skip-llm
```

## 手动运行

```powershell
python run_daily_news.py
```

常用参数：

```powershell
python run_daily_news.py --config config/default_config.yaml
python run_daily_news.py --skip-llm
python run_daily_news.py --max-items-per-section 4
```

## 可视化界面

启动本地控制台：

```powershell
python run_web_ui.py
```

打开：

```text
http://127.0.0.1:8001
```

界面支持：

- 配置抓取起止日期或回退小时数
如果你填了 开始日期/结束日期，系统优先按这个固定日期范围抓。
如果你没填日期，系统才会用“回退小时数”这个规则。
- 配置每站抓取上限
- 动态增删、启停和排序数据源
- 配置摘要字数范围、质量阈值、模块入选条数
- 保存配置并生成日报
- 下载 `docx`、`md` 和抓取统计 `txt`

## 定时运行

默认定时时间在 [default_config.yaml](./config/default_config.yaml) 里配置为 `09:00`。

```powershell
python run_scheduler.py
```

## 配置说明

主要配置都放在 [default_config.yaml](./config/default_config.yaml)：

- `runtime`：输出路径、并发数、抓取时效窗口、每个模块保留条数、文件名格式等。
- `summary`：摘要最少/最多字数。
- `quality`：资讯质量分最低阈值。
- `llm`：Qwen 模型名、温度、环境变量名等。
- `document`：标题、字体、字号、行距、分节顺序等。
- `filtering`：关键词、排除规则、分类关键词。
- `sources`：数据源地址、抓取类型、权重、选择器、是否默认视为 AI 相关。

## 默认文档风格

默认采用偏内部公文的版式取向：

- 标题使用小标宋风格
- 模块标题使用黑体
- 正文使用仿宋
- 行距较规整，适合内部流转和二次编辑

如果本机未安装对应中文字体，Word 会自动回退到系统可用字体，但文档仍可正常打开和编辑。

## 运行结果

成功执行后会在 `output/` 下生成类似文件：

```text
每日AI资讯_20260330_0930.docx
每日AI资讯_20260330_0930.md
每日AI资讯_20260330_0930_stats.txt
```

日志文件默认输出到：

```text
logs/ai_news_agent.log
```

## 已知说明

- 当前版本优先保证“可运行 + 可扩展 + 可配置”，没有为每个资讯站点单独做深度反爬适配。
- 对于需要登录、强反爬、强 JS 渲染的网站，后续可以按站点追加更强的抓取逻辑。
- 论文模块目前默认使用 `arXiv` 最新论文流，后续可以再补顶会官网或更细分的论文源。
