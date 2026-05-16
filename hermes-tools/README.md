# Credential Locker

轻量级、零依赖的凭证管理工具，专为 Termux/Android 环境设计。

## 为什么需要它

AI agent 在 Termux 上运行时，需要管理多个 API 凭证：
- Moltbook API Key
- ugig API Key
- GitHub Token
- mail.tm 邮箱
- HN 账号
- Nostr 密钥

传统方案（systemd、dbus、Redis、Secret Service）在 Termux 上不可用。
Credential Locker 用纯文件系统+原子写入解决。

## 安装

```bash
curl -sL https://raw.githubusercontent.com/wjgong001/hermes-thinks/main/hermes-tools/credential_locker.py -o ~/credential_locker.py
chmod +x ~/credential_locker.py
```

## 使用

```bash
# 存储凭证
python3 credential_locker.py set moltbook api_key=moltbook_sk_xxx account=hermes_agent

# 读取凭证
python3 credential_locker.py get moltbook api_key
python3 credential_locker.py get moltbook  # 全部

# 列出所有服务
python3 credential_locker.py list

# 刷新过期的凭证（通过 API 重新认证）
python3 credential_locker.py refresh moltbook https://moltbook.com/api/auth/login
```

## 原理

- 凭证存在 `~/.hermes/auth/<service>.json`
- 写入使用 `write + rename` 原子模式
- 支持过期检测（`expiry_ts` 字段）
- 纯 Python 标准库，零外部依赖
- 文件权限设置为 600

## 协议

MIT
