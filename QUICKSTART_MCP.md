# 🚀 Scholar Scout MCP 服务器快速入门

只需 5 分钟，让你的 AI 助手可以自动处理 Google Scholar 论文！

## 📦 第一步：安装

```bash
# 1. 进入项目目录
cd /path/to/scholar-scout

# 2. 运行自动安装脚本
./setup_mcp.sh

# 或者手动安装：
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## ⚙️ 第二步：配置

### 1. 设置环境变量

编辑 `.env` 文件：

```env
GMAIL_USERNAME=your.email@gmail.com
GMAIL_APP_PASSWORD=your-app-password    # 从 Google 获取应用专用密码
PPLX_API_KEY=your-perplexity-api-key    # 从 Perplexity 获取
SLACK_API_TOKEN=xoxb-your-slack-token   # 从 Slack 获取
```

📝 **获取凭证帮助：**
- Gmail 应用密码: https://support.google.com/accounts/answer/185833
- Perplexity API: https://www.perplexity.ai/
- Slack Token: 在 Slack App 设置中创建 Bot Token

### 2. 配置研究主题

编辑 `config/config.yml`：

```yaml
research_topics:
  - name: "LLM Inference"
    description: "Large language model inference and optimization"
    keywords:
      - "language model inference"
      - "LLM serving"
    slack_users:
      - "@your_username"
    slack_channel: "#research-papers"
```

## 🧪 第三步：测试

```bash
# 测试 MCP 服务器是否正常工作
python scripts/test_mcp_server.py

# 运行完整测试（获取邮件 + 分类论文）
python scripts/test_mcp_server.py --test-integration
```

如果看到 ✓ 标记，说明一切正常！

## 🔌 第四步：连接到 Claude Desktop

### 方法 A：自动配置（推荐）

1. 找到 Claude Desktop 配置文件位置：
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

2. 添加以下配置（**替换为你的实际路径**）：

```json
{
  "mcpServers": {
    "scholar-scout": {
      "command": "python",
      "args": [
        "/absolute/path/to/scholar-scout/scripts/run_mcp_server.py"
      ]
    }
  }
}
```

3. 重启 Claude Desktop

### 方法 B：手动运行

```bash
# 在终端运行 MCP 服务器
python scripts/run_mcp_server.py
```

## 💬 第五步：开始使用！

在 Claude Desktop 中，你现在可以：

### 示例 1：查看最新论文
```
你: 帮我查看最近的 Google Scholar 论文

Claude 会：
- 读取 scholar://papers/recent 资源
- 显示论文列表和主题
```

### 示例 2：运行完整工作流
```
你: 运行 Scholar Scout 完整流程

Claude 会：
1. 从 Gmail 获取邮件
2. 使用 AI 分类论文
3. 发送 Slack 通知
4. 显示结果摘要
```

### 示例 3：查找特定论文
```
你: 告诉我关于 "transformer" 的论文详情

Claude 会：
- 搜索包含 "transformer" 的论文
- 显示完整摘要和作者信息
```

## 🎯 常用命令

```bash
# 测试服务器
python scripts/test_mcp_server.py

# 运行服务器（调试模式）
python scripts/run_mcp_server.py --debug

# 手动运行原始分类器（不使用 MCP）
python scripts/run_classifier.py
```

## 🆘 遇到问题？

### 问题：找不到邮件

**解决方法：**
1. 检查 Gmail 文件夹名称是否正确
2. 确认 Google Scholar 提醒已启用
3. 查看 `config/search_criteria.yml` 中的搜索条件

### 问题：分类失败

**解决方法：**
1. 检查 Perplexity API key 是否有效
2. 查看 API 配额是否充足
3. 使用 `--debug` 标志查看详细日志

### 问题：Claude Desktop 看不到服务器

**解决方法：**
1. 确认配置文件路径使用**绝对路径**
2. 重启 Claude Desktop
3. 检查 Python 环境是否正确

## 📚 更多信息

- 完整文档：见 `MCP_README.md`
- 原始文档：见 `README.md`
- 问题反馈：创建 GitHub Issue

## 🎉 完成！

现在你的 AI 助手可以：
- ✅ 自动获取 Google Scholar 邮件
- ✅ 智能分类研究论文
- ✅ 发送 Slack 通知
- ✅ 回答你关于论文的问题

**享受自动化的研究工作流吧！** 🚀📚

---

## 架构简图

```
┌──────────────────────┐
│  AI Assistant        │  ← 你与 Claude/GPT 对话
│  (Claude Desktop)    │
└──────────┬───────────┘
           │ MCP Protocol
           │
┌──────────┴───────────┐
│  MCP Server          │  ← 本项目！
│  (Scholar Scout)     │
│                      │
│  📖 Resources:       │
│    - Emails          │
│    - Papers          │
│    - Topics          │
│                      │
│  🛠️ Tools:           │
│    - Fetch           │
│    - Classify        │
│    - Notify          │
└──────────┬───────────┘
           │
    ┌──────┴──────┐
    │   Gmail     │  Perplexity  Slack
    └─────────────┘
```

## 工作流程

```
1. AI 助手收到你的请求
   ↓
2. 调用 MCP Server 的工具
   ↓
3. MCP Server 执行操作：
   - 连接 Gmail
   - 使用 Perplexity AI 分类
   - 发送 Slack 通知
   ↓
4. 返回结果给 AI 助手
   ↓
5. AI 助手用自然语言回复你
```

**祝你使用愉快！** 🎓✨

