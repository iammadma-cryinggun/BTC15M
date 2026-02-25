# GitHub & Zeabur 部署指南

## 📋 准备工作

### ✅ 已完成
- [x] Git仓库初始化
- [x] 敏感文件已排除（.env, *.db）
- [x] .gitignore已配置
- [x] .env.example模板已创建
- [x] 本地代码已提交

---

## 🚀 上传到GitHub

### 方法1：通过GitHub网页创建（推荐）

#### 步骤1：创建GitHub仓库
1. 访问 https://github.com/new
2. 填写仓库信息：
   - **Repository name**: `btc-15min-v5-professional`
   - **Description**: `BTC 15-minute Auto Trading System with Polymarket`
   - **Visibility**: 🔒 Private（强烈建议私有！）
   - **不要**勾选 "Add a README file"（已有README.md）
   - **不要**勾选 "Add .gitignore"（已配置）

3. 点击 **"Create repository"**

#### 步骤2：推送代码到GitHub

创建完成后，GitHub会显示推送命令。在命令行执行：

```bash
cd "D:\OpenClaw\workspace\BTC_15min_V5_Professional"

# 添加远程仓库（替换 YOUR_USERNAME 为你的GitHub用户名）
git remote add origin https://github.com/YOUR_USERNAME/btc-15min-v5-professional.git

# 推送代码
git push -u origin master
```

或者，如果你使用SSH（推荐）：
```bash
git remote add origin git@github.com:YOUR_USERNAME/btc-15min-v5-professional.git
git push -u origin master
```

---

### 方法2：通过GitHub CLI（gh命令）

如果已安装 `gh` 命令行工具：

```bash
cd "D:\OpenClaw\workspace\BTC_15min_V5_Professional"

# 登录GitHub
gh auth login

# 创建私有仓库并推送
gh repo create btc-15min-v5-professional --private --source=. --push
```

---

## 🔐 安全检查清单

上传前，请确认以下文件**不在**GitHub仓库中：

### ❌ 必须排除的文件
- `.env` - 包含私钥和API密钥
- `*.db` - 数据库文件
- `*.key` - 私钥文件
- `__pycache__/` - Python缓存

### ✅ 应该包含的文件
- `.env.example` - 环境变量模板
- `.gitignore` - 排除规则
- `README.md` - 项目说明
- `auto_trader_ankr.py` - 主程序

---

## 📊 验证上传

### 检查仓库内容
访问你的GitHub仓库页面，确认：
1. ✅ 所有代码文件都已上传
2. ✅ **没有** `.env` 文件
3. ✅ **没有** `.db` 数据库文件
4. ✅ 有 `.env.example` 模板文件

### 如果发现敏感文件已泄露
立即执行以下操作：

1. **从仓库中删除敏感文件**
   ```bash
   # 从Git历史中彻底删除
   git filter-branch --force --index-filter \
     "git rm --cached --ignore-unmatch .env" \
     --prune-empty --tag-name-filter cat -- --all

   # 强制推送
   git push origin --force --all
   ```

2. **立即轮换所有密钥**
   - 更换Polymarket钱包私钥
   - 更换Telegram Bot Token
   - 更换所有API密钥

---

## 🚀 部署到Zeabur

### 步骤1：连接GitHub到Zeabur

1. 访问 https://zeabur.com
2. 使用GitHub账号登录
3. 授权Zeabur访问你的GitHub仓库

### 步骤2：创建新项目

1. 点击 **"New Project"**
2. 选择 **"Deploy from GitHub"**
3. 选择 `btc-15min-v5-professional` 仓库

### 步骤3：配置环境变量

在Zeabur项目设置中，添加环境变量：

| 变量名 | 值 | 说明 |
|--------|-----|------|
| `PRIVATE_KEY` | 你的私钥 | Polymarket钱包私钥 |
| `HTTP_PROXY` | `http://your-proxy:port` | 代理地址 |
| `HTTPS_PROXY` | `http://your-proxy:port` | 代理地址 |
| `TELEGRAM_ENABLED` | `true` | 启用Telegram通知 |
| `TELEGRAM_BOT_TOKEN` | 你的Bot Token | Telegram机器人 |
| `TELEGRAM_CHAT_ID` | 你的Chat ID | Telegram接收者 |
| `DRY_RUN` | `false` | 真实交易模式 |

### 步骤4：部署服务

1. 选择服务类型：**Python**
2. 设置启动命令：
   ```bash
   ./start.sh
   ```
   **或者**
   ```bash
   python start.sh
   ```
3. 点击 **"Deploy"**

**重要提示：** 使用 `start.sh` 会自动同时启动：
- Binance Oracle（提供UT Bot趋势信号）
- 交易机器人（执行交易）

如果只启动 `auto_trader_ankr.py`，UT Bot会一直显示NEUTRAL！

---

## 🔍 部署后验证

### 检查日志
在Zeabur控制台查看日志，确认：
- ✅ 代理连接成功
- ✅ Polymarket API连接成功
- ✅ 钱包余额查询成功
- ✅ Telegram通知正常

### 测试交易
1. 观察日志中的交易信号
2. 确认订单执行
3. 检查Telegram通知

---

## 📝 日常维护

### 更新代码
```bash
# 本地修改后
git add .
git commit -m "Update description"
git push

# Zeabur会自动重新部署
```

### 查看日志
- Zeabur控制台 → 选择服务 → Logs

### 停止服务
- Zeabur控制台 → 选择服务 → Stop

---

## ⚠️ 重要提醒

1. **永远不要**将 `.env` 文件提交到GitHub
2. **永远使用** 私有仓库存储交易机器人代码
3. **定期轮换** API密钥和私钥
4. **监控** Zeabur部署的运行状态
5. **备份** 数据库文件到本地

---

## 🆘 常见问题

### Q1: git push 失败，提示"Permission denied"
**A:** 检查GitHub仓库权限，确保你有写入权限。使用SSH方式连接。

### Q2: Zeabur部署后无法连接Polymarket
**A:** 检查环境变量中的代理配置是否正确。

### Q3: 如何在Zeabur上查看数据库？
**A:** Zeabur是临时容器，数据库会丢失。建议：
- 使用外部数据库（如Supabase）
- 或定期导出数据到本地

### Q4: Telegram通知不工作
**A:** 检查：
- `TELEGRAM_BOT_TOKEN` 是否正确
- `TELEGRAM_CHAT_ID` 是否正确
- 机器人是否被拉入群组（如果是群组通知）

---

**部署成功后，你的交易机器人将7x24小时自动运行！🚀**
