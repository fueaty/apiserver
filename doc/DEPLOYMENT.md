# 部署指南

本文档介绍了如何构建和部署API Server应用。

## 目录

1. [使用Docker构建](#使用docker构建)
2. [使用Docker Compose部署](#使用docker-compose部署)
3. [环境变量配置](#环境变量配置)
4. [数据持久化](#数据持久化)
5. [故障排除](#故障排除)

## 使用Docker构建

### 构建镜像

```bash
docker build -t apiserver:latest .
```

### 运行容器

```bash
docker run -d \
  --name apiserver \
  -p 8000:8000 \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  apiserver:latest
```

## 使用Docker Compose部署

### 启动所有服务

```bash
docker-compose up -d
```

这将启动以下服务：
- apiserver: 主应用服务
- redis: Redis缓存服务
- mongodb: MongoDB数据库服务

### 查看服务状态

```bash
docker-compose ps
```

### 查看日志

```bash
# 查看所有服务日志
docker-compose logs

# 查看特定服务日志
docker-compose logs apiserver
```

### 停止服务

```bash
docker-compose down
```

### 重新构建并启动

```bash
docker-compose up -d --build
```

## 环境变量配置

可以通过以下环境变量配置应用：

| 变量名 | 描述 | 默认值 |
|--------|------|--------|
| ENV | 运行环境 (development, production) | development |
| REDIS_URL | Redis连接URL | redis://redis:6379 |
| MONGODB_URL | MongoDB连接URL | mongodb://admin:admin123@mongodb:27017 |
| PORT | 应用监听端口 | 8000 |

在docker-compose.yml中配置环境变量：

```yaml
services:
  apiserver:
    environment:
      - ENV=production
      - REDIS_URL=redis://redis:6379
      - MONGODB_URL=mongodb://admin:admin123@mongodb:27017
```

## 数据持久化

数据通过Docker卷进行持久化存储：

- Redis数据存储在`redis_data`卷中
- MongoDB数据存储在`mongodb_data`卷中
- 应用配置文件、数据和日志通过绑定挂载到主机目录

确保在生产环境中正确备份这些数据卷。

## 故障排除

### 构建失败

如果构建失败，请检查：
1. Dockerfile中的依赖是否正确
2. requirements.txt中的包版本是否可用
3. 系统是否有足够的磁盘空间

### 容器无法启动

如果容器无法启动，请检查：
1. 端口是否被占用
2. 挂载的目录权限是否正确
3. 环境变量是否配置正确

查看容器日志以获取更多信息：
```bash
docker logs apiserver
```

### 采集脚本问题

如果采集脚本无法正常工作：
1. 检查网络连接是否正常
2. 确认Playwright浏览器是否正确安装
3. 查看日志中是否有相关错误信息

### 性能问题

如果遇到性能问题：
1. 检查容器资源限制
2. 调整采集频率避免对目标网站造成压力
3. 考虑水平扩展部署多个采集实例