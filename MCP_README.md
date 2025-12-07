# Scholar Scout MCP Server

这是 Scholar Scout 的 MCP (Model Context Protocol) 服务器实现。它允许 AI 助手（如 Claude Desktop）通过标准化协议与 Scholar Scout 系统交互。

## 📋 目录

- [什么是 MCP？](#什么是-mcp)
- [功能特性](#功能特性)
- [安装步骤](#安装步骤)
- [配置说明](#配置说明)
- [使用方法](#使用方法)
- [可用资源和工具](#可用资源和工具)
- [故障排查](#故障排查)

## 什么是 MCP？

**MCP (Model Context Protocol)** 是一个标准化协议，允许 AI 应用程序访问外部数据源和工具。通过 MCP 服务器，AI 助手可以：

- 📖 读取数据资源（Resources）
- 🛠️ 执行操作（Tools）
- 💬 使用预定义提示词（Prompts）

想象一下：MCP 服务器就像是 AI 助手的"外挂插件"，让它可以访问你的 Gmail、分类论文、发送 Slack 通知等！

## 功能特性

### 🔍 Resources (数据资源)

MCP 服务器提供三种数据资源，AI 助手可以随时读取：

1. **`scholar://emails/list`** - Google Scholar 邮件列表
   - 显示所有获取的邮件元数据（主题、发件人、日期）
   - 自动缓存以提高性能

2. **`scholar://papers/recent`** - 最近分类的论文
   - 显示论文的标题、作者、摘要（前200字）、发表地点
   - 包含匹配的研究主题

3. **`scholar://topics/config`** - 研究主题配置
   - 显示所有配置的研究主题
   - 包含关键词、Slack 频道和用户信息

### 🛠️ Tools (可执行工具)

提供五个强大的工具来自动化你的工作流：

1. **`fetch_emails`** - 从 Gmail 获取邮件
   - 参数：`force_refresh` (布尔值) - 强制刷新缓存
   - 获取符合配置条件的 Google Scholar 邮件

2. **`classify_papers`** - 使用 AI 分类论文
   - 参数：`fetch_first` (布尔值) - 先获取最新邮件
   - 从邮件中提取论文元数据
   - 使用 Perplexity AI 匹配研究主题

3. **`send_notifications`** - 发送 Slack 通知
   - 参数：`weekly_update` (布尔值) - 发送周报而非单个通知
   - 通知配置的用户和频道

4. **`run_pipeline`** - 运行完整工作流 ⭐
   - 参数：
     - `weekly_update` (布尔值，默认 true) - 发送周报
     - `delete_old_emails` (布尔值，默认 true) - 删除旧邮件
   - 执行完整流程：获取 → 分类 → 通知

5. **`get_paper_details`** - 获取论文详情
   - 参数：`index` (整数) 或 `title` (字符串)
   - 返回论文的完整信息（包括完整摘要）

## 安装步骤

### 1. 安装依赖项

首先，确保你已经安装了 Python 3.8 或更高版本。然后安装所需的包：

```bash
# 进入项目目录
cd /path/to/scholar-scout

# 安装依赖
pip install -r requirements.txt
```

**重要提示**：确保 `requirements.txt` 包含 `mcp>=0.1.0`。

### 2. 设置环境变量

创建 `.env` 文件（如果还没有）：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的凭证：

```env
# Gmail 凭证
GMAIL_USERNAME=your.email@gmail.com
GMAIL_APP_PASSWORD=your-app-specific-password

# Perplexity AI API
PPLX_API_KEY=your-perplexity-api-key

# Slack API
SLACK_API_TOKEN=xoxb-your-slack-token
```

**注意**：
- Gmail 需要使用[应用专用密码](https://support.google.com/accounts/answer/185833)，不是你的普通密码
- Perplexity API key 可以从 [Perplexity 网站](https://www.perplexity.ai/) 获取
- Slack token 需要从 Slack App 设置中获取

### 3. 配置研究主题

复制并编辑配置文件：

```bash
cp config/config.example.yml config/config.yml
```

编辑 `config/config.yml`，设置你的研究主题：

```yaml
email:
  username: ${GMAIL_USERNAME}
  password: ${GMAIL_APP_PASSWORD}
  folder: "Scholar"  # Gmail 文件夹名称

slack:
  api_token: ${SLACK_API_TOKEN}
  default_channel: "#research-papers"
  channel_topics:
    research-papers:
      - "LLM Inference"
      - "Distributed Systems"

perplexity:
  api_key: ${PPLX_API_KEY}
  model: "sonar-pro"

research_topics:
  - name: "LLM Inference"
    description: "Large language model inference and optimization"
    keywords:
      - "language model inference"
      - "LLM serving"
      - "model optimization"
    slack_users:
      - "@username"
    slack_channel: "#llm-papers"
```

## 配置说明

### 连接到 Claude Desktop

如果你想在 Claude Desktop 中使用这个 MCP 服务器：

1. 找到你的 Claude Desktop 配置文件：
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`

2. 编辑配置文件，添加 Scholar Scout 服务器：

```json
{
  "mcpServers": {
    "scholar-scout": {
      "command": "python",
      "args": [
        "/absolute/path/to/scholar-scout/scripts/run_mcp_server.py",
        "--config",
        "/absolute/path/to/scholar-scout/config/config.yml"
      ]
    }
  }
}
```

**重要**：请替换为你系统中的实际绝对路径！

3. 重启 Claude Desktop

4. 现在你可以在 Claude Desktop 中询问：
   - "帮我获取最新的 Scholar 邮件"
   - "分类最近的论文"
   - "运行完整的 Scholar Scout 工作流"

### 配置到其他 MCP 客户端

对于其他 MCP 客户端，你需要：

1. 运行 MCP 服务器：
```bash
python scripts/run_mcp_server.py
```

2. 配置客户端连接到服务器的 stdio 接口

## 使用方法

### 命令行使用

直接运行 MCP 服务器（主要用于调试）：

```bash
# 使用默认配置
python scripts/run_mcp_server.py

# 使用自定义配置
python scripts/run_mcp_server.py --config my_config.yml

# 启用调试日志
python scripts/run_mcp_server.py --debug
```

### 通过 Claude Desktop 使用

配置好 Claude Desktop 后，你可以直接与 Claude 对话：

**示例对话 1：查看邮件**
```
你：请帮我查看最新的 Google Scholar 邮件

Claude 会：
1. 读取 scholar://emails/list 资源
2. 显示邮件列表
```

**示例对话 2：分类论文**
```
你：帮我分类最近的论文

Claude 会：
1. 调用 classify_papers 工具
2. 使用 AI 分析论文
3. 显示分类结果
```

**示例对话 3：运行完整流程**
```
你：运行完整的 Scholar Scout 工作流

Claude 会：
1. 调用 run_pipeline 工具
2. 获取邮件
3. 分类论文
4. 发送 Slack 通知
5. 显示执行摘要
```

**示例对话 4：查看特定论文**
```
你：告诉我关于"transformer"的论文详情

Claude 会：
1. 调用 get_paper_details 工具
2. 搜索包含"transformer"的论文
3. 显示完整详情
```

## 可用资源和工具

### 资源列表

| URI | 名称 | 描述 |
|-----|------|------|
| `scholar://emails/list` | Scholar Emails | Google Scholar 邮件列表 |
| `scholar://papers/recent` | Recent Papers | 最近分类的论文 |
| `scholar://topics/config` | Research Topics | 研究主题配置 |

### 工具列表

| 工具名 | 描述 | 主要参数 |
|--------|------|----------|
| `fetch_emails` | 获取邮件 | `force_refresh` |
| `classify_papers` | 分类论文 | `fetch_first` |
| `send_notifications` | 发送通知 | `weekly_update` |
| `run_pipeline` | 完整流程 | `weekly_update`, `delete_old_emails` |
| `get_paper_details` | 论文详情 | `index` 或 `title` |

## 架构设计

### 为什么选择 MCP？

传统的自动化脚本有几个限制：

1. **不灵活**：只能按预设流程运行
2. **难以交互**：无法根据情况调整
3. **信息隔离**：难以与 AI 助手集成

MCP 服务器解决了这些问题：

```
┌─────────────────┐
│   AI Assistant  │  (Claude, GPT, etc.)
│   (用户交互)     │
└────────┬────────┘
         │ MCP Protocol
         │ (标准化通信)
┌────────┴────────┐
│   MCP Server    │
│ (Scholar Scout) │
├─────────────────┤
│   Resources     │  ← 数据访问层
│   - Emails      │
│   - Papers      │
│   - Config      │
├─────────────────┤
│     Tools       │  ← 操作执行层
│   - Fetch       │
│   - Classify    │
│   - Notify      │
└────────┬────────┘
         │
    ┌────┴────┐
    │  Gmail  │  Perplexity  Slack
    └─────────┘

```

### 缓存机制

为了提高性能，MCP 服务器使用了智能缓存：

- **邮件缓存**：获取的邮件会缓存 5 分钟
- **论文缓存**：分类结果会保留在内存中
- **自动刷新**：缓存过期或明确请求时自动刷新

这意味着你可以多次查询数据而不会重复调用 Gmail API。

### 异步设计

MCP 服务器使用 Python 的 `asyncio` 进行异步编程：

- **非阻塞 I/O**：邮件获取不会阻塞其他操作
- **线程池执行**：阻塞操作在线程池中运行
- **高并发**：可以同时处理多个请求

```python
# 示例：异步执行阻塞操作
loop = asyncio.get_event_loop()
emails = await loop.run_in_executor(None, fetch_emails)
```

## 故障排查

### 问题：无法连接到 Gmail

**症状**：收到 "Error connecting to Gmail" 错误

**解决方法**：
1. 检查 Gmail 用户名和密码是否正确
2. 确保使用的是[应用专用密码](https://support.google.com/accounts/answer/185833)
3. 检查 Gmail 是否启用了 IMAP 访问（Gmail 设置 → 转发和 POP/IMAP → 启用 IMAP）

### 问题：找不到邮件

**症状**：`fetch_emails` 返回 0 封邮件

**解决方法**：
1. 检查 `config.yml` 中的 `folder` 设置是否正确
2. 确认 Gmail 中该文件夹确实存在
3. 检查 `config/search_criteria.yml` 中的搜索条件
4. 验证 Google Scholar 提醒是否正在发送到该邮箱

### 问题：分类失败

**症状**：论文分类时出错

**解决方法**：
1. 检查 Perplexity API key 是否有效
2. 确认 API 配额是否充足
3. 查看日志了解具体错误信息（使用 `--debug` 标志）

### 问题：Slack 通知发送失败

**症状**：通知未出现在 Slack 频道

**解决方法**：
1. 验证 Slack API token 是否正确
2. 检查 bot 是否已被添加到目标频道
3. 确认频道名称格式正确（`#channel-name`）
4. 验证 Slack 用户名格式（`@username`）

### 问题：Claude Desktop 无法连接

**症状**：Claude Desktop 中看不到 Scholar Scout 服务器

**解决方法**：
1. 确认配置文件路径正确（使用绝对路径）
2. 重启 Claude Desktop
3. 检查 Python 环境是否正确（可以直接运行脚本测试）
4. 查看 Claude Desktop 的日志文件

### 调试技巧

1. **启用调试日志**：
```bash
python scripts/run_mcp_server.py --debug
```

2. **手动测试组件**：
```bash
# 测试 Gmail 连接
python -m tests.test_gmail_connection

# 测试分类器
python -m tests.test_scholar_classifier

# 测试 Slack 通知
python -m tests.test_slack_notifier
```

3. **检查环境变量**：
```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('Gmail:', os.getenv('GMAIL_USERNAME'))"
```

## 进阶使用

### 自定义研究主题

你可以在 `config/config.yml` 中添加任意数量的研究主题：

```yaml
research_topics:
  - name: "Deep Learning"
    description: "Neural networks and deep learning methods"
    keywords:
      - "neural network"
      - "deep learning"
      - "CNN"
      - "RNN"
    slack_users:
      - "@researcher1"
    slack_channel: "#dl-papers"
    
  - name: "Quantum Computing"
    description: "Quantum algorithms and hardware"
    keywords:
      - "quantum"
      - "qubit"
      - "quantum algorithm"
    slack_users:
      - "@researcher2"
    slack_channel: "#quantum-papers"
```

### 调整搜索条件

编辑 `config/search_criteria.yml` 来自定义邮件搜索：

```yaml
email_filter:
  from: "scholaralerts-noreply@google.com"
  time_window: "7D"  # 7天内的邮件
  subject:
    - "新引用提醒"
    - "新研究结果"

email_empty:
  time_window: "30D"  # 删除30天前的邮件
```

### 集成到 CI/CD

你可以在 CI/CD 流水线中使用 MCP 服务器：

```yaml
# GitHub Actions 示例
name: Weekly Scholar Scout
on:
  schedule:
    - cron: '0 0 * * 1'  # 每周一运行

jobs:
  run-scholar-scout:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run pipeline
        env:
          GMAIL_USERNAME: ${{ secrets.GMAIL_USERNAME }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          PPLX_API_KEY: ${{ secrets.PPLX_API_KEY }}
          SLACK_API_TOKEN: ${{ secrets.SLACK_API_TOKEN }}
        run: |
          python scripts/run_classifier.py
```

## 性能优化

### 缓存时间调整

在 `mcp_server.py` 中修改缓存超时时间：

```python
def _is_cache_stale(self) -> bool:
    """Check if cache is stale."""
    if not self._cache_timestamp:
        return True
    age = (datetime.now() - self._cache_timestamp).total_seconds()
    return age > 300  # 改为你想要的秒数
```

### 批量处理

对于大量邮件，可以调整批处理大小：

```python
# 在 classifier.py 中
def classify_papers(self, email_messages: List[Message], batch_size: int = 10):
    # 分批处理以避免内存问题
    for i in range(0, len(email_messages), batch_size):
        batch = email_messages[i:i+batch_size]
        # 处理批次...
```

## 安全考虑

1. **凭证管理**：
   - 永远不要将 `.env` 文件提交到 Git
   - 使用环境变量或密钥管理服务
   - 定期轮换 API keys

2. **访问控制**：
   - MCP 服务器通过 stdio 运行，只有本地进程可访问
   - 不会暴露网络端口

3. **日志安全**：
   - 日志中不包含敏感信息
   - 生产环境中使用 INFO 级别日志

## 贡献和支持

如果你遇到问题或有建议，请：

1. 查看本文档的故障排查部分
2. 检查项目的 Issues 页面
3. 创建新 Issue 并提供详细信息：
   - 错误消息
   - 日志输出
   - 配置文件（隐藏敏感信息）

## 许可证

本项目采用 MIT 许可证。详见 LICENSE 文件。

---

**快乐研究！📚✨**

