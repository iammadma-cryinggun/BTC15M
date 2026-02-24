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

# 尝试安装 py-clob-client（多种方式）
RUN echo "Attempting to install py-clob-client..." && \
    pip install polymarket-clob || \
    pip install clob-client || \
    pip install py-clob-client || \
    echo "WARNING: py-clob-client installation failed, will run in signal-only mode"

# 复制应用代码
COPY . .

# 设置环境变量
ENV PYTHONUNBUFFERED=1

# 启动应用
CMD ["python", "main.py"]
