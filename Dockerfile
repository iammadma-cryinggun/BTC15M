# 使用Python 3.11官方镜像
FROM python:3.11-slim

# 安装系统依赖（只需要ca-certificates用于HTTPS请求）
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 创建数据目录（用于持久化存储）
RUN mkdir -p /app/data

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data

# 启动应用
CMD ["python", "main.py"]
