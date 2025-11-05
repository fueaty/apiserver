# 智能体工作流API服务 - 部署文档

## 1. 环境要求

- **操作系统**: Rocky Linux 8.5+
- **硬件配置**: 2核CPU, 2GB内存, 20GB SSD存储
- **软件依赖**: Python 3.9+, Nginx, Redis, Celery

## 2. 部署架构

本系统采用基于Nginx + Uvicorn + FastAPI的经典部署架构，并通过systemd进行进程守护。

```
┌─────────────────────────────────────────┐
│             服务器 (2核2G)               │
├─────────────┬──────────────┬────────────┤
│ Nginx (反向代理) │ Uvicorn (ASGI) │ 应用服务     │
│ - SSL终结    │ - 4工作进程   │ - FastAPI应用 │
│ - 静态资源    │ - 异步I/O     │ - 配置文件    │
└─────────────┴──────────────┴────────────┘
```

## 3. 部署流程

### 3.1 环境准备

```bash
# 安装依赖
yum install -y python3.9 python3.9-devel gcc nginx
pip3.9 install -r requirements.txt

# 配置防火墙
firewall-cmd --add-port=443/tcp --permanent
firewall-cmd --reload
```

### 3.2 应用部署

```bash
# 创建应用目录
mkdir -p /opt/agent-api/{app,config,logs}
chown -R nginx:nginx /opt/agent-api

# 配置systemd服务
cat > /etc/systemd/system/agent-api.service << EOF
[Unit]
Description=Agent API Service
After=network.target

[Service]
User=nginx
Group=nginx
WorkingDirectory=/opt/agent-api
ExecStart=/usr/local/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 启动服务
systemctl daemon-reload
systemctl enable --now agent-api
```

### 3.3 Nginx配置

```nginx
server {
    listen 443 ssl;
    server_name api.agent-platform.com;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    
    # SSL配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # 健康检查端点
    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        access_log off;
    }
}
```

## 4. 配置管理

- **配置文件**: 位于`/opt/agent-api/config/`目录，包括`main.yaml`, `sites.yaml`, `platforms.yaml`
- **热加载**: 支持配置文件的热加载，无需重启服务

## 5. 监控与告警

- **健康检查**: 访问`/health`端点获取服务状态
- **日志管理**: 日志文件位于`/var/log/intelligent-agent-api/app.log`

## 6. 版本更新

- **平滑更新**: 采用滚动更新策略，避免服务中断
- **版本回滚**: 支持通过Git回滚到历史版本
