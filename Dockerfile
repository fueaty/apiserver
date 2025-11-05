# 使用Python 3.11作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 复制项目文件
COPY . /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon-x11-0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libxss1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 安装Playwright浏览器
RUN playwright install chromium

# 创建非root用户
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# 暴露端口（如果需要的话）
EXPOSE 8000

# 启动应用
CMD ["python", "main.py"]