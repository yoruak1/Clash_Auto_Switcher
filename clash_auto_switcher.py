import yaml
import random
import time
import os
import sys
import argparse
import requests
from datetime import datetime
from colorama import init, Fore, Back, Style

# 初始化colorama
init(autoreset=True)

# 颜色
class Colors:
    TITLE = Fore.MAGENTA + Style.BRIGHT
    INFO = Fore.CYAN
    SUCCESS = Fore.GREEN + Style.BRIGHT
    WARNING = Fore.YELLOW + Style.DIM
    ERROR = Fore.RED + Style.BRIGHT
    HIGHLIGHT = Fore.RED  + Style.BRIGHT
    NODE = Fore.LIGHTCYAN_EX
    GROUP = Fore.LIGHTMAGENTA_EX + Style.BRIGHT
    TIME = Fore.LIGHTGREEN_EX
    WAITING = Fore.BLUE + Style.BRIGHT
    ASCII_ART = Fore.LIGHTBLUE_EX + Style.BRIGHT

# 标题
def print_ascii_art():
    ascii_art = """
  ___ _         _        _       _         ___        _ _      _
 / __| |__ _ __| |_     /_\ _  _| |_ ___  / __|_ __ _(_) |_ __| |_  ___ _ _ 
| (__| / _` (_-< ' \   / _ \ || |  _/ _ \ \__ \ V  V / |  _/ _| ' \/ -_) '_|
 \___|_\__,_/__/_||_|_/_/ \_\_,_|\__\___/_|___/\_/\_/|_|\__\__|_||_\___|_|  
                   |___|               |___|
    """
    print(f"{Colors.ASCII_ART}{ascii_art}{Style.RESET_ALL}")
    print(f"{Colors.INFO}Clash for Windows 代理节点自动切换器 v1.0{Style.RESET_ALL}")
    print(f"{Colors.INFO}作者：yoruaki{Style.RESET_ALL}")
    print(f"{Colors.INFO}github：https://github.com/yoruak1{Style.RESET_ALL}")
    print(f"{Colors.INFO}公众号：夜秋的小屋{Style.RESET_ALL}")
    print()

def print_title(message):
    border = "=" * (len(message) + 13)
    print(f"{Colors.TITLE}{border}")
    print(f"{Colors.TITLE}= {message} =")
    print(f"{Colors.TITLE}{border}")

def print_info(message):
    print(f"{Colors.INFO}{message}{Style.RESET_ALL}")

def print_success(message):
    print(f"{Colors.SUCCESS}✓ {message}{Style.RESET_ALL}")

def print_warning(message):
    print(f"{Colors.WARNING}⚠ {message}{Style.RESET_ALL}")

def print_error(message):
    print(f"{Colors.ERROR}✗ {message}{Style.RESET_ALL}")

def print_highlight(message):
    print(f"{Colors.HIGHLIGHT}{message}{Style.RESET_ALL}")

def colorize_node(node_name):
    return f"{Colors.NODE}{node_name}{Style.RESET_ALL}"

def colorize_group(group_name):
    return f"{Colors.GROUP}{group_name}{Style.RESET_ALL}"

def colorize_time(time_str):
    return f"{Colors.TIME}{time_str}{Style.RESET_ALL}"

def load_config(config_path):
    try:
        with open(config_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
            controller = config.get('external-controller', '127.0.0.1:9090')
            secret = config.get('secret', '')
            
            if not controller:
                print_warning("配置文件中未找到external-controller，将使用默认值: 127.0.0.1:9090")
                controller = '127.0.0.1:9090'
            
            return {
                'config': config,
                'controller': controller,
                'secret': secret
            }
    except Exception as e:
        print_error(f"加载配置文件时出错: {e}")
        sys.exit(1)

def get_proxies_and_groups(controller_address, secret):
    try:
        headers = {"Authorization": f"Bearer {secret}"}
        if not controller_address.startswith("http://") and not controller_address.startswith("https://"):
            controller_address = f"http://{controller_address}"
        
        groups_url = f"{controller_address}/proxies"
        groups_resp = requests.get(groups_url, headers=headers)
        
        if groups_resp.status_code != 200:
            print_error(f"无法获取代理组信息，API返回: {groups_resp.status_code}")
            return [], []
        
        api_groups = groups_resp.json().get('proxies', {})
        proxy_names = set()
        available_groups = []
        
        for group_name, group_info in api_groups.items():
            if group_info.get('type') in ['Selector', 'URLTest', 'Fallback']:
                available_groups.append({
                    'name': group_name,
                    'type': group_info.get('type'),
                    'now': group_info.get('now'),
                    'all': group_info.get('all', [])
                })
                proxy_names.update(group_info.get('all', []))
        
        print_success(f"从API检测到 {len(available_groups)} 个可选择的代理组和 {len(proxy_names)} 个代理")
        return list(proxy_names), available_groups
    
    except Exception as e:
        print_error(f"从API获取代理信息时出错: {e}")
        return [], []

def switch_proxy(interval, config_path, secret, controller_address, blacklist=None):
    if blacklist is None:
        blacklist = ["最新网址", "剩余流量", "距离下次重置", "套餐到期", "自动选择", "故障转移", "DIRECT", "REJECT"]
    print_highlight(f"已设置黑名单节点: {', '.join(blacklist)}")
    
    api_url = controller_address
    if not api_url.startswith("http://") and not api_url.startswith("https://"):
        api_url = f"http://{api_url}"
    
    try:
        while True:
            proxy_names, available_groups = get_proxies_and_groups(api_url, secret)
            
            if not available_groups:
                print_warning("未找到任何可用的代理组。请确保Clash for Windows正在运行。")
                time.sleep(interval)
                continue
            
            switched = False
            
            for group in available_groups:
                if group['type'] == 'Selector' or group['name'] == 'GLOBAL':
                    group_proxies = group.get('all', [])
                    filtered_proxies = []
                    
                    for proxy in group_proxies:
                        is_blacklisted = False
                        for black_item in blacklist:
                            if black_item and black_item in proxy:
                                is_blacklisted = True
                                break
                        if not is_blacklisted:
                            filtered_proxies.append(proxy)
                    
                    if filtered_proxies:
                        selected = random.choice(filtered_proxies)
                        old_selection = group.get('now', '无')
                        
                        if selected == old_selection:
                            continue
                        
                        try:
                            headers = {"Authorization": f"Bearer {secret}"}
                            encoded_group_name = requests.utils.quote(group['name'])
                            selector_url = f"{api_url}/proxies/{encoded_group_name}"
                            
                            response = requests.put(
                                selector_url, 
                                json={"name": selected}, 
                                headers=headers
                            )
                            
                            if response.status_code in [200, 204]:
                                timestamp = colorize_time(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
                                group_name = colorize_group(group['name'])
                                old_node = colorize_node(old_selection)
                                new_node = colorize_node(selected)
                                print_success(f"{timestamp} 已将组 {group_name} 从 {old_node} 切换到 {new_node}")
                                switched = True
                            else:
                                print_warning(f"跳过组 {colorize_group(group['name'])} - API返回错误: {response.status_code}")
                        except Exception as e:
                            print_error(f"通过API修改代理选择失败: {e}")
                    else:
                        print_warning(f"警告: 组 {colorize_group(group['name'])} 没有可用的代理节点（排除黑名单后）")
            
            if not switched:
                print_warning("警告: 未能切换任何代理组。请检查您的代理组配置。")
            
            print_info(f"{Colors.WAITING}等待 {interval} 秒后进行下一次切换...{Style.RESET_ALL}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print_highlight("\n停止代理切换...")

def main():
    # 显示ASCII艺术字
    print_ascii_art()
    
    parser = argparse.ArgumentParser(description='Clash for Windows 代理节点自动切换器')
    parser.add_argument('--config', '-c', help='Clash配置文件的路径（自动从中读取控制器地址和密钥）')
    parser.add_argument('--interval', '-i', type=int, default=60, help='代理切换之间的间隔（默认：60秒）')
    parser.add_argument('--secret', '-s', help='手动输入Clash API 密钥')
    parser.add_argument('--controller', '-a', default='127.0.0.1:9090', help='手动输入Clash控制器地址')
    parser.add_argument('--blacklist', '-b', nargs='+', 
                       default=["最新网址", "剩余流量", "距离下次重置", "套餐到期", "自动选择", "故障转移", "DIRECT", "REJECT"], 
                       help='要避开的代理节点名称列表（默认：最新网址 剩余流量 距离下次重置 套餐到期 自动选择 故障转移 DIRECT REJECT）')
    
    args = parser.parse_args()
    
    # 获取控制器地址和密钥
    controller = args.controller
    secret = args.secret
    
    # 如果提供了配置文件，则从配置文件中读取控制器地址和密钥
    if args.config:
        config_data = load_config(args.config)
        controller = config_data['controller']
        secret = config_data['secret']
        print_info(f"从配置文件加载控制器地址: {colorize_highlight(controller)}")
        if secret:
            print_info("从配置文件加载API密钥")
        else:
            print_warning("配置文件中未找到API密钥")
    else:
        print_info(f"使用命令行参数控制器地址: {colorize_highlight(controller)}")
        if secret:
            print_info("使用命令行参数API密钥")
        else:
            print_warning("未提供API密钥")
    
    # 打印启动标题
    print_title("Clash for Windows 代理节点自动切换器")
    
    # 测试控制器连接
    test_headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    controller_url = f"http://{controller}"
    try:
        print_info(f"正在测试与控制器 {colorize_highlight(controller_url)} 的连接...")
        test_response = requests.get(f"{controller_url}/version", headers=test_headers)
        version = test_response.json().get('version', '未知')
        print_success(f"控制器连接测试成功! Clash 版本: {colorize_highlight(version)}")
    except Exception as e:
        print_error(f"警告: 无法连接到控制器 {controller_url}: {e}")
        print_warning("请确保 Clash for Windows 正在运行且控制器地址正确。")
        choice = input(f"{Colors.HIGHLIGHT}是否仍要继续? (y/n): {Style.RESET_ALL}")
        if choice.lower() != 'y':
            sys.exit(1)
    
    print_success(f"正在启动 Clash for Windows 代理 IP 切换器，间隔时间为 {colorize_highlight(str(args.interval))} 秒")
    switch_proxy(args.interval, args.config, secret, controller, args.blacklist)

def colorize_highlight(text):
    return f"{Fore.YELLOW + Style.BRIGHT}{text}{Style.RESET_ALL}"

if __name__ == "__main__":
    main() 