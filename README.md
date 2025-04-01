# Clash_Auto_Switcher(Clash for Windows 代理节点自动切换器)

一个用于 Clash for Windows 的自动代理节点切换工具，可以按指定时间间隔自动切换代理节点，支持黑名单过滤。

<img src=".\demo\1_1.png" style="zoom: 67%;" />

## ✨ 功能特性

- 自动定时切换代理节点
- 支持从 Clash 配置文件自动读取控制台与密钥
- 支持代理节点黑名单

## 📋 安装要求

- Python 3.6或更高版本
- Clash for Windows

## 🚀 安装步骤

1. 克隆仓库或下载仓库：
2. 安装依赖：
```bash
pip install -r requirements.txt
```

## 🔧 使用方法

### 基本用法

1. 使用配置文件（推荐）：
```bash
python clash_auto_switcher.py -c config.yaml
```

2. 手动指定参数：
```bash
python clash_auto_switcher.py -a your_external-controller -s your_secret -i 60
```

### 命令行参数

```
参数说明：
  -c, --config      Clash配置文件的路径（自动从中读取控制器地址和密钥）
  -i, --interval    代理切换之间的间隔（默认：60秒）
  -s, --secret      手动输入Clash API 密钥
  -a, --controller  手动输入Clash控制器地址
  -b, --blacklist   要避开的代理节点名称列表
```

### 配置文件示例

<img src=".\demo\2.png" style="zoom:50%;" />

![](.\demo\3.png)

在config.yaml中需要包含以下信息：

```yaml
# 控制器地址
external-controller: your_external-controller

# API 密钥
secret: your_secret
```

### 黑名单设置

默认的黑名单包含以下节点名称：最新网址，剩余流量，距离下次重置，套餐到期，自动选择，故障转移，DIRECT，REJECT

可以通过 `-b` 参数自定义黑名单：
```bash
python clash_auto_switcher.py -c config.yaml -b "测试节点" "过期节点" ...
```

## ⚠️ 注意事项

1. 确保 Clash for Windows 正在运行
2. 确保配置文件中的控制器地址和密钥正确
