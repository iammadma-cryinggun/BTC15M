# 使用Python 3.11官方镜像
FROM python:3.11-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    ca-certificates \
    wget \
    unzip \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装基础Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 安装 py-clob-client（使用下载方式，避免git认证问题）
RUN cd /tmp && \
    wget https://github.com/Polymarket/clob-py-client/archive/refs/heads/main.zip -O clob-client.zip && \
    unzip clob-client.zip && \
    cd clob-py-client-main && \
    pip install -e . && \
    cd / && \
    rm -rf /tmp/clob-client.zip /tmp/clob-py-client-main

# 复制应用代码
COPY . .

# 设置环境变量
ENV PYTHONUNBUFFERED=1

# 启动应用
CMD ["python", "main.py"]
