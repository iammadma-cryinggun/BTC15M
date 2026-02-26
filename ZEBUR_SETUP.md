# Zeabur 持久化存储配置指南

## 📦 问题说明

Zeabur 默认容器重启后数据会丢失。需要配置持久化卷（Volume）来保存数据库：
- `btc_15min_auto_trades.db` - 交易数据库
- `btc_15min_predictionsv2.db` - 学习系统数据库

## 🔧 配置步骤

### 方法1: 通过 Zeabur 控制台（推荐）

1. 登录 Zeabur 控制台
2. 找到你的服务（BTC 15min）
3. 进入服务设置
4. 找到 **"卷" (Volumes)** 或 **"存储" (Storage)** 选项
5. 添加卷：
   - **容器路径**: `/app/data`
   - **类型**: 持久化卷（Persist Volume）
6. 保存并重启服务

### 方法2: 通过配置文件（如果支持）

在 `zeabur.yaml` 或服务配置中添加：

```yaml
volumes:
  - path: /app/data
    type: volume
```

## ✅ 验证持久化是否生效

重启服务后，在日志中搜索：

```
mkdir -p /app/data
```

如果数据库路径指向 `/app/data/`，说明配置成功。

## 📊 数据库位置

| 数据库 | 路径 | 说明 |
|--------|------|------|
| btc_15min_auto_trades.db | /app/data/btc_15min_auto_trades.db | 交易数据库 |
| btc_15min_predictionsv2.db | /app/data/btc_15min_predictionsv2.db | 学习系统数据库 |

## 🔄 迁移现有数据

如果已有数据在 `/app` 目录，需要迁移：

1. 进入 Zeabur 终端
2. 执行：
```bash
cd /app
cp btc_15min_auto_trades.db /app/data/ 2>/dev/null || true
cp btc_15min_predictionsv2.db /app/data/ 2>/dev/null || true
ls -lh /app/data/
```

## 💡 提示

- 持久化卷会在服务删除后仍然保留数据
- 重新部署代码不会影响 `/app/data` 中的数据
- 建议定期备份数据库文件到本地
