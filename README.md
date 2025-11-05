# AI Headlines Pipeline

这是一个自动化的新闻采集、分析和发布的系统。

## 安全配置

由于项目包含敏感的凭证信息，我们需要特别注意安全配置：

1. `config/credentials.yaml` 文件包含飞书应用的凭证信息，不应提交到版本控制系统中。
2. 请使用 `config/credentials.template.yaml` 模板创建你的本地凭证文件。

### 配置步骤

1. 复制模板文件：
   ```bash
   cp config/credentials.template.yaml config/credentials.yaml
   ```

2. 编辑 `config/credentials.yaml` 文件，填入你的飞书应用凭证。

3. 确保 `config/credentials.yaml` 已添加到 `.gitignore` 文件中，避免意外提交。

## 开发环境设置

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

2. 配置 Redis：
   ```bash
   redis-server config/redis.conf
   ```

3. 启动应用：
   ```bash
   python apiserver/app/main.py
   ```