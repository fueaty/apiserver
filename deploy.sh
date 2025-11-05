#!/bin/bash

# 智能体工作流API服务部署脚本
set -e

echo "🚀 开始部署智能体工作流API服务..."

# 检查Docker是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ Docker未安装，请先安装Docker"
    exit 1
fi

# 检查Docker Compose是否安装
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose未安装，请先安装Docker Compose"
    exit 1
fi

# 检查环境变量文件
if [ ! -f .env ]; then
    echo "⚠️  未找到.env文件，使用.env.example创建默认配置"
    cp .env.example .env
    echo "📝 请编辑.env文件配置相关参数"
fi

# 创建日志目录
mkdir -p logs

# 停止现有服务
echo "🛑 停止现有服务..."
docker-compose down

# 构建镜像
echo "🔨 构建Docker镜像..."
docker-compose build

# 启动服务
echo "🚀 启动服务..."
docker-compose up -d

# 等待服务启动
echo "⏳ 等待服务启动..."
sleep 30

# 检查服务状态
echo "🔍 检查服务状态..."

# 检查Redis服务
if docker-compose ps redis | grep -q "Up"; then
    echo "✅ Redis服务运行正常"
else
    echo "❌ Redis服务启动失败"
    docker-compose logs redis
    exit 1
fi

# 检查API服务
if docker-compose ps api | grep -q "Up"; then
    echo "✅ API服务运行正常"
    
    # 测试健康检查接口
    if curl -f http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ 健康检查接口正常"
    else
        echo "❌ 健康检查接口异常"
        docker-compose logs api
        exit 1
    fi
else
    echo "❌ API服务启动失败"
    docker-compose logs api
    exit 1
fi

# 检查Celery Worker服务
if docker-compose ps celery-worker | grep -q "Up"; then
    echo "✅ Celery Worker服务运行正常"
else
    echo "❌ Celery Worker服务启动失败"
    docker-compose logs celery-worker
    exit 1
fi

echo ""
echo "🎉 部署完成！"
echo ""
echo "📊 服务信息："
echo "   API服务: http://localhost:8000"
echo "   API文档: http://localhost:8000/docs"
echo "   Flower监控: http://localhost:5555"
echo ""
echo "📋 常用命令："
echo "   查看服务状态: docker-compose ps"
echo "   查看服务日志: docker-compose logs -f"
echo "   停止服务: docker-compose down"
echo "   重启服务: docker-compose restart"
echo ""
echo "🔧 配置说明："
echo "   编辑 .env 文件修改配置参数"
echo "   编辑 config/ 目录下的配置文件调整平台设置"
echo ""

# 显示服务状态
docker-compose ps