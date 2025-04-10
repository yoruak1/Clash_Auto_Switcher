# Clash_Auto_Switcher(Clash for Windows 代理节点自动切换器)

一个用于 Clash for Windows 的自动代理节点切换工具，可以按指定时间间隔自动切换代理节点，支持黑名单过滤。

<img src=".\assets\1_1.png" style="zoom: 67%;" />

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
  -b, --blacklist   要避开的代理节点名称列表（默认：最新 流量 重置 自动选择 故障转移 DIRECT REJECT）
```

### 配置文件示例

<img src=".\assets\2.png" style="zoom:50%;" />

<img src=".\assets\3.png" style="zoom:67%;" />

在config.yaml中需要包含以下信息：

```yaml
# 控制器地址
external-controller: your_external-controller

# API 密钥
secret: your_secret
```

### 黑名单设置

默认的黑名单包含以下节点名称：最新，流量，重置，自动选择，故障转移，DIRECT，REJECT

可以通过 `-b` 参数自定义黑名单：
```bash
python clash_auto_switcher.py -c config.yaml -b "测试节点" "过期节点" ...
```

## ❓ 注意事项

1. 确保 Clash for Windows 正在运行
2. 确保配置文件中的控制器地址和密钥正确

## ⚠️免责声明 

1. 本工具仅用于合法的网络安全研究及技术学习，使用者应确保在法律允许的范围内使用本工具，任何利用本工具进行的非法活动、网络攻击或侵权行为而导致的任何直接、间接、偶然、特殊、惩戒性或后果性损害，均由使用者自行承担全部法律责任，与开发者无关，本工具的开发者不承担任何责任。
2. 本工具不附带任何形式的明示或暗示保证，包括但不限于对适销性、特定用途适用性、准确性、完整性、权利归属及非侵权性的保证，本工具的开发者不对该工具的可靠性、可用性或满足您特定需求的适用性作出任何陈述或担保。
3. 使用者使用本工具可能涉及访问和操作各类计算机系统及网络资源。此类行为可能受限于并可能违反特定地区、国家或国际的法律、法规或政策。使用者必须自行负责确保其使用本工具的行为是合法的、合乎道德规范的，并且已获得所有必要的授权。使用者将独立承担因违反任何适用法律、法规、政策或进行任何未经授权操作所引发的全部及排他的法律责任。本工具的开发者对于使用者任何非法、不道德或未经授权的使用行为及其所导致的一切法律后果，明确声明不承担任何责任。
4. 一旦您开始使用本工具，即表示您已阅读、理解并同意接受本免责声明所有条款的约束。
