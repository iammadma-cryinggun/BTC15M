# 🔍 CVD数据源诊断报告

## 检查时间：2026-03-02 13:46

---

## 📊 诊断结果

### ❌ 问题确认

**oracle_signal.json 文件不存在**
- 路径：`D:\OpenClaw\workspace\BTC_15min_Lite\oracle_signal.json`
- 状态：❌ 文件不存在
- 原因：`binance_oracle.py` 没有运行

**影响**：
- ❌ CVD 数据无法获取
- ❌ CVD 规则无法投票
- ❌ 统治级权重（55%）失效
- ❌ 系统退化为普通技术指标系统

---

## 🚀 解决方案

### 方案1：手动启动（推荐用于测试）

打开新的终端窗口，执行：

```bash
# 进入项目目录
cd D:\OpenClaw\workspace\BTC_15min_Lite

# 启动 binance_oracle.py
python binance_oracle.py
```

**预期输出**：
```
[ORACLE] Binance Oracle 启动
[ORACLE] CVD窗口: 1分钟 + 5分钟
[ORACLE] 连接到 Binance WebSocket...
[ORACLE] 已订阅 BTCUSDT 交易流
[ORACLE] 信号文件: oracle_signal.json
```

**验证**：
```bash
# 等待10秒后，检查文件是否生成
ls -la oracle_signal.json

# 查看文件内容
cat oracle_signal.json
```

---

### 方案2：后台运行（推荐用于生产）

#### Windows (PowerShell)

```powershell
# 使用 Start-Process 后台运行
cd D:\OpenClaw\workspace\BTC_15min_Lite
Start-Process python -ArgumentList "binance_oracle.py" -WindowStyle Hidden

# 或者使用 nohup（如果安装了 Git Bash）
nohup python binance_oracle.py > oracle.log 2>&1 &
```

#### Linux / macOS

```bash
cd D:\OpenClaw\workspace\BTC_15min_Lite

# 使用 nohup 后台运行
nohup python binance_oracle.py > oracle.log 2>&1 &

# 或者使用 screen
screen -dmS oracle python binance_oracle.py

# 或者使用 tmux
tmux new -d -s oracle 'python binance_oracle.py'
```

---

### 方案3：使用 PM2（最推荐）

PM2 是专业的进程管理工具，支持自动重启、日志管理等。

```bash
# 安装 PM2（如果还没有）
npm install -g pm2

# 启动 binance_oracle.py
cd D:\OpenClaw\workspace\BTC_15min_Lite
pm2 start binance_oracle.py --name btc-oracle --interpreter python

# 查看状态
pm2 status

# 查看日志
pm2 logs btc-oracle

# 设置开机自启
pm2 startup
pm2 save
```

**PM2 优势**：
- ✅ 自动重启（崩溃后自动恢复）
- ✅ 日志管理（自动轮转）
- ✅ 监控面板（CPU、内存使用）
- ✅ 开机自启

---

## 🔧 创建启动脚本

### Windows 批处理脚本

创建 `start_oracle.bat`：

```batch
@echo off
echo ========================================
echo 启动 Binance Oracle (CVD数据源)
echo ========================================
echo.

cd /d D:\OpenClaw\workspace\BTC_15min_Lite

echo [1/3] 检查 Python 环境...
python --version
if errorlevel 1 (
    echo [错误] Python 未安装或未添加到 PATH
    pause
    exit /b 1
)

echo [2/3] 检查 binance_oracle.py...
if not exist binance_oracle.py (
    echo [错误] binance_oracle.py 文件不存在
    pause
    exit /b 1
)

echo [3/3] 启动 Oracle...
echo.
echo ========================================
echo Oracle 正在运行...
echo 按 Ctrl+C 停止
echo ========================================
echo.

python binance_oracle.py

pause
```

**使用方法**：
双击 `start_oracle.bat` 即可启动

---

### Linux/macOS Shell 脚本

创建 `start_oracle.sh`：

```bash
#!/bin/bash

echo "========================================"
echo "启动 Binance Oracle (CVD数据源)"
echo "========================================"
echo ""

cd "$(dirname "$0")"

echo "[1/3] 检查 Python 环境..."
if ! command -v python3 &> /dev/null; then
    echo "[错误] Python3 未安装"
    exit 1
fi
python3 --version

echo "[2/3] 检查 binance_oracle.py..."
if [ ! -f "binance_oracle.py" ]; then
    echo "[错误] binance_oracle.py 文件不存在"
    exit 1
fi

echo "[3/3] 启动 Oracle..."
echo ""
echo "========================================"
echo "Oracle 正在运行..."
echo "按 Ctrl+C 停止"
echo "========================================"
echo ""

python3 binance_oracle.py
```

**使用方法**：
```bash
chmod +x start_oracle.sh
./start_oracle.sh
```

---

## 📋 验证清单

启动 `binance_oracle.py` 后，按以下步骤验证：

### 1. 检查进程是否运行

```bash
# Windows (PowerShell)
Get-Process | Where-Object {$_.ProcessName -like "*python*"}

# Linux/macOS
ps aux | grep binance_oracle
```

### 2. 检查文件是否生成

```bash
# 等待10秒后检查
ls -la oracle_signal.json

# 应该看到文件存在，大小约 200-500 字节
```

### 3. 查看文件内容

```bash
cat oracle_signal.json

# 应该看到类似内容：
{
  "cvd_1m": 50000.0,
  "cvd_5m": 120000.0,
  "signal_score": 4.5,
  "ut_hull_trend": "LONG",
  "momentum_30s": 1.2,
  "momentum_60s": 2.3,
  "momentum_120s": 3.5,
  "timestamp": 1709358000.123
}
```

### 4. 检查数据新鲜度

```bash
# 查看文件修改时间
ls -l oracle_signal.json

# 应该是最近几秒内修改的
```

### 5. 观察主程序日志

重启 `auto_trader_ankr.py` 或 `v6_hft_engine.py`，应该看到：

```
[ORACLE] 💰 CVD 1m: +50000, CVD 5m: +120000

[VOTING] 规则投票 (12个规则参与):
...
6. Oracle 5m CVD : LONG 80% - 5m CVD +120000
7. Oracle 1m CVD : LONG 67% - 1m CVD +50000
8. Delta Z-Score : LONG 75% - Delta标准化
...
```

---

## ⚠️ 常见问题

### 问题1：启动后立即退出

**可能原因**：
- Python 依赖缺失
- 网络连接问题
- 代理配置错误

**解决方案**：
```bash
# 检查依赖
pip install websockets pandas numpy requests

# 检查网络
ping api.binance.com

# 检查代理（如果使用）
echo $HTTP_PROXY
echo $HTTPS_PROXY
```

### 问题2：文件生成但数据为空

**可能原因**：
- Binance WebSocket 连接失败
- 数据还在初始化（需要等待1-2分钟）

**解决方案**：
```bash
# 查看日志
tail -f oracle.log

# 等待1-2分钟让数据积累
```

### 问题3：数据过期警告

**日志显示**：
```
[ORACLE] ⚠️ 数据过期: 120.5秒前
```

**原因**：
- `binance_oracle.py` 已停止运行
- 进程崩溃

**解决方案**：
```bash
# 重启 binance_oracle.py
pm2 restart btc-oracle

# 或手动重启
python binance_oracle.py
```

---

## 🎯 推荐配置

### 生产环境（推荐）

```bash
# 使用 PM2 管理
pm2 start binance_oracle.py --name btc-oracle --interpreter python
pm2 startup
pm2 save

# 同时启动主程序
pm2 start v6_hft_engine.py --name btc-trader --interpreter python
```

### 开发环境

```bash
# 使用两个终端窗口

# 终端1：运行 Oracle
cd D:\OpenClaw\workspace\BTC_15min_Lite
python binance_oracle.py

# 终端2：运行主程序
cd D:\OpenClaw\workspace\BTC_15min_Lite
python v6_hft_engine.py
```

---

## 📊 监控建议

### 1. 定期检查 oracle_signal.json

```bash
# 每分钟检查一次文件修改时间
watch -n 60 'ls -l oracle_signal.json'
```

### 2. 监控 CVD 数据

```bash
# 实时查看 CVD 数据
watch -n 5 'cat oracle_signal.json | grep cvd'
```

### 3. 日志监控

```bash
# 实时查看 Oracle 日志
tail -f oracle.log

# 或使用 PM2
pm2 logs btc-oracle --lines 100
```

---

## 🎉 总结

**当前状态**：
- ❌ `binance_oracle.py` 未运行
- ❌ `oracle_signal.json` 不存在
- ❌ CVD 数据缺失

**下一步**：
1. ✅ 启动 `binance_oracle.py`（使用上述任一方案）
2. ✅ 验证 `oracle_signal.json` 文件生成
3. ✅ 检查 CVD 数据是否正常
4. ✅ 重启主程序，观察 CVD 规则投票

**推荐方案**：
- 开发测试：手动启动（方案1）
- 生产环境：PM2 管理（方案3）

---

**诊断人员**：Claude Sonnet 4.5  
**诊断时间**：2026-03-02 13:46  
**状态**：等待启动 binance_oracle.py
