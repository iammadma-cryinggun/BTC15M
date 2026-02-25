# 使用Python 3.11官方镜像
FROM python:3.11-slim

# 安装系统依赖（只需要ca-certificates用于HTTPS请求）
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 设置脚本可执行权限
RUN chmod +x start.sh

# 设置环境变量
ENV PYTHONUNBUFFERED=1

# 启动应用（使用start.sh同时启动Oracle和交易引擎）
CMD ["./start.sh"]
