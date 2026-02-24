# 使用Python 3.11官方镜像
FROM python:3.11-slim

# 安装git和系统依赖
RUN apt-get update && apt-get install -y \
    git \
    ca-certificates \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖（包括从GitHub克隆）
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 设置环境变量
ENV PYTHONUNBUFFERED=1

# 启动应用
CMD ["python", "main.py"]
