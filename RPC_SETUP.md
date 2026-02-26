# Polygon RPC 节点配置指南

## 🚀 性能优化：双节点容灾架构

系统现在支持**双节点自动故障转移**，大幅提升余额查询速度和可靠性。

---

## 📋 配置步骤

### 1. 获取专属 RPC 密钥

#### Alchemy（推荐 - 主力节点）
1. 访问：https://www.alchemy.com/
2. 注册/登录账号
3. 创建新项目：`Polymarket Trading`
4. 选择网络：`Polygon`
5. 复制你的 HTTP API Key
6. 格式类似：`lvMbAszdqd8vyswgr0hMu...`

#### QuickNode（备用节点）
1. 访问：https://www.quicknode.com/
2. 注册/登录账号
3. 创建新端点：`Polymarket Trading`
4. 选择网络：`Polygon`
5. 复制你的端点 URL
6. 格式类似：`bb4ccab51795871b1d38fe9683b9dd3dda4097e7`

---

### 2. 配置环境变量

#### 方法A：Zeabur 控制台（推荐）

1. 登录 Zeabur 控制台
2. 找到你的服务（BTC 15min）
3. 进入 **"环境变量" (Environment Variables)**
4. 添加以下变量：

```bash
# Alchemy Polygon 主网密钥
ALCHEMY_POLYGON_KEY=your_alchemy_key_here

# QuickNode Polygon 密钥（只需要最后那部分）
QUICKNODE_POLYGON_KEY=your_quicknode_key_here
```

5. 保存并重启服务

#### 方法B：本地开发

创建 `.env` 文件（已在 .gitignore 中）：

```bash
ALCHEMY_POLYGON_KEY=your_alchemy_key_here
QUICKNODE_POLYGON_KEY=your_quicknode_key_here
```

---

## ✅ 验证配置

部署后查看日志，应该看到：

```
[RPC] ✅ Alchemy节点已配置
[RPC] ✅ QuickNode节点已配置
[RPC] ✅ 公共备用节点已配置（保底）
[RPC] 🚀 RPC节点池大小: 3 (双节点容灾架构)
```

查询余额时会看到：

```
[BALANCE] Fetching REAL balance from Polygon...
[RPC] ✅ 使用节点: polygon-mainnet
[OK] USDC.e balance: 100.00
[OK] POL balance: 0.5000
```

---

## 🔒 安全提醒

### ⚠️ 绝对不要：
- ❌ 将密钥提交到 GitHub
- ❌ 在微信群/论坛分享密钥
- ❌ 写在代码注释里

### ✅ 应该：
- ✅ 使用环境变量存储
- ✅ 定期轮换密钥
- ✅ 监控 API 使用量

---

## 📊 性能对比

| 节点类型 | 响应时间 | 可靠性 | 成本 |
|---------|---------|--------|------|
| 公共节点 | 300ms+ | 低 | 免费 |
| Alchemy | 30-50ms | 高 | 免费层够用 |
| QuickNode | 30-50ms | 高 | 免费层够用 |

**预期提升：**
- 余额查询速度：**5-10倍**
- 超时率：**降低90%+**
- 止损响应：**更可靠**

---

## 🛠️ 故障转移逻辑

```
1. 尝试 Alchemy (主力节点)
   ├─ 成功 → 返回结果 ✅
   └─ 失败 → 继续下一步

2. 尝试 QuickNode (备用节点)
   ├─ 成功 → 返回结果 ✅
   └─ 失败 → 继续下一步

3. 尝试公共节点 (保底方案)
   ├─ 成功 → 返回结果 ⚠️ (慢)
   └─ 失败 → 返回 None ❌

4. 所有节点都失败
   └─ 报错，停止交易 🚨
```

---

## 💡 常见问题

### Q: 只配置一个节点可以吗？
A: 可以，但建议至少配置两个。双节点容灾能大幅提升可靠性。

### Q: 免费层够用吗？
A: 对于个人交易机器人，Alchemy 和 QuickNode 的免费层完全够用。

### Q: 如何监控 API 使用量？
A: 登录 Alchemy/QuickNode 控制台查看使用统计。

---

## 📝 更新日志

### 2025-02-26
- 实施双节点容灾架构
- 支持自动故障转移
- 移除公共节点作为主力
- 添加环境变量配置
