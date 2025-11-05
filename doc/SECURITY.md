# 安全策略说明

## 敏感信息处理

本项目包含敏感的凭证信息，需要采取特殊的安全措施来保护这些信息。

## 推荐的安全实践

### 1. 使用模板文件

我们提供了一个模板文件 `config/credentials.template.yaml`，开发者应该复制这个文件并填入自己的凭证信息，而不是直接修改原始文件。

### 2. 使用加密工具

项目中包含了一个简单的加密工具 `scripts/encrypt_credentials.py`，可以用来加密敏感文件。

#### 使用步骤：

1. 生成加密密钥：
   ```bash
   python scripts/encrypt_credentials.py generate_key
   ```

2. 加密凭证文件：
   ```bash
   python scripts/encrypt_credentials.py encrypt config/credentials.yaml
   ```

3. 解密凭证文件：
   ```bash
   python scripts/encrypt_credentials.py decrypt config/credentials.yaml.encrypted
   ```

### 3. Git 版本控制策略

- 永远不要将包含真实凭证的文件提交到版本控制系统中
- 所有敏感文件都应添加到 `.gitignore` 文件中
- 可以将加密后的文件提交到版本控制系统中，但要确保加密密钥安全存储

## 部署时的安全考虑

在生产环境中，推荐使用专业的秘密管理服务，如：
- HashiCorp Vault
- AWS Secrets Manager
- Azure Key Vault
- Google Secret Manager

这些服务提供了更安全的方式来管理和访问敏感信息。