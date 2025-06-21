import sys
import time
import os
import configparser
import yaml
import random
import math
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                           QLabel, QLineEdit, QSpinBox, QPushButton, QFileDialog, 
                           QTextEdit, QGroupBox, QCheckBox, QListWidget, QInputDialog,
                           QRadioButton, QButtonGroup, QFrame, QDoubleSpinBox, QStatusBar,
                           QSizePolicy, QDialog)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QPoint, QSize
from PyQt6.QtGui import QFont, QTextCursor, QColor, QIcon, QPalette, QPixmap, QPainter, QPen, QBrush, QLinearGradient
from PyQt6.QtWidgets import QGraphicsDropShadowEffect

import requests
from datetime import datetime

def get_application_path():
    if hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, relative_path)

def load_config(config_path):
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        controller = config.get('external-controller', '127.0.0.1:9090')
        secret = config.get('secret', '')
        
        return {
            'controller': controller,
            'secret': secret
        }
    except Exception as e:
        print(f"加载配置文件时出错: {e}")
        return {
            'controller': '127.0.0.1:9090',
            'secret': ''
        }

def get_proxies_and_groups(api_url, secret):
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    
    try:
        proxies_response = requests.get(f"{api_url}/proxies", headers=headers)
        proxies_data = proxies_response.json()
        
        if proxies_response.status_code != 200:
            print(f"获取代理列表失败: HTTP {proxies_response.status_code}")
            return [], []
        
        proxy_names = []
        for name, details in proxies_data.get('proxies', {}).items():
            if details.get('type') == 'Proxy':
                proxy_names.append(name)
        
        available_groups = []
        for name, details in proxies_data.get('proxies', {}).items():
            if details.get('type') in ['Selector', 'URLTest', 'Fallback']:
                group_info = {
                    'name': name,
                    'type': details.get('type'),
                    'now': details.get('now', ''),
                    'all': details.get('all', [])
                }
                available_groups.append(group_info)
        
        return proxy_names, available_groups
    except Exception as e:
        print(f"获取代理信息时出错: {e}")
        return [], []


class ConnectionMonitorThread(QThread):
    connection_detected = pyqtSignal()
    log_signal = pyqtSignal(str, str)
    
    def __init__(self, controller_url, secret, interval=1, connection_filter_mode='blacklist', connection_list=None):
        super().__init__()
        self.controller_url = controller_url
        if not self.controller_url.startswith('http'):
            self.controller_url = f'http://{self.controller_url}'
        self.secret = secret
        self.interval = interval
        self.running = True
        self.previous_connection_ids = set()
        self.connection_filter_mode = connection_filter_mode
        self.connection_list = connection_list or []
        
        import urllib.parse
        parsed_url = urllib.parse.urlparse(self.controller_url)
        self.controller_host = parsed_url.hostname or "127.0.0.1"
        self.controller_port = str(parsed_url.port or 9090)
    
    def run(self):
        self.log_signal.emit(f"开始监控", "info")
        if self.connection_list:
            mode_text = "黑名单" if self.connection_filter_mode == 'blacklist' else "白名单"
            self.log_signal.emit(f"已设置访问目标{mode_text}: {', '.join(self.connection_list)}", "info")
        
        headers = {"Authorization": f"Bearer {self.secret}"} if self.secret else {}
        
        try:
            while self.running:
                try:
                    response = requests.get(f"{self.controller_url}/connections", headers=headers)
                    if response.status_code != 200:
                        self.log_signal.emit(f"获取连接信息失败: HTTP {response.status_code}", "error")
                        time.sleep(self.interval)
                        continue
                    
                    all_current_conns = response.json().get('connections', [])
                    current_connection_ids = {conn['id'] for conn in all_current_conns}
                    
                    new_connection_ids = current_connection_ids - self.previous_connection_ids
                    
                    if new_connection_ids:
                        new_conns = [conn for conn in all_current_conns if conn['id'] in new_connection_ids]
                        
                        valid_new_conns_count = 0
                        for conn in new_conns:
                            if self.is_controller_request(conn):
                                continue

                            is_in_list = self.is_target_in_list(conn)
                            should_count = False

                            if self.connection_filter_mode == 'blacklist':
                                if not is_in_list:
                                    should_count = True
                            elif self.connection_filter_mode == 'whitelist':
                                if self.connection_list and is_in_list:
                                    should_count = True
                            
                            if should_count:
                                host = conn.get('metadata', {}).get('host', 'unknown')
                                destination = conn.get('metadata', {}).get('destinationIP', 'unknown')
                                self.log_signal.emit(f"检测到有效新连接: {host} -> {destination}", "info")
                                self.connection_detected.emit()
                                valid_new_conns_count += 1

                        if valid_new_conns_count > 0:
                            self.log_signal.emit(f"本轮检测到 {valid_new_conns_count} 个有效新连接", "highlight")

                    self.previous_connection_ids = current_connection_ids
                    
                except Exception as e:
                    self.log_signal.emit(f"监控连接时出错: {e}", "error")
                
                time.sleep(self.interval)
                
        except Exception as e:
            self.log_signal.emit(f"连接监控异常: {e}", "error")
        finally:
            pass
    
    def is_controller_request(self, connection):
        try:
            metadata = connection.get('metadata', {})
            dest_ip = metadata.get('destinationIP', '')
            dest_port = metadata.get('destinationPort', '')
            
            is_to_controller = (
                (dest_ip in ['127.0.0.1', 'localhost', self.controller_host]) and 
                (str(dest_port) == str(self.controller_port))
            )
            
            host = metadata.get('host', '')
            if is_to_controller or host == self.controller_host:
                return True
                
            return False
        except Exception:
            return False
            
    def is_target_in_list(self, connection):
        try:
            metadata = connection.get('metadata', {})
            host = metadata.get('host', '')
            dest_ip = metadata.get('destinationIP', '')
            
            for item in self.connection_list:
                if not item:
                    continue
                if item in host or item in dest_ip:
                    return True
            
            return False
        except Exception:
            return False
    
    def stop(self):
        self.running = False

class ProxySwitcherThread(QThread):
    log_signal = pyqtSignal(str, str)
    status_update = pyqtSignal(bool)
    used_proxy_update = pyqtSignal(str, str, bool)
    
    def __init__(self, interval, config_path, secret, controller_address, blacklist=None, switch_mode="time", switch_logic="random"):
        super().__init__()
        self.interval = interval
        self.config_path = config_path
        self.secret = secret
        self.controller_address = controller_address
        self.blacklist = blacklist or ["最新", "流量", "套餐", "重置", "自动选择", "故障转移", "DIRECT", "REJECT"]
        self.running = True
        self.force_switch = False
        self.switch_mode = switch_mode
        self.switch_logic = switch_logic
        
        self.used_proxies = set()
        self.available_proxies_cache = {}
    
    def switch_proxy_now(self):
        self.force_switch = True
    
    def run(self):
        self.log_signal.emit(f"已设置黑名单节点: {', '.join(self.blacklist)}", "highlight")
        self.log_signal.emit(f"切换模式: {('定时切换' if self.switch_mode == 'time' else '连接次数切换')}", "highlight")
        self.log_signal.emit(f"切换逻辑: {('随机切换' if self.switch_logic == 'random' else '逻辑切换')}", "highlight")
        
        api_url = self.controller_address
        if not api_url.startswith("http://") and not api_url.startswith("https://"):
            api_url = f"http://{api_url}"
        
        try:
            last_switch_time = time.time()
            
            if self.switch_mode == "connection":
                self.log_signal.emit(f"等待连接次数达到阈值后进行切换...", "info")
            
            while self.running:
                self.status_update.emit(True)
                
                current_time = time.time()
                time_elapsed = current_time - last_switch_time
                
                should_switch = False
                
                if self.switch_mode == "time" and time_elapsed >= self.interval:
                    should_switch = True
                elif self.switch_mode == "connection" and self.force_switch:
                    should_switch = True
                
                if should_switch:
                    if self.force_switch:
                        self.force_switch = False
                
                    proxy_names, available_groups = get_proxies_and_groups(api_url, self.secret)
                    
                    if not available_groups:
                        self.log_signal.emit("未找到任何可用的代理组。请确保Clash for Windows正在运行。", "warning")
                        time.sleep(5)
                        continue
                    
                    switched = False
                    
                    for group in available_groups:
                        if group['type'] == 'Selector' or group['name'] == 'GLOBAL':
                            group_name = group['name']
                            group_proxies = group.get('all', [])
                            filtered_proxies = []
                            
                            for proxy in group_proxies:
                                is_blacklisted = False
                                for black_item in self.blacklist:
                                    if black_item and black_item in proxy:
                                        is_blacklisted = True
                                        break
                                if not is_blacklisted:
                                    filtered_proxies.append(proxy)
                            
                            if filtered_proxies:
                                import random
                                
                                old_selection = group.get('now', '无')
                                selected = None
                                
                                if self.switch_logic == "random":
                                    selected = random.choice(filtered_proxies)
                                else:
                                    if group_name not in self.available_proxies_cache:
                                        self.available_proxies_cache[group_name] = set()
                                    
                                    if not self.available_proxies_cache[group_name]:
                                        self.available_proxies_cache[group_name] = set(filtered_proxies)
                                        self.log_signal.emit(f"组 {group_name} 的代理池已重置，包含 {len(filtered_proxies)} 个代理", "info")
                                        self.used_proxy_update.emit(group_name, "", True)
                                    
                                    if old_selection in self.available_proxies_cache[group_name]:
                                        self.available_proxies_cache[group_name].remove(old_selection)
                                        
                                    if not self.available_proxies_cache[group_name]:
                                        self.available_proxies_cache[group_name] = set(filtered_proxies)
                                        self.log_signal.emit(f"组 {group_name} 的所有代理已轮换一遍，重新开始", "info")
                                        self.used_proxy_update.emit(group_name, "", True)
                                    
                                    available_list = list(self.available_proxies_cache[group_name])
                                    selected = random.choice(available_list)
                                    
                                    if selected in self.available_proxies_cache[group_name]:
                                        self.available_proxies_cache[group_name].remove(selected)
                                
                                if selected == old_selection:
                                    continue
                                
                                try:
                                    headers = {"Authorization": f"Bearer {self.secret}"}
                                    encoded_group_name = requests.utils.quote(group['name'])
                                    selector_url = f"{api_url}/proxies/{encoded_group_name}"
                                    
                                    response = requests.put(
                                        selector_url, 
                                        json={"name": selected}, 
                                        headers=headers
                                    )
                                    
                                    if response.status_code in [200, 204]:
                                        timestamp = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
                                        
                                        extra_info = ""
                                        if self.switch_logic == "sequential":
                                            remaining = len(self.available_proxies_cache[group_name])
                                            total = len(filtered_proxies)
                                            extra_info = f"(剩余可用代理: {remaining}/{total})"
                                            
                                            self.used_proxy_update.emit(group_name, selected, False)
                                            
                                        self.log_signal.emit(
                                            f"{timestamp} 已将组 {group['name']} 从 {old_selection} 切换到 {selected} {extra_info}",
                                            "success"
                                        )
                                        switched = True
                                    else:
                                        self.log_signal.emit(f"跳过组 {group['name']} - API返回错误: {response.status_code}", "warning")
                                except Exception as e:
                                    self.log_signal.emit(f"通过API修改代理选择失败: {e}", "error")
                            else:
                                self.log_signal.emit(f"警告: 组 {group['name']} 没有可用的代理节点（排除黑名单后）", "warning")
                    
                    if not switched:
                        self.log_signal.emit("警告: 未能切换任何代理组。请检查您的代理组配置。", "warning")
                    else:
                        last_switch_time = time.time()
                    
                    if self.switch_mode == "time":
                        self.log_signal.emit(f"等待 {self.interval} 秒后进行下一次切换...", "info")
                
                sleep_time = 1 if self.switch_mode == "time" else 0.1
                time.sleep(sleep_time)
                    
        except Exception as e:
            self.log_signal.emit(f"异常: {e}", "error")
        finally:
            self.status_update.emit(False)
    
    def stop(self):
        self.running = False
        self.log_signal.emit("正在停止代理切换...", "highlight")

class Snowflake:
    def __init__(self, parent_width, parent_height):
        self.x = random.randint(0, parent_width)
        self.y = random.randint(-50, 0)
        self.size = random.randint(3, 12)
        self.speed = random.uniform(0.5, 3.0)
        self.swing = random.uniform(-1.5, 1.5)
        self.parent_width = parent_width
        self.parent_height = parent_height
        self.alpha = random.randint(220, 255)
        self.rotation = random.uniform(0, 360)
        self.rotation_speed = random.uniform(-2, 2)
        self.shape_type = random.choice([0, 1, 2])
        self.color = random.choice([
            QColor(255, 255, 255, self.alpha),
            QColor(230, 240, 255, self.alpha),
            QColor(220, 240, 255, self.alpha)
        ])
        
    def update(self):
        self.y += self.speed
        self.x += self.swing
        self.rotation += self.rotation_speed
        
        if self.y > self.parent_height:
            self.reset()
        
        if self.x < -20 or self.x > self.parent_width + 20:
            self.reset()
    
    def reset(self):
        self.x = random.randint(0, self.parent_width)
        self.y = random.randint(-50, -10)
        self.size = random.randint(3, 12)
        self.speed = random.uniform(0.5, 3.0)
        self.swing = random.uniform(-1.5, 1.5)
        self.alpha = random.randint(220, 255)
        self.color = random.choice([
            QColor(255, 255, 255, self.alpha),
            QColor(230, 240, 255, self.alpha),
            QColor(220, 240, 255, self.alpha)
        ])

class ClashAutoSwitcherGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.config = configparser.ConfigParser()
        
        self.initialization_complete = False
        self.connection_counter = 0
        
        self.switcher_thread = None
        self.monitor_thread = None
        
        self.clash_config_path = ""
        self.switch_interval = 60
        self.auto_switch_mode = "time"
        self.auto_switch_logic = "random"
        self.exclude_keywords = []
        self.current_proxy_group = "GLOBAL"
        
        self.used_proxies_by_group = {}
        

        self.base_dir = get_application_path()
        self.config_dir = os.path.join(self.base_dir, "config")
        
        if not os.path.exists(self.config_dir):
            try:
                os.makedirs(self.config_dir)
                print(f"创建配置目录: {self.config_dir}")
            except Exception as e:
                print(f"创建配置目录失败: {e}")
        
        self.config_file_path = os.path.join(self.config_dir, "config.ini")
        self.blacklist_file = os.path.join(self.config_dir, "blacklist.txt")
        self.whitelist_file = os.path.join(self.config_dir, "whitelist.txt")
        self.keywordlist_file = os.path.join(self.config_dir, "keywordlist.txt")
        
        self.ensure_icons_exist()
        
        self.log_buffer = []
        
        self.load_app_config()
        
        resource_icon_path = get_resource_path(os.path.join("icons", "clash.png"))
        
        if os.path.exists(resource_icon_path):
            self.setWindowIcon(QIcon(resource_icon_path))
        else:
            self.add_log("警告: 未找到图标文件", "warning")

        self.set_style()
        
        self.add_logo()
        
        self.initUI()
        
        self.load_lists()
        
        for log_msg, log_type in self.log_buffer:
            self.log(log_msg, log_type)
        self.log_buffer = []
        
        self.snowflakes = []
        self.snow_timer = QTimer(self)
        self.snow_timer.timeout.connect(self.update_snow)
        self.snow_timer.start(50)
        
        self.init_snowflakes(100)
    
    def ensure_icons_exist(self):
        resource_clash_icon = get_resource_path(os.path.join("icons", "clash.png"))
        resource_yoruaki_icon = get_resource_path(os.path.join("icons", "yoruaki.png"))
        
        if not os.path.exists(resource_clash_icon):
            print(f"警告: 未在资源中找到clash.png图标")
            self.add_log("警告: 未在资源中找到clash.png图标", "warning")
            
        if not os.path.exists(resource_yoruaki_icon):
            print(f"警告: 未在资源中找到yoruaki.png图标")
            self.add_log("警告: 未在资源中找到yoruaki.png图标", "warning")

    def add_logo(self):
        self.logo_frame = QFrame(self)
        self.logo_frame.setObjectName("logoFrame")
        
        logo_size = 75
        frame_size = logo_size + 10
        self.logo_frame.setFixedSize(frame_size, frame_size)
        
        self.logo_label = QLabel(self.logo_frame)
        self.logo_label.setObjectName("logoLabel")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.logo_label.move(5, 5)
        self.logo_label.setFixedSize(logo_size, logo_size)
        
        resource_logo_path = get_resource_path(os.path.join("icons", "clash.png"))
        
        if os.path.exists(resource_logo_path):
            pixmap = QPixmap(resource_logo_path)
        else:
            self.add_log("警告: 未找到图标文件，使用默认图标", "warning")
            pixmap = QPixmap(logo_size, logo_size)
            pixmap.fill(QColor(0, 0, 0, 0))
            
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            painter.setPen(QPen(QColor("#6AAFE6"), 2))
            painter.setBrush(QBrush(QColor("#6AAFE6")))
            painter.drawEllipse(2, 2, 60, 60)
            
            painter.setPen(QPen(QColor("white"), 4))
            painter.drawArc(15, 10, 34, 44, 45 * 16, 270 * 16)
            
            painter.end()
            
        pixmap = pixmap.scaled(logo_size, logo_size, 
                              Qt.AspectRatioMode.KeepAspectRatio, 
                              Qt.TransformationMode.SmoothTransformation)
        self.logo_label.setPixmap(pixmap)
        
        self.logo_frame.setStyleSheet("""
            #logoFrame {
                background: qradialgradient(
                    cx: 0.5, cy: 0.5, radius: 0.8, 
                    fx: 0.5, fy: 0.5, 
                    stop: 0 rgba(230, 243, 255, 180), 
                    stop: 0.7 rgba(230, 243, 255, 120), 
                    stop: 1 rgba(230, 243, 255, 0)
                );
                border-radius: """ + str(frame_size//2) + """px;
            }
            #logoLabel {
                background-color: transparent;
                opacity: 0.9;
            }
        """)
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(106, 175, 230, 100))
        shadow.setOffset(0, 0)
        self.logo_label.setGraphicsEffect(shadow)
        
        self.logo_frame.setParent(self)
        
        self.position_logo()
    
    def on_resize(self, event):
        self.position_logo()
        super().resizeEvent(event)
    
    def position_logo(self):
        margin_right = 0
        margin_top = 5
        self.logo_frame.move(self.width() - self.logo_frame.width() - margin_right, margin_top)
        self.logo_frame.raise_()
    
    def set_style(self):
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor("#E6F3FF"))
        gradient.setColorAt(1, QColor("#D9EAFF"))
        
        palette = self.palette()
        palette.setBrush(QPalette.ColorRole.Window, QBrush(gradient))
        self.setPalette(palette)
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #E6F3FF;
            }
            QWidget {
                background-color: #E6F3FF;
                color: #333333;
                font-family: '微软雅黑', Arial, sans-serif;
                font-size: 10pt;
            }
            QLabel {
                color: #333333;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
            QPushButton {
                background-color: #6AAFE6;
                color: white;
                border-radius: 5px;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8BC4F2;
            }
            QPushButton:pressed {
                background-color: #4A8BC2;
            }
            QPushButton:disabled {
                background-color: #D3D3D3;
                color: #A9A9A9;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                border: 1px solid #6AAFE6;
                border-radius: 4px;
                padding: 5px;
                background-color: #FFFFFF;
            }
            QTextEdit {
                border: 1px solid #6AAFE6;
                border-radius: 4px;
                padding: 5px;
                background-color: #FFFFFF;
                color: #333333;
            }
            QListWidget {
                border: 1px solid #6AAFE6;
                border-radius: 4px;
                padding: 5px;
                background-color: #FFFFFF;
            }
            QRadioButton {
                spacing: 5px;
            }
            QRadioButton::indicator {
                width: 15px;
                height: 15px;
            }
            QRadioButton::indicator:unchecked {
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                background-color: #FFFFFF;
            }
            QRadioButton::indicator:checked {
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                background-color: #8BC4F2;
            }
            QCheckBox {
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                background-color: #FFFFFF;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                background-color: #8BC4F2;
            }
        """)

    def get_button_style(self):
        return """
            QPushButton {
                background-color: #6AAFE6;
                color: white;
                border-radius: 5px;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8BC4F2;
            }
            QPushButton:pressed {
                background-color: #4A8BC2;
            }
            QPushButton:disabled {
                background-color: #D3D3D3;
                color: #A9A9A9;
            }
        """

    def log(self, message, message_type="info"):
        color_map = {
            "info": "#3498db",
            "success": "#2ecc71",
            "warning": "#f39c12",
            "error": "#e74c3c",
            "highlight": "#6AAFE6",
            "node": "#1abc9c",
            "group": "#3B7DB9",
            "time": "#27ae60",
            "waiting": "#2980b9",
            "ascii_art": "#6AAFE6"
        }
        
        color = color_map.get(message_type, "#333333")
        
        self.log_text.setTextColor(QColor(color))
        
        if message_type != "ascii_art":
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.append(f"[{timestamp}] {message}")
        else:
            self.log_text.append(message)
        
        if hasattr(self, 'initialization_complete') and self.initialization_complete:
            self.log_text.moveCursor(QTextCursor.MoveOperation.End)
            self.log_text.ensureCursorVisible()
            
    def load_app_config(self):
        self.config.add_section('Clash')
        
        self.clash_config_path = ""
        self.controller_address = "127.0.0.1:9090"
        self.api_secret = ""
        
        if os.path.exists(self.config_file_path):
            try:
                self.config.read(self.config_file_path, encoding='utf-8')
                if 'Clash' in self.config:
                    self.clash_config_path = self.config.get('Clash', 'config_path', fallback="")
                    
                    if self.clash_config_path and os.path.exists(self.clash_config_path):
                        self.add_log(f"已从配置文件加载Clash配置: {self.clash_config_path}", "info")
                        try:
                            config_data = load_config(self.clash_config_path)
                            self.controller_address = config_data['controller']
                            self.api_secret = config_data['secret']
                        except Exception as e:
                            self.add_log(f"从Clash配置文件加载控制器信息时出错: {e}", "error")
                    elif self.clash_config_path:
                        self.add_log(f"配置文件中指定的Clash配置路径不存在: {self.clash_config_path}", "warning")
                    else:
                        self.add_log("配置文件中未指定Clash配置路径", "info")
            except Exception as e:
                self.add_log(f"读取配置文件时出错: {e}", "error")
        else:
            self.add_log(f"未找到配置文件，将使用默认设置并在退出时创建: {self.config_file_path}", "info")
    
    def add_log(self, message, message_type="info"):
        print(f"[{message_type}] {message}")
        if hasattr(self, 'log_text') and self.log_text:
            self.log(message, message_type)
        else:
            self.log_buffer.append((message, message_type))
    
    def save_app_config(self):
        if 'Clash' not in self.config:
            self.config.add_section('Clash')
        
        self.config.set('Clash', 'config_path', self.config_file_input.text())
        
        try:
            os.makedirs(os.path.dirname(self.config_file_path), exist_ok=True)
            with open(self.config_file_path, 'w', encoding='utf-8') as configfile:
                self.config.write(configfile)
            self.add_log(f"配置已保存到: {self.config_file_path}", "success")
        except Exception as e:
            self.add_log(f"保存配置文件时出错: {e}", "error")
    
    def initUI(self):
        self.initialization_complete = False
        
        self.setWindowTitle('Clash_Auto_Switcher   by:yoruaki')
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        window_width = 1000
        window_height = 920
        x = (screen_geometry.width() - window_width) // 2
        y = (screen_geometry.height() - window_height) // 3
        self.setGeometry(x, y, window_width, window_height)
        self.setMinimumSize(1000, 900)
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #E6F3FF;
                background-image: url('');
                background-position: bottom right;
                background-repeat: no-repeat;
            }
        """)
        
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        
        columns_layout = QHBoxLayout()
        main_layout.addLayout(columns_layout)
        
        left_layout = QVBoxLayout()
        columns_layout.addLayout(left_layout, 1)
        
        center_layout = QVBoxLayout()
        columns_layout.addLayout(center_layout, 2)
        
        right_layout = QVBoxLayout()
        columns_layout.addLayout(right_layout, 1)
        
        
        proxy_blacklist_group = QGroupBox("代理节点关键词黑名单")
        proxy_blacklist_layout = QVBoxLayout()
        proxy_blacklist_group.setLayout(proxy_blacklist_layout)
        proxy_blacklist_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        proxy_blacklist_group.setFixedHeight(200)
        proxy_blacklist_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
        """)
        
        proxy_blacklist_label = QLabel("包含以下关键词的代理节点将被排除:")
        self.blacklist_input = QListWidget()
        self.blacklist_input.setAlternatingRowColors(True)
        self.blacklist_input.setFixedHeight(120)
        self.blacklist_input.setStyleSheet("""
            QListWidget {
                border: 1px solid #6AAFE6;
                border-radius: 4px;
                padding: 5px;
                background-color: #FFFFFF;
            }
            QListWidget::item {
                padding: 3px;
                border-radius: 2px;
            }
            QListWidget::item:alternate {
                background-color: #E6F3FF;
            }
            QListWidget::item:selected {
                background-color: #6AAFE6 !important;
                color: white;
            }
        """)
        
        default_blacklist = ["最新", "流量", "套餐", "重置", "自动选择", "故障转移", "DIRECT", "REJECT"]
        for item in default_blacklist:
            self.blacklist_input.addItem(item)
        
        blacklist_buttons_layout = QHBoxLayout()
        add_button = QPushButton("添加")
        add_button.setStyleSheet(self.get_button_style())
        add_button.clicked.connect(self.add_blacklist_item)
        remove_button = QPushButton("移除")
        remove_button.setStyleSheet(self.get_button_style())
        remove_button.clicked.connect(self.remove_blacklist_item)
        blacklist_buttons_layout.addWidget(add_button)
        blacklist_buttons_layout.addWidget(remove_button)
        
        proxy_blacklist_layout.addWidget(proxy_blacklist_label)
        proxy_blacklist_layout.addWidget(self.blacklist_input)
        proxy_blacklist_layout.addLayout(blacklist_buttons_layout)
        
        left_layout.addWidget(proxy_blacklist_group)
        
        filter_mode_group = QGroupBox("访问过滤模式")
        filter_mode_layout = QHBoxLayout()
        filter_mode_group.setLayout(filter_mode_layout)
        filter_mode_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        filter_mode_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
        """)
        
        self.conn_blacklist_mode_radio = QRadioButton("使用黑名单")
        self.conn_whitelist_mode_radio = QRadioButton("使用白名单")
        self.conn_blacklist_mode_radio.setChecked(True)
        
        self.conn_filter_mode_group = QButtonGroup()
        self.conn_filter_mode_group.addButton(self.conn_blacklist_mode_radio)
        self.conn_filter_mode_group.addButton(self.conn_whitelist_mode_radio)
        self.conn_filter_mode_group.buttonClicked.connect(self.on_conn_filter_mode_changed)
        
        filter_mode_layout.addWidget(self.conn_blacklist_mode_radio)
        filter_mode_layout.addWidget(self.conn_whitelist_mode_radio)
        left_layout.addWidget(filter_mode_group)

        self.conn_blacklist_group = QGroupBox("访问目标黑名单")
        conn_blacklist_layout = QVBoxLayout()
        self.conn_blacklist_group.setLayout(conn_blacklist_layout)
        self.conn_blacklist_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.conn_blacklist_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
        """)
        
        self.conn_blacklist_input = QListWidget()
        self.conn_blacklist_input.setAlternatingRowColors(True)
        self.conn_blacklist_input.setStyleSheet("""
            QListWidget {
                border: 1px solid #6AAFE6;
                border-radius: 4px;
                padding: 5px;
                background-color: #FFFFFF;
            }
            QListWidget::item {
                padding: 3px;
                border-radius: 2px;
            }
            QListWidget::item:alternate {
                background-color: #E6F3FF;
            }
            QListWidget::item:selected {
                background-color: #6AAFE6 !important;
                color: white;
            }
        """)
        
        default_conn_blacklist = []
        for item in default_conn_blacklist:
            self.conn_blacklist_input.addItem(item)
        conn_blacklist_layout.addWidget(self.conn_blacklist_input)
        
        conn_bl_buttons_layout = QHBoxLayout()
        add_conn_bl_button = QPushButton("添加")
        add_conn_bl_button.setStyleSheet(self.get_button_style())
        add_conn_bl_button.clicked.connect(self.add_conn_blacklist_item)
        remove_conn_bl_button = QPushButton("移除")
        remove_conn_bl_button.setStyleSheet(self.get_button_style())
        remove_conn_bl_button.clicked.connect(self.remove_conn_blacklist_item)
        conn_bl_buttons_layout.addWidget(add_conn_bl_button)
        conn_bl_buttons_layout.addWidget(remove_conn_bl_button)
        conn_blacklist_layout.addLayout(conn_bl_buttons_layout)
        left_layout.addWidget(self.conn_blacklist_group)

        self.conn_whitelist_group = QGroupBox("访问目标白名单")
        conn_whitelist_layout = QVBoxLayout()
        self.conn_whitelist_group.setLayout(conn_whitelist_layout)
        self.conn_whitelist_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.conn_whitelist_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
        """)
        
        self.conn_whitelist_input = QListWidget()
        self.conn_whitelist_input.setAlternatingRowColors(True)
        self.conn_whitelist_input.setStyleSheet("""
            QListWidget {
                border: 1px solid #6AAFE6;
                border-radius: 4px;
                padding: 5px;
                background-color: #FFFFFF;
            }
            QListWidget::item {
                padding: 3px;
                border-radius: 2px;
            }
            QListWidget::item:alternate {
                background-color: #E6F3FF;
            }
            QListWidget::item:selected {
                background-color: #6AAFE6 !important;
                color: white;
            }
        """)
        
        conn_whitelist_layout.addWidget(self.conn_whitelist_input)
        
        conn_wl_buttons_layout = QHBoxLayout()
        add_conn_wl_button = QPushButton("添加")
        add_conn_wl_button.setStyleSheet(self.get_button_style())
        add_conn_wl_button.clicked.connect(self.add_conn_whitelist_item)
        remove_conn_wl_button = QPushButton("移除")
        remove_conn_wl_button.setStyleSheet(self.get_button_style())
        remove_conn_wl_button.clicked.connect(self.remove_conn_whitelist_item)
        conn_wl_buttons_layout.addWidget(add_conn_wl_button)
        conn_wl_buttons_layout.addWidget(remove_conn_wl_button)
        conn_whitelist_layout.addLayout(conn_wl_buttons_layout)
        left_layout.addWidget(self.conn_whitelist_group)
        self.conn_whitelist_group.setVisible(False)
        
        
        config_group = QGroupBox("配置选项")
        config_layout = QVBoxLayout()
        config_group.setLayout(config_layout)
        config_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        config_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
        """)
        
        config_file_layout = QHBoxLayout()
        config_file_label = QLabel("配置文件路径:")
        self.config_file_input = QLineEdit()
        
        if self.clash_config_path:
            self.config_file_input.setText(self.clash_config_path)
            try:
                config_data = load_config(self.clash_config_path)
                self.controller_address = config_data['controller']
                self.api_secret = config_data['secret']
            except Exception as e:
                self.add_log(f"加载Clash配置文件时出错: {e}", "error")
        
        config_file_button = QPushButton("浏览...")
        config_file_button.setStyleSheet(self.get_button_style())
        config_file_button.clicked.connect(self.browse_config_file)
        config_file_layout.addWidget(config_file_label)
        config_file_layout.addWidget(self.config_file_input)
        config_file_layout.addWidget(config_file_button)
        config_layout.addLayout(config_file_layout)
        
        mode_group = QGroupBox("切换模式")
        mode_layout = QVBoxLayout()
        mode_group.setLayout(mode_layout)
        mode_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        mode_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
        """)
        
        self.time_mode_radio = QRadioButton("定时切换模式")
        self.connection_mode_radio = QRadioButton("连接次数切换模式")
        self.time_mode_radio.setChecked(True)
        
        self.mode_group = QButtonGroup()
        self.mode_group.addButton(self.time_mode_radio, 1)
        self.mode_group.addButton(self.connection_mode_radio, 2)
        self.mode_group.buttonClicked.connect(self.on_mode_changed)
        
        mode_layout.addWidget(self.time_mode_radio)
        mode_layout.addWidget(self.connection_mode_radio)
        
        config_layout.addWidget(mode_group)
        
        logic_group = QGroupBox("切换逻辑")
        logic_layout = QVBoxLayout()
        logic_group.setLayout(logic_layout)
        logic_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        logic_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
        """)
        
        self.random_logic_radio = QRadioButton("随机切换")
        self.sequential_logic_radio = QRadioButton("逻辑切换")
        
        sequential_desc = QLabel("逻辑切换: 切换过的代理节点暂时不会再被选择，直到所有可用节点都被使用一遍后再重新开始")
        sequential_desc.setWordWrap(True)
        sequential_desc.setStyleSheet("""
            color: #6AAFE6;
            font-weight: bold;
            padding: 5px;
            background-color: #E6F3FF;
            border: 1px dashed #6AAFE6;
            border-radius: 4px;
            margin-top: 5px;
            margin-bottom: 5px;
        """)
        
        self.random_logic_radio.setChecked(True)
        
        self.logic_group = QButtonGroup()
        self.logic_group.addButton(self.random_logic_radio, 1)
        self.logic_group.addButton(self.sequential_logic_radio, 2)
        self.logic_group.buttonClicked.connect(self.on_logic_changed)
        
        logic_layout.addWidget(self.random_logic_radio)
        logic_layout.addWidget(self.sequential_logic_radio)
        logic_layout.addWidget(sequential_desc)
        
        config_layout.addWidget(logic_group)
        
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("background-color: #6AAFE6;")
        config_layout.addWidget(separator)
        
        settings_container = QWidget()
        settings_container_layout = QVBoxLayout(settings_container)
        settings_container_layout.setContentsMargins(0, 0, 0, 0)
        
        max_height = 150
        settings_container.setFixedHeight(max_height)
        config_layout.addWidget(settings_container)
        
        self.time_settings_group = QGroupBox("定时切换设置")
        time_settings_layout = QVBoxLayout()
        self.time_settings_group.setLayout(time_settings_layout)
        self.time_settings_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
        """)
        
        interval_layout = QHBoxLayout()
        interval_label = QLabel("切换间隔(秒):")
        self.interval_input = QSpinBox()
        self.interval_input.setRange(5, 3600)
        self.interval_input.setValue(10)
        interval_layout.addWidget(interval_label)
        interval_layout.addWidget(self.interval_input)
        time_settings_layout.addLayout(interval_layout)
        
        time_settings_layout.addStretch(1)
        
        settings_container_layout.addWidget(self.time_settings_group)
        
        self.connection_settings_group = QGroupBox("连接次数切换设置")
        connection_settings_layout = QVBoxLayout()
        self.connection_settings_group.setLayout(connection_settings_layout)
        self.connection_settings_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
        """)
        
        api_poll_layout = QHBoxLayout()
        api_poll_label = QLabel("API轮询间隔(秒):")
        self.api_poll_input = QDoubleSpinBox()
        self.api_poll_input.setRange(0.1, 10)
        self.api_poll_input.setSingleStep(0.1)
        self.api_poll_input.setDecimals(1)
        self.api_poll_input.setValue(1.0)
        api_poll_layout.addWidget(api_poll_label)
        api_poll_layout.addWidget(self.api_poll_input)
        connection_settings_layout.addLayout(api_poll_layout)
        
        threshold_layout = QHBoxLayout()
        threshold_label = QLabel("连接次数阈值:")
        self.threshold_input = QSpinBox()
        self.threshold_input.setRange(1, 1000)
        self.threshold_input.setValue(5)
        threshold_layout.addWidget(threshold_label)
        threshold_layout.addWidget(self.threshold_input)
        connection_settings_layout.addLayout(threshold_layout)

        self.connection_counter_label = QLabel("当前连接计数: 0")
        connection_settings_layout.addWidget(self.connection_counter_label)
        
        settings_container_layout.addWidget(self.connection_settings_group)
        
        self.time_settings_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.connection_settings_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        
        self.connection_settings_group.setVisible(False)
        
        center_layout.addWidget(config_group)
        
        
        self.used_proxies_group = QGroupBox("已使用代理列表")
        used_proxies_layout = QVBoxLayout()
        self.used_proxies_group.setLayout(used_proxies_layout)
        self.used_proxies_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.used_proxies_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
        """)
        
        self.used_proxies_text = QTextEdit()
        self.used_proxies_text.setReadOnly(True)
        self.used_proxies_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #6AAFE6;
                border-radius: 4px;
                padding: 5px;
                background-color: #FFFFFF;
                color: #333333;
            }
        """)
        
        self.used_proxies_text.setHtml("<div style='color: #8BADD9; text-align: center; margin-top: 20px;'>暂无已使用的代理</div>")
        
        proxies_shadow = QGraphicsDropShadowEffect(self)
        proxies_shadow.setBlurRadius(10)
        proxies_shadow.setColor(QColor(106, 175, 230, 30))
        proxies_shadow.setOffset(0, 0)
        self.used_proxies_text.setGraphicsEffect(proxies_shadow)
        
        used_proxies_layout.addWidget(self.used_proxies_text)
        
        right_layout.addWidget(self.used_proxies_group)
        
        control_layout = QHBoxLayout()
        
        def add_shadow_effect(widget):
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(10)
            shadow.setColor(QColor(106, 175, 230, 60))
            shadow.setOffset(2, 2)
            widget.setGraphicsEffect(shadow)
        
        self.test_button = QPushButton("测试连接")
        self.test_button.setStyleSheet(self.get_button_style())
        self.test_button.clicked.connect(self.test_connection)
        self.test_button.setMinimumHeight(35)
        self.test_button.setFixedHeight(35)
        self.test_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        add_shadow_effect(self.test_button)
        
        self.start_button = QPushButton("开始切换")
        self.start_button.setStyleSheet(self.get_button_style())
        self.start_button.clicked.connect(self.start_switching)
        self.start_button.setMinimumHeight(35)
        self.start_button.setFixedHeight(35)
        self.start_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        add_shadow_effect(self.start_button)
        
        self.stop_button = QPushButton("停止切换")
        self.stop_button.setStyleSheet(self.get_button_style())
        self.stop_button.clicked.connect(self.stop_switching)
        self.stop_button.setEnabled(False)
        self.stop_button.setMinimumHeight(35)
        self.stop_button.setFixedHeight(35)
        self.stop_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        add_shadow_effect(self.stop_button)
        
        self.about_button = QPushButton("关于")
        self.about_button.setStyleSheet(self.get_button_style())
        self.about_button.clicked.connect(self.show_about_dialog)
        self.about_button.setFixedHeight(30)
        self.about_button.setFixedWidth(100)
        self.about_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        add_shadow_effect(self.about_button)
        
        control_layout.addWidget(self.test_button)
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addStretch()
        control_layout.addWidget(self.about_button)
        
        main_layout.addLayout(control_layout)
        
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)
        log_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        log_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #6AAFE6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgba(230, 243, 255, 180);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3B7DB9;
            }
        """)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Courier", 10))
        
        self.log_text.setMinimumHeight(200)
        
        log_shadow = QGraphicsDropShadowEffect(self)
        log_shadow.setBlurRadius(15)
        log_shadow.setColor(QColor(106, 175, 230, 30))
        log_shadow.setOffset(0, 0)
        self.log_text.setGraphicsEffect(log_shadow)
        
        log_layout.addWidget(self.log_text)
        main_layout.addWidget(log_group)
        
        self.statusBar = QStatusBar()
        self.statusBar.setStyleSheet("""
            QStatusBar {
                background-color: #E6F3FF;
                color: #333333;
                border-top: 1px solid #6AAFE6;
            }
        """)
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("就绪")
        
        self.show_ascii_art()
        
        QTimer.singleShot(100, self.scroll_to_top)
        
        self.initialization_complete = True
    
    def scroll_to_top(self):
        self.log_text.moveCursor(QTextCursor.MoveOperation.Start)
        self.log_text.ensureCursorVisible()
    
    def on_mode_changed(self, button):
        if button == self.time_mode_radio:
            self.time_settings_group.setVisible(True)
            self.connection_settings_group.setVisible(False)
            self.log("已选择定时切换模式", "info")
        else:
            self.time_settings_group.setVisible(False)
            self.connection_settings_group.setVisible(True)
            self.log("已选择连接次数切换模式", "info")
    
    def on_logic_changed(self, button):
        if button == self.random_logic_radio:
            self.log("已选择随机切换逻辑", "info")
        else:
            self.log("已选择逻辑切换逻辑", "info")
    
    def update_used_proxies(self, group_name, proxy_name, clear=False):
        if clear:
            if group_name in self.used_proxies_by_group:
                self.used_proxies_by_group[group_name] = []
        else:
            if group_name not in self.used_proxies_by_group:
                self.used_proxies_by_group[group_name] = []
            self.used_proxies_by_group[group_name].append(proxy_name)
        
        self.refresh_used_proxies_display()
    
    def refresh_used_proxies_display(self):
        text = ""
        for group_name, proxies in self.used_proxies_by_group.items():
            if proxies:
                text += f"<div style='margin-bottom: 10px;'>"
                text += f"<div style='font-weight: bold; color: #3B7DB9; background-color: #D9EAFF; padding: 3px; border-radius: 3px; border-left: 3px solid #6AAFE6;'>组: {group_name}</div>"
                for i, proxy in enumerate(proxies):
                    text += f"<div style='margin-left: 10px; padding: 2px; border-bottom: 1px dotted #6AAFE6;'>"
                    text += f"{i+1}. <span style='color: #3498db;'>{proxy}</span>"
                    text += "</div>"
                text += "</div>"
        
        if not text:
            text = "<div style='color: #8BADD9; text-align: center; margin-top: 20px;'>暂无已使用的代理</div>"
            
        self.used_proxies_text.setHtml(text)
    
    def show_ascii_art(self):
        ascii_art = r"""
  ___ _         _        _       _         ___        _ _      _
 / __| |__ _ __| |_     /_\ _  _| |_ ___  / __|_ __ _(_) |_ __| |_  ___ _ _ 
| (__| / _` (_-< ' \   / _ \ || |  _/ _ \ \__ \ V  V / |  _/ _| ' \/ -_) '_|
 \___|_\__,_/__/_||_|_/_/ \_\_,_|\__\___/_|___/\_/\_/|_|\__\__|_||_\___|_|  
                   |___|               |___|
        """
        self.log(ascii_art, "ascii_art")
        
        title_html = "<div style='text-align: center; color: #3B7DB9; font-weight: bold; font-size: 14px;'>Clash_Auto_Switcher v2.0</div>"
        author_html = "<div style='text-align: center; color: #6AAFE6;'>作者：yoruaki</div>"
        github_html = "<div style='text-align: center; color: #6AAFE6;'>github：https://github.com/yoruak1</div>"
        wechat_html = "<div style='text-align: center; color: #6AAFE6;'>公众号：夜秋的小屋</div>"
        
        self.log_text.append(title_html)
        self.log_text.append(author_html)
        self.log_text.append(github_html)
        self.log_text.append(wechat_html)
        self.log_text.append("<br>")
        
        tip_html = "<div style='text-align: center; color: #3B7DB9; background-color: #D9EAFF; padding: 5px; border-radius: 5px; border: 1px dashed #6AAFE6;'>"
        tip_html += "提示: 请先选择Clash配置文件，然后点击「测试连接」确认连接正常后开始自动切换"
        tip_html += "</div>"
        self.log_text.append(tip_html)
        self.log_text.append("<br>")
        
        self.log_text.moveCursor(QTextCursor.MoveOperation.Start)
        self.log_text.ensureCursorVisible()
    
    def browse_config_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择Clash配置文件", "", "YAML文件 (*.yaml *.yml);;所有文件 (*)")
        if file_path:
            self.config_file_input.setText(file_path)
            try:
                config_data = load_config(file_path)
                self.controller_address = config_data['controller']
                self.api_secret = config_data['secret']
                self.add_log(f"从配置文件加载控制器信息成功", "info")
                
                self.save_app_config()
            except Exception as e:
                self.add_log(f"加载配置文件时出错: {e}", "error")
    
    def add_blacklist_item(self):
        dialog = QInputDialog(self)
        dialog.setWindowTitle("添加黑名单项")
        dialog.setLabelText("请输入黑名单关键词:")
        dialog.setStyleSheet("""
            QInputDialog {
                background-color: #E6F3FF;
            }
            QLabel {
                color: #3B7DB9;
                font-weight: bold;
                font-family: '微软雅黑', Arial, sans-serif;
            }
            QLineEdit {
                border: 1px solid #6AAFE6;
                border-radius: 4px;
                padding: 5px;
                background-color: #FFFFFF;
            }
            QPushButton {
                background-color: #6AAFE6;
                color: white;
                border-radius: 5px;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8BC4F2;
            }
            QPushButton:pressed {
                background-color: #4A8BC2;
            }
        """)
        
        ok = dialog.exec()
        text = dialog.textValue()
        if ok and text:
            self.blacklist_input.addItem(text)
            self.save_lists()
    
    def remove_blacklist_item(self):
        selected_items = self.blacklist_input.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            self.blacklist_input.takeItem(self.blacklist_input.row(item))
        self.save_lists()
    
    def get_blacklist(self):
        blacklist = []
        for i in range(self.blacklist_input.count()):
            blacklist.append(self.blacklist_input.item(i).text())
        return blacklist
    
    def add_conn_blacklist_item(self):
        dialog = QInputDialog(self)
        dialog.setWindowTitle("添加访问黑名单项")
        dialog.setLabelText("请输入域名或IP地址:")
        dialog.setStyleSheet("""
            QInputDialog {
                background-color: #E6F3FF;
            }
            QLabel {
                color: #3B7DB9;
                font-weight: bold;
                font-family: '微软雅黑', Arial, sans-serif;
            }
            QLineEdit {
                border: 1px solid #6AAFE6;
                border-radius: 4px;
                padding: 5px;
                background-color: #FFFFFF;
            }
            QPushButton {
                background-color: #6AAFE6;
                color: white;
                border-radius: 5px;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8BC4F2;
            }
            QPushButton:pressed {
                background-color: #4A8BC2;
            }
        """)
        
        ok = dialog.exec()
        text = dialog.textValue()
        if ok and text:
            self.conn_blacklist_input.addItem(text)
            self.save_lists()
    
    def remove_conn_blacklist_item(self):
        selected_items = self.conn_blacklist_input.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            self.conn_blacklist_input.takeItem(self.conn_blacklist_input.row(item))
        self.save_lists()
    
    def get_connection_blacklist(self):
        blacklist = []
        for i in range(self.conn_blacklist_input.count()):
            blacklist.append(self.conn_blacklist_input.item(i).text())
        return blacklist
    
    def add_conn_whitelist_item(self):
        dialog = QInputDialog(self)
        dialog.setWindowTitle("添加访问白名单项")
        dialog.setLabelText("请输入域名或IP地址:")
        dialog.setStyleSheet("""
            QInputDialog {
                background-color: #E6F3FF;
            }
            QLabel {
                color: #3B7DB9;
                font-weight: bold;
                font-family: '微软雅黑', Arial, sans-serif;
            }
            QLineEdit {
                border: 1px solid #6AAFE6;
                border-radius: 4px;
                padding: 5px;
                background-color: #FFFFFF;
            }
            QPushButton {
                background-color: #6AAFE6;
                color: white;
                border-radius: 5px;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8BC4F2;
            }
            QPushButton:pressed {
                background-color: #4A8BC2;
            }
        """)
        
        ok = dialog.exec()
        text = dialog.textValue()
        if ok and text:
            self.conn_whitelist_input.addItem(text)
            self.save_lists()
    
    def remove_conn_whitelist_item(self):
        selected_items = self.conn_whitelist_input.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            self.conn_whitelist_input.takeItem(self.conn_whitelist_input.row(item))
        self.save_lists()

    def get_connection_whitelist(self):
        whitelist = []
        for i in range(self.conn_whitelist_input.count()):
            whitelist.append(self.conn_whitelist_input.item(i).text())
        return whitelist
    
    def test_connection(self):
        controller = self.controller_address
        secret = self.api_secret
        
        test_headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        controller_url = controller
        if not controller_url.startswith("http://") and not controller_url.startswith("https://"):
            controller_url = f"http://{controller_url}"
            
        self.log(f"正在测试与控制器 {controller_url} 的连接...", "info")
        self.statusBar.showMessage("正在测试连接...")
        
        try:
            test_response = requests.get(f"{controller_url}/version", headers=test_headers)
            version = test_response.json().get('version', '未知')
            self.log(f"控制器连接测试成功! Clash 版本: {version}", "success")
            
            test_response = requests.get(f"{controller_url}/connections", headers=test_headers)
            if test_response.status_code == 200:
                connections = test_response.json().get('connections', [])
                self.log(f"连接监控API测试成功! 当前活跃连接数: {len(connections)}", "success")
                self.statusBar.showMessage(f"连接测试成功! Clash 版本: {version}")
                self.statusBar.setStyleSheet("""
                    QStatusBar {
                        background-color: #D9EAFF;
                        color: #2ecc71;
                        border-top: 1px solid #6AAFE6;
                        font-weight: bold;
                    }
                """)
            else:
                self.log(f"连接监控API测试失败! 状态码: {test_response.status_code}", "error")
                self.statusBar.showMessage("连接监控API测试失败!")
                self.statusBar.setStyleSheet("""
                    QStatusBar {
                        background-color: #FDEDEC;
                        color: #C0392B;
                        border-top: 1px solid #E74C3C;
                        font-weight: bold;
                    }
                """)
        except Exception as e:
            self.log(f"警告: 无法连接到控制器 {controller_url}: {e}", "error")
            self.statusBar.showMessage(f"连接失败: {e}")
            self.statusBar.setStyleSheet("""
                QStatusBar {
                    background-color: #FDEDEC;
                    color: #C0392B;
                    border-top: 1px solid #E74C3C;
                    font-weight: bold;
                }
            """)
    
    def start_switching(self):
        if self.switcher_thread and self.switcher_thread.isRunning():
            self.log("代理切换已经在运行中", "warning")
            return
        
        controller = self.controller_address
        secret = self.api_secret
        interval = self.interval_input.value()
        config_path = self.config_file_input.text()
        blacklist = self.get_blacklist()
        
        switch_mode = "time" if self.time_mode_radio.isChecked() else "connection"
        
        switch_logic = "random" if self.random_logic_radio.isChecked() else "sequential"
        
        self.used_proxies_by_group = {}
        self.refresh_used_proxies_display()
        
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.statusBar.showMessage("正在启动代理切换...")
        
        mode_text = "定时切换模式" if switch_mode == "time" else "连接次数切换模式"
        logic_text = "随机切换" if switch_logic == "random" else "逻辑切换"
        
        if switch_mode == "time":
            self.log(f"正在启动{mode_text}，{logic_text}，间隔时间为 {interval} 秒", "success")
        else:
            self.log(f"正在启动{mode_text}，{logic_text}，连接阈值为 {self.threshold_input.value()} 次", "success")
        
        self.switcher_thread = ProxySwitcherThread(interval, config_path, secret, controller, blacklist, switch_mode, switch_logic)
        self.switcher_thread.log_signal.connect(self.log)
        self.switcher_thread.status_update.connect(self.update_status)
        self.switcher_thread.used_proxy_update.connect(self.update_used_proxies)
        self.switcher_thread.start()
        
        if switch_mode == "connection":
            self.connection_counter = 0
            self.update_connection_counter_label()
            
            api_poll_interval = self.api_poll_input.value()
            self.connection_threshold = self.threshold_input.value()
            
            connection_filter_mode = 'blacklist'
            connection_list = []
            if self.conn_blacklist_mode_radio.isChecked():
                connection_filter_mode = 'blacklist'
                connection_list = self.get_connection_blacklist()
                if connection_list:
                    self.log(f"访问过滤模式: 黑名单，包含 {len(connection_list)} 个项目", "info")
            else:
                connection_filter_mode = 'whitelist'
                connection_list = self.get_connection_whitelist()
                if connection_list:
                    self.log(f"访问过滤模式: 白名单，包含 {len(connection_list)} 个项目", "info")
                else:
                    self.log("警告: 访问过滤模式为白名单，但列表为空，将不会有任何连接被计数", "warning")

            self.monitor_thread = ConnectionMonitorThread(controller, secret, api_poll_interval, connection_filter_mode, connection_list)
            self.monitor_thread.log_signal.connect(self.log)
            self.monitor_thread.connection_detected.connect(self.on_connection_detected)
            self.monitor_thread.start()
            self.log(f"启动API连接监控，轮询间隔: {api_poll_interval}秒", "info")
            self.log(f"连接阈值设置为: {self.connection_threshold}次", "info")
            
    def on_connection_detected(self):
        self.connection_counter += 1
        self.update_connection_counter_label()
        
        if self.connection_counter >= self.connection_threshold:
            self.log(f"达到连接阈值({self.connection_threshold}次)，触发IP切换", "highlight")
            if self.switcher_thread and self.switcher_thread.isRunning():
                self.switcher_thread.switch_proxy_now()
            self.connection_counter = 0
            self.update_connection_counter_label()
    
    def update_connection_counter_label(self):
        self.connection_counter_label.setText(f"当前连接计数: {self.connection_counter}")
    
    def stop_switching(self):
        if self.switcher_thread and self.switcher_thread.isRunning():
            self.switcher_thread.stop()
            self.log("正在停止代理切换，请等待当前操作完成...", "highlight")
            self.statusBar.showMessage("正在停止代理切换...")
        else:
            self.update_status(False)
            self.log("代理切换未在运行", "warning")
        
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
            self.monitor_thread.wait()
            self.monitor_thread = None
    
    def update_status(self, running):
        if running:
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.statusBar.showMessage("正在运行中...")
            self.statusBar.setStyleSheet("""
                QStatusBar {
                    background-color: #D9EAFF;
                    color: #3B7DB9;
                    border-top: 1px solid #6AAFE6;
                    font-weight: bold;
                }
            """)
        else:
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.statusBar.showMessage("已停止")
            self.statusBar.setStyleSheet("""
                QStatusBar {
                    background-color: #E6F3FF;
                    color: #333333;
                    border-top: 1px solid #6AAFE6;
                }
            """)
    
    def on_conn_filter_mode_changed(self, button):
        if button == self.conn_blacklist_mode_radio:
            self.conn_blacklist_group.setVisible(True)
            self.conn_whitelist_group.setVisible(False)
        else:
            self.conn_blacklist_group.setVisible(False)
            self.conn_whitelist_group.setVisible(True)
            
    def load_lists(self):
        os.makedirs(self.config_dir, exist_ok=True)
        
        if os.path.exists(self.keywordlist_file):
            try:
                with open(self.keywordlist_file, 'r', encoding='utf-8') as f:
                    keywords = [line.strip() for line in f if line.strip()]
                    self.blacklist_input.clear()
                    for keyword in keywords:
                        self.blacklist_input.addItem(keyword)
                self.add_log(f"已从{self.keywordlist_file}加载节点关键词黑名单", "info")
            except Exception as e:
                self.add_log(f"加载节点关键词黑名单时出错: {e}", "error")
                default_blacklist = ["最新", "流量", "套餐", "重置", "自动选择", "故障转移", "DIRECT", "REJECT"]
                self.blacklist_input.clear()
                for item in default_blacklist:
                    self.blacklist_input.addItem(item)
        
        if os.path.exists(self.blacklist_file):
            try:
                with open(self.blacklist_file, 'r', encoding='utf-8') as f:
                    blacklist = [line.strip() for line in f if line.strip()]
                    self.conn_blacklist_input.clear()
                    for item in blacklist:
                        self.conn_blacklist_input.addItem(item)
                self.add_log(f"已从{self.blacklist_file}加载访问目标黑名单", "info")
            except Exception as e:
                self.add_log(f"加载访问目标黑名单时出错: {e}", "error")
                self.conn_blacklist_input.clear()
        
        if os.path.exists(self.whitelist_file):
            try:
                with open(self.whitelist_file, 'r', encoding='utf-8') as f:
                    whitelist = [line.strip() for line in f if line.strip()]
                    self.conn_whitelist_input.clear()
                    for item in whitelist:
                        self.conn_whitelist_input.addItem(item)
                self.add_log(f"已从{self.whitelist_file}加载访问目标白名单", "info")
            except Exception as e:
                self.add_log(f"加载访问目标白名单时出错: {e}", "error")
    
    def save_lists(self):
        os.makedirs(self.config_dir, exist_ok=True)
        
        try:
            with open(self.keywordlist_file, 'w', encoding='utf-8') as f:
                for i in range(self.blacklist_input.count()):
                    f.write(f"{self.blacklist_input.item(i).text()}\n")
            self.add_log(f"节点关键词黑名单已保存到{self.keywordlist_file}", "success")
        except Exception as e:
            self.add_log(f"保存节点关键词黑名单时出错: {e}", "error")
        
        try:
            with open(self.blacklist_file, 'w', encoding='utf-8') as f:
                for i in range(self.conn_blacklist_input.count()):
                    f.write(f"{self.conn_blacklist_input.item(i).text()}\n")
            self.add_log(f"访问目标黑名单已保存到{self.blacklist_file}", "success")
        except Exception as e:
            self.add_log(f"保存访问目标黑名单时出错: {e}", "error")
        
        try:
            with open(self.whitelist_file, 'w', encoding='utf-8') as f:
                for i in range(self.conn_whitelist_input.count()):
                    f.write(f"{self.conn_whitelist_input.item(i).text()}\n")
            self.add_log(f"访问目标白名单已保存到{self.whitelist_file}", "success")
        except Exception as e:
            self.add_log(f"保存访问目标白名单时出错: {e}", "error")

    def closeEvent(self, event):
        if hasattr(self, 'snow_timer') and self.snow_timer.isActive():
            self.snow_timer.stop()
            
        if self.switcher_thread and self.switcher_thread.isRunning():
            self.switcher_thread.stop()
            self.switcher_thread.wait()
        
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        
        self.save_app_config()
        self.save_lists()
            
        event.accept()

    def show_about_dialog(self):
        about_dialog = QDialog(self)
        about_dialog.setWindowTitle("关于")
        about_dialog.setFixedSize(600, 300)
        about_dialog.setStyleSheet("""
            QDialog {
                background-color: #E6F3FF;
                border: 2px solid #6AAFE6;
                border-radius: 10px;
            }
        """)
        
        dialog_layout = QHBoxLayout(about_dialog)
        dialog_layout.setSpacing(20)
        
        left_layout = QVBoxLayout()
        left_logo_label = QLabel()
        
        resource_clash_logo = get_resource_path(os.path.join("icons", "clash.png"))
        
        if os.path.exists(resource_clash_logo):
            pixmap = QPixmap(resource_clash_logo)
        else:
            pixmap = QPixmap(120, 120)
            pixmap.fill(QColor("#6AAFE6"))
            
        pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        left_logo_label.setPixmap(pixmap)
        left_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        github_url = "https://github.com/yoruak1"
        github_label = QLabel(f'<a href="{github_url}" style="text-decoration:none; color:#3B7DB9;">{github_url}</a>')
        github_label.setOpenExternalLinks(True)
        github_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        github_label.setStyleSheet("""
            color: #3B7DB9;
            font-size: 11pt;
            font-weight: bold;
            font-family: '微软雅黑', Arial, sans-serif;
            letter-spacing: 1px;
            padding: 8px;
            border-radius: 8px;
            background-color: white;
            border: 3px solid #6AAFE6;
            margin: 10px;
        """)
        
        left_layout.addWidget(left_logo_label)
        left_layout.addWidget(github_label)
        left_layout.addStretch()
        
        right_layout = QVBoxLayout()
        right_logo_label = QLabel()
        
        resource_yoruaki_logo = get_resource_path(os.path.join("icons", "yoruaki.png"))
        
        if os.path.exists(resource_yoruaki_logo):
            pixmap = QPixmap(resource_yoruaki_logo)
        else:
            pixmap = QPixmap(120, 120)
            pixmap.fill(QColor("#6AAFE6"))
            
        pixmap = pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        right_logo_label.setPixmap(pixmap)
        right_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        wechat_label = QLabel("绿泡泡公众号：夜秋的小屋")
        wechat_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wechat_label.setStyleSheet("""
            color: #3B7DB9;
            font-size: 11pt;
            font-weight: bold;
            font-family: '微软雅黑', Arial, sans-serif;
            letter-spacing: 1px;
            padding: 8px;
            border-radius: 8px;
            background-color: white;
            border: 3px solid #6AAFE6;
            margin: 10px;
        """)
        
        right_layout.addWidget(right_logo_label)
        right_layout.addWidget(wechat_label)
        right_layout.addStretch()
        
        dialog_layout.addLayout(left_layout, 1)
        dialog_layout.addLayout(right_layout, 1)
        
        about_dialog.exec()

    def init_snowflakes(self, count):
        self.snowflakes = []
        for _ in range(count):
            self.snowflakes.append(Snowflake(self.width(), self.height()))
    
    def update_snow(self):
        for snowflake in self.snowflakes:
            snowflake.update()
        self.update()
    
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        for snowflake in self.snowflakes:
            painter.save()
            
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(snowflake.color))
            
            painter.translate(QPoint(int(snowflake.x), int(snowflake.y)))
            
            if snowflake.shape_type == 0:
                painter.drawEllipse(QPoint(0, 0), snowflake.size, snowflake.size)
            
            elif snowflake.shape_type == 1:
                painter.rotate(snowflake.rotation)
                size = snowflake.size
                for i in range(6):
                    painter.save()
                    painter.rotate(60 * i)
                    painter.drawLine(0, 0, 0, int(size * 2))
                    painter.drawLine(0, int(size * 0.5), int(size * 0.5), int(size * 0.3))
                    painter.drawLine(0, int(size * 0.5), -int(size * 0.5), int(size * 0.3))
                    painter.drawLine(0, int(size), int(size * 0.7), int(size * 0.7))
                    painter.drawLine(0, int(size), -int(size * 0.7), int(size * 0.7))
                    painter.restore()
            
            elif snowflake.shape_type == 2:
                painter.rotate(snowflake.rotation)
                size = snowflake.size
                points = []
                for i in range(10):
                    angle = 2 * 3.14159 * i / 10
                    radius = size if i % 2 == 0 else size * 0.4
                    points.append(QPoint(int(radius * math.cos(angle)), int(radius * math.sin(angle))))
                painter.drawPolygon(points)
            
            painter.restore()

    def resizeEvent(self, event):
        if hasattr(self, 'logo_frame'):
            self.position_logo()
        
        for snowflake in self.snowflakes:
            snowflake.parent_width = self.width()
            snowflake.parent_height = self.height()
        
        super().resizeEvent(event)

def main():
    if sys.platform == 'win32':
        import ctypes
        myappid = 'yoruaki.clash.auto.switcher'
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception as e:
            print(f"设置应用程序ID失败: {e}")

    app = QApplication(sys.argv)
    gui = ClashAutoSwitcherGUI()
    gui.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()