# Polymarket 地理限制解决方案

## 🌍 问题描述

```
PolyApiException[status_code=403]
Trading restricted in your region
```

## 📋 Polymarket CLOB 允许的地区

根据 Polymarket 文档，CLOB 交易在以下地区可用：
- ✅ 美国（US）
- ✅ 加拿大（CA）
- ✅ 英国（UK）
- ✅ 欧盟部分国家
- ❌ 中国大陆
- ❌ 其他限制地区

## 🚀 推荐部署平台

### 选项1：Railway（推荐）
- **服务器位置**：美国/欧盟
- **优点**：简单易用，支持GitHub一键部署
- **链接**：https://railway.app

### 选项2：Render
- **服务器位置**：美国俄勒冈
- **优点**：免费套餐，美国西部
- **链接**：https://render.com

### 选项3：Fly.io
- **服务器位置**：全球多地可选
- **优点**：边缘计算，低延迟
- **链接**：https://fly.io

### 选项4：Heroku
- **服务器位置**：美国弗吉尼亚
- **优点**：稳定可靠
- **链接**：https://heroku.com

### 选项5：NorthFlank（欧盟）
- **服务器位置**：欧盟
- **优点**：GDPR合规，可能在允许地区
- **链接**：https://northflank.com

## 🛠️ 迁移步骤

### 到 Railway 部署

1. 访问 https://railway.app
2. 用GitHub账号登录
3. 点击 "New Project" → "Deploy from GitHub repo"
4. 选择 `iammadma-cryinggun/BTC15M`
5. Railway 会自动检测 Python 项目
6. 配置环境变量：
   ```
   PRIVATE_KEY=你的私钥
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=你的Token
   TELEGRAM_CHAT_ID=你的ChatID
   ```
7. 点击 "Deploy"

### 到 Render 部署

1. 访问 https://render.com
2. 点击 "New" → "Web Service"
3. 连接GitHub账号
4. 选择 `iammadma-cryinggun/BTC15M`
5. 配置：
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
6. 添加环境变量
7. 点击 "Deploy Web Service"

## 🔍 验证地区支持

部署后，查看日志中是否仍有 403 错误：
- ✅ 如果没有 403 → 地区OK，可以交易
- ❌ 如果仍有 403 → 需要尝试其他平台

## 💡 备选方案：本地运行 + 云端监控

如果所有云平台都被限制，可以：
1. **本地运行交易机器人**（您的本地已安装py-clob-client）
2. **云端只运行监控和信号生成**
3. **Telegram通知信号到手机**
4. **手动执行交易**

## 📞 联系 Polymarket

如果需要解锁您的地区：
- 邮件：support@polymarket.com
- 说明您的用途和需求
- 可能需要KYC认证

## 总结

**当前状态**：
- ✅ 程序完全正常
- ✅ 信号生成正常
- ❌ Zeabur地区被封锁

**推荐行动**：
1. 尝试 Railway 或 Render（美国服务器）
2. 或本地运行 + 手动交易
