import sys
import os
import json
import subprocess
import threading
import time
import webbrowser
from datetime import date
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                               QPushButton, QLabel, QLineEdit, QMessageBox, 
                               QGroupBox, QCheckBox, QFrame, QDialog, QComboBox, 
                               QDateEdit, QTextEdit)
from PySide6.QtGui import QTextCursor, QFont
from PySide6.QtCore import Qt, Signal, QThread, Slot, QDate

# ==========================================
# 0. 基础配置与路径
# ==========================================
def get_app_path():
    """获取程序运行时的绝对路径 (兼容 EXE 和 Python 脚本)"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

APP_ROOT = get_app_path()
USER_DATA_DIR = os.path.join(APP_ROOT, "user_data")
STRATEGY_DIR = os.path.join(USER_DATA_DIR, "strategies")
CONFIG_PATH = os.path.join(USER_DATA_DIR, "config.json")
# [新增] 历史记录文件路径
HISTORY_PATH = os.path.join(USER_DATA_DIR, "pairs_history.json")

# --- 样式表 ---
STYLE_LIGHT_ON = "background-color: #2ecc71; border-radius: 10px; border: 2px solid #27ae60;" 
STYLE_LIGHT_OFF = "background-color: #e74c3c; border-radius: 10px; border: 2px solid #c0392b;" 
STYLE_BTN_GREEN = "background-color: #dff0d8; color: #3c763d; font-weight: bold;"
STYLE_BTN_BLUE = "background-color: #d9edf7; color: #31708f; font-weight: bold;"
STYLE_BTN_PURPLE = "background-color: #e8daef; color: #8e44ad; font-weight: bold;"
STYLE_BTN_ORANGE = "background-color: #f39c12; color: white; font-weight: bold;"
STYLE_BTN_RED = "background-color: #ffcccc; color: #cc0000; font-weight: bold; font-size: 11pt;"

# ==========================================
# 1. 后台任务线程 (执行回测/下载/优化)
# ==========================================
class DockerWorker(QThread):
    log_signal = Signal(str)
    finish_signal = Signal()

    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd

    def run(self):
        try:
            self.log_signal.emit(f"🚀 执行命令:\n{self.cmd}\n{'='*40}\n")
            process = subprocess.Popen(
                self.cmd, 
                shell=True, 
                cwd=APP_ROOT, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                creationflags=subprocess.CREATE_NO_WINDOW,
                encoding='utf-8', 
                errors='replace'
            )

            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    self.log_signal.emit(line.strip())
            
            self.log_signal.emit(f"\n{'='*40}\n✅ 任务结束")
        except Exception as e:
            self.log_signal.emit(f"❌ 发生错误: {str(e)}")
        finally:
            self.finish_signal.emit()

# ==========================================
# 2. 实验室弹窗 (回测、下载与优化) - V6.4 更新
# ==========================================
class BacktestWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 实验室: 回测 / 下载 / 优化 (Hyperopt)")
        self.resize(800, 850)
        self.init_ui()
        self.scan_files()
        self.load_history() # [新增] 加载历史记录

    def init_ui(self):
        layout = QVBoxLayout()

        # --- 1. 基础配置 ---
        grp_basic = QGroupBox("1. 基础配置")
        lay_basic = QVBoxLayout()
        
        # 策略与配置
        hbox_files = QHBoxLayout()
        hbox_files.addWidget(QLabel("策略:"))
        self.combo_strat = QComboBox()
        hbox_files.addWidget(self.combo_strat)
        hbox_files.addWidget(QLabel(" 配置:"))
        self.combo_conf = QComboBox()
        hbox_files.addWidget(self.combo_conf)
        lay_basic.addLayout(hbox_files)

        # 时间选择
        hbox_time = QHBoxLayout()
        hbox_time.addWidget(QLabel("时间范围:"))
        
        self.line_days = QLineEdit()
        self.line_days.setPlaceholderText("30")
        self.line_days.setFixedWidth(50)
        self.line_days.setToolTip("填写数字。\n下载模式: 生成 --days N\n回测/优化模式: 自动换算为具体日期范围 --timerange")
        hbox_time.addWidget(QLabel("最近"))
        hbox_time.addWidget(self.line_days)
        hbox_time.addWidget(QLabel("天  或  指定日期:"))
        
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        self.date_start.setDate(QDate.currentDate().addDays(-30))
        hbox_time.addWidget(self.date_start)
        hbox_time.addWidget(QLabel("-"))
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        self.date_end.setDate(QDate.currentDate())
        hbox_time.addWidget(self.date_end)
        
        lay_basic.addLayout(hbox_time)
        grp_basic.setLayout(lay_basic)
        layout.addWidget(grp_basic)

        # --- 2. 高级参数 (通用) ---
        grp_adv = QGroupBox("2. 高级参数 (通用)")
        lay_adv = QVBoxLayout()
        
        # 币种与模式
        hbox_pairs = QHBoxLayout()
        self.chk_futures = QCheckBox("🔥 合约模式 (Futures)")
        self.chk_futures.setChecked(True)
        self.chk_futures.setStyleSheet("color: #e67e22; font-weight: bold;")
        hbox_pairs.addWidget(self.chk_futures)
        
        hbox_pairs.addWidget(QLabel("   强制币种:"))
        
        # [修改] 使用 QComboBox 替代 QLineEdit 以支持历史记录
        self.line_pairs = QComboBox()
        self.line_pairs.setEditable(True) # 允许自由输入
        self.line_pairs.setToolTip("留空则使用配置文件的白名单。\n输入新内容并生成指令后，会自动保存到历史记录。")
        self.line_pairs.setPlaceholderText("如 BTC/USDC:USDC (可手动输入)")
        hbox_pairs.addWidget(self.line_pairs, stretch=1) # stretch=1 让它尽可能宽
        
        lay_adv.addLayout(hbox_pairs)
        
        # 附加选项
        hbox_opts = QHBoxLayout()
        hbox_opts.addWidget(QLabel("K线周期:"))
        self.line_tf = QLineEdit("1m 5m 15m 1h 4h 1d")
        hbox_opts.addWidget(self.line_tf)
        
        self.chk_export = QCheckBox("💾 导出结果至 UI (--export trades)")
        self.chk_export.setChecked(True) 
        self.chk_export.setToolTip("仅回测有效。勾选后，结果可在 FreqUI 网页端查看")
        hbox_opts.addWidget(self.chk_export)
        
        lay_adv.addLayout(hbox_opts)
        grp_adv.setLayout(lay_adv)
        layout.addWidget(grp_adv)

        # --- 3. 优化参数 (Hyperopt 专用) ---
        grp_hyper = QGroupBox("3. 优化参数 (Hyperopt 专用)")
        lay_hyper = QVBoxLayout()

        hbox_hyp_1 = QHBoxLayout()
        hbox_hyp_1.addWidget(QLabel("优化轮数 (Epochs):"))
        self.line_epochs = QLineEdit("100")
        self.line_epochs.setFixedWidth(80)
        hbox_hyp_1.addWidget(self.line_epochs)
        
        hbox_hyp_1.addWidget(QLabel("   评估标准 (Loss):"))
        self.combo_loss = QComboBox()
        
        # V6.3 保留功能: 中文显示 + OnlyProfit
        self.combo_loss.addItem("夏普比率 (Sharpe - 默认推荐)", "SharpeHyperOptLoss")
        self.combo_loss.addItem("索提诺比率 (Sortino - 关注下行风险)", "SortinoHyperOptLoss")
        self.combo_loss.addItem("卡尔玛比率 (Calmar - 收益回撤比)", "CalmarHyperOptLoss")
        self.combo_loss.addItem("利润与回撤平衡 (ProfitDrawDown)", "ProfitDrawDownHyperOptLoss")
        self.combo_loss.addItem("纯利润优先 (OnlyProfit - 极度贪婪)", "OnlyProfitHyperOptLoss")
        
        self.combo_loss.setToolTip("告诉机器人什么样才算'好的策略'。\n默认推荐 Sharpe (夏普比率)。")
        hbox_hyp_1.addWidget(self.combo_loss)
        lay_hyper.addLayout(hbox_hyp_1)

        hbox_hyp_2 = QHBoxLayout()
        hbox_hyp_2.addWidget(QLabel("优化空间:"))
        
        self.chk_space_buy = QCheckBox("Buy (买入)")
        self.chk_space_buy.setChecked(True)
        hbox_hyp_2.addWidget(self.chk_space_buy)

        self.chk_space_sell = QCheckBox("Sell (卖出)")
        self.chk_space_sell.setChecked(True)
        hbox_hyp_2.addWidget(self.chk_space_sell)

        self.chk_space_roi = QCheckBox("ROI (止盈)")
        hbox_hyp_2.addWidget(self.chk_space_roi)

        self.chk_space_stop = QCheckBox("Stoploss (止损)")
        hbox_hyp_2.addWidget(self.chk_space_stop)
        
        self.chk_space_trail = QCheckBox("Trailing (移动止损)")
        hbox_hyp_2.addWidget(self.chk_space_trail)
        
        lay_hyper.addLayout(hbox_hyp_2)
        grp_hyper.setLayout(lay_hyper)
        layout.addWidget(grp_hyper)

        # --- 4. 指令生成与预览区 ---
        grp_cmd = QGroupBox("4. 指令预览与执行")
        lay_cmd = QVBoxLayout()
        
        hbox_gen = QHBoxLayout()
        self.btn_gen_dl = QPushButton("📝 生成【下载】指令")
        self.btn_gen_dl.setStyleSheet(STYLE_BTN_BLUE)
        self.btn_gen_dl.clicked.connect(self.gen_download_cmd)
        
        self.btn_gen_bt = QPushButton("📝 生成【回测】指令")
        self.btn_gen_bt.setStyleSheet(STYLE_BTN_GREEN)
        self.btn_gen_bt.clicked.connect(self.gen_backtest_cmd)

        self.btn_gen_hyp = QPushButton("💊 生成【优化】指令")
        self.btn_gen_hyp.setStyleSheet(STYLE_BTN_PURPLE)
        self.btn_gen_hyp.clicked.connect(self.gen_hyperopt_cmd)
        
        hbox_gen.addWidget(self.btn_gen_dl)
        hbox_gen.addWidget(self.btn_gen_bt)
        hbox_gen.addWidget(self.btn_gen_hyp)
        lay_cmd.addLayout(hbox_gen)
        
        self.txt_preview = QTextEdit()
        self.txt_preview.setPlaceholderText("点击上方按钮生成指令，指令将显示在这里...")
        self.txt_preview.setMaximumHeight(80)
        self.txt_preview.setStyleSheet("color: #00ffff; background-color: #333; font-family: Consolas; font-weight: bold;")
        lay_cmd.addWidget(self.txt_preview)
        
        self.btn_run = QPushButton("🚀 执行预览中的指令 (Execute)")
        self.btn_run.setStyleSheet(STYLE_BTN_RED)
        self.btn_run.setFixedHeight(40)
        self.btn_run.clicked.connect(self.execute_preview_cmd)
        lay_cmd.addWidget(self.btn_run)
        
        grp_cmd.setLayout(lay_cmd)
        layout.addWidget(grp_cmd)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: Consolas; font-size: 10pt;")
        layout.addWidget(self.txt_log)

        self.setLayout(layout)

    # --- [新增逻辑] 历史记录管理 ---
    def load_history(self):
        """从文件加载币种历史记录"""
        if os.path.exists(HISTORY_PATH):
            try:
                with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    if isinstance(history, list):
                        self.line_pairs.addItems(history)
            except: pass

    def save_history(self):
        """保存当前输入的币种到历史记录 (如果不存在的话)"""
        current_pair = self.line_pairs.currentText().strip()
        if not current_pair: return

        # 获取当前所有项
        items = [self.line_pairs.itemText(i) for i in range(self.line_pairs.count())]
        
        # 如果是新的，添加进列表
        if current_pair not in items:
            self.line_pairs.addItem(current_pair)
            items.append(current_pair)
            
            # 保存到文件
            try:
                if not os.path.exists(USER_DATA_DIR):
                    os.makedirs(USER_DATA_DIR)
                with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
                    json.dump(items, f, ensure_ascii=False, indent=4)
            except: pass

    def scan_files(self):
        self.combo_strat.clear()
        if os.path.exists(STRATEGY_DIR):
            strategies = [f[:-3] for f in os.listdir(STRATEGY_DIR) if f.endswith(".py") and f != "__init__.py"]
            if strategies: self.combo_strat.addItems(strategies)
            else: self.combo_strat.addItem("未找到策略")
        
        self.combo_conf.clear()
        if os.path.exists(USER_DATA_DIR):
            configs = [f for f in os.listdir(USER_DATA_DIR) if f.endswith(".json")]
            self.combo_conf.addItems(configs)
            index = self.combo_conf.findText("back.json")
            if index >= 0: self.combo_conf.setCurrentIndex(index)

    def get_time_flags(self, is_backtest=False):
        days_txt = self.line_days.text().strip()
        if days_txt.isdigit() and int(days_txt) > 0:
            if is_backtest:
                days = int(days_txt)
                today = QDate.currentDate()
                start_date = today.addDays(-days)
                t_str = f"{start_date.toString('yyyyMMdd')}-{today.toString('yyyyMMdd')}"
                return f"--timerange {t_str}"
            else:
                return f"--days {days_txt}"
        else:
            d_start = self.date_start.date().toString("yyyyMMdd")
            d_end = self.date_end.date().toString("yyyyMMdd")
            return f"--timerange {d_start}-{d_end}"

    def get_base_cmd(self, is_backtest=False):
        config_file = self.combo_conf.currentText()
        time_flag = self.get_time_flags(is_backtest=is_backtest)
        
        cmd = f"--config user_data/{config_file} {time_flag}"
        
        # [修改] 使用 currentText() 获取 ComboBox 的输入内容
        raw_pairs = self.line_pairs.currentText().strip()
        if raw_pairs:
            pairs = " ".join(raw_pairs.split())
            cmd += f" --pairs {pairs}"
            # [新增] 只要生成基础命令，就尝试保存历史记录
            self.save_history()
            
        return cmd

    def gen_download_cmd(self):
        base_cmd = self.get_base_cmd(is_backtest=False)
        tfs = self.line_tf.text().strip()
        mode_flag = "--trading-mode futures" if self.chk_futures.isChecked() else "--trading-mode spot"
        full_cmd = f"docker compose run --rm freqtrade download-data {base_cmd} {mode_flag} -t {tfs}"
        self.txt_preview.setText(full_cmd)

    def gen_backtest_cmd(self):
        base_cmd = self.get_base_cmd(is_backtest=True)
        strategy = self.combo_strat.currentText()
        export_flag = "--export trades" if self.chk_export.isChecked() else ""
        full_cmd = f"docker compose run --rm freqtrade backtesting {base_cmd} --strategy {strategy} {export_flag}"
        self.txt_preview.setText(full_cmd)

    def gen_hyperopt_cmd(self):
        base_cmd = self.get_base_cmd(is_backtest=True)
        strategy = self.combo_strat.currentText()
        epochs = self.line_epochs.text().strip()
        if not epochs: epochs = "100"
        
        loss_func = self.combo_loss.currentData()
        if not loss_func: loss_func = "SharpeHyperOptLoss"
        
        spaces = []
        if self.chk_space_buy.isChecked(): spaces.append("buy")
        if self.chk_space_sell.isChecked(): spaces.append("sell")
        if self.chk_space_roi.isChecked(): spaces.append("roi")
        if self.chk_space_stop.isChecked(): spaces.append("stoploss")
        if self.chk_space_trail.isChecked(): spaces.append("trailing")
        
        spaces_str = " ".join(spaces)
        spaces_flag = f"--spaces {spaces_str}" if spaces else "--spaces buy sell"
        
        full_cmd = (f"docker compose run --rm freqtrade hyperopt {base_cmd} "
                    f"--strategy {strategy} --hyperopt-loss {loss_func} "
                    f"{spaces_flag} --epochs {epochs} -j -1")
        
        self.txt_preview.setText(full_cmd)

    def execute_preview_cmd(self):
        cmd = self.txt_preview.toPlainText().strip()
        if not cmd:
            QMessageBox.warning(self, "提示", "预览框为空，请先生成指令！")
            return
        self.txt_log.clear()
        self.start_worker(cmd)

    def start_worker(self, cmd):
        self.btn_run.setEnabled(False)
        self.btn_gen_dl.setEnabled(False)
        self.btn_gen_bt.setEnabled(False)
        self.btn_gen_hyp.setEnabled(False)
        
        self.worker = DockerWorker(cmd)
        self.worker.log_signal.connect(self.append_log)
        self.worker.finish_signal.connect(self.on_finished)
        self.worker.start()

    def append_log(self, text):
        self.txt_log.append(text)
        self.txt_log.moveCursor(QTextCursor.End)

    def on_finished(self):
        self.btn_run.setEnabled(True)
        self.btn_gen_dl.setEnabled(True)
        self.btn_gen_bt.setEnabled(True)
        self.btn_gen_hyp.setEnabled(True)

# ==========================================
# 3. 主程序 (FreqtradeManager) - 保持不变
# ==========================================
class DockerMonitor(QThread):
    status_signal = Signal(bool)
    def run(self):
        while True:
            try:
                result = subprocess.run(
                    "docker compose ps --services --filter \"status=running\"", 
                    shell=True, cwd=APP_ROOT, capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self.status_signal.emit(bool(result.stdout.strip()))
            except: self.status_signal.emit(False)
            time.sleep(3) 

class FreqtradeManager(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Freqtrade 懒人管家 (V6.4 历史增强版)")
        self.setGeometry(300, 300, 400, 520)
        
        self.check_env()
        self.init_ui()
        self.load_config()
        
        self.monitor = DockerMonitor()
        self.monitor.status_signal.connect(self.update_power_light)
        self.monitor.start()

    def check_env(self):
        if not os.path.exists(CONFIG_PATH):
            QMessageBox.critical(self, "错误", f"找不到配置文件：\n{CONFIG_PATH}")
            sys.exit(1)

    def init_ui(self):
        layout = QVBoxLayout()
        btn_font = QFont("Microsoft YaHei", 9, QFont.Bold)
        
        # --- 1. 状态指示 ---
        grp_status = QGroupBox("📊 运行状态")
        lay_status = QHBoxLayout()
        lay_status.addStretch()
        
        self.light_p = QLabel()
        self.light_p.setFixedSize(20, 20)
        self.light_p.setStyleSheet(STYLE_LIGHT_ON if False else STYLE_LIGHT_OFF)
        lay_status.addWidget(self.light_p)
        lay_status.addWidget(QLabel("Docker 电源状态"))
        
        lay_status.addStretch()
        grp_status.setLayout(lay_status)
        layout.addWidget(grp_status)

        # --- 2. 电源与日志控制 ---
        grp_ctrl = QGroupBox("🔌 电源与日志")
        lay_ctrl = QVBoxLayout()
        
        hbox_btn = QHBoxLayout()
        self.btn_start = QPushButton("▶ 启动电源")
        self.btn_start.setFont(btn_font)
        self.btn_start.clicked.connect(lambda: self.run_bg("docker compose up -d", "启动指令已发送"))
        
        self.btn_stop = QPushButton("⏹ 切断电源")
        self.btn_stop.clicked.connect(self.confirm_stop)
        
        hbox_btn.addWidget(self.btn_start)
        hbox_btn.addWidget(self.btn_stop)
        lay_ctrl.addLayout(hbox_btn)

        self.btn_logs = QPushButton("📜 查看实时运行日志 (Live Logs)")
        self.btn_logs.setStyleSheet("background-color: #ecf0f1; border: 1px solid #bdc3c7;")
        self.btn_logs.clicked.connect(self.view_logs)
        lay_ctrl.addWidget(self.btn_logs)
        
        self.btn_term = QPushButton("💻 打开命令行终端 (PowerShell)")
        self.btn_term.setStyleSheet("background-color: #34495e; color: white;")
        self.btn_term.clicked.connect(self.open_terminal)
        lay_ctrl.addWidget(self.btn_term)
        
        self.btn_restart = QPushButton("🔄 重启生效 (Restart)")
        self.btn_restart.clicked.connect(self.confirm_restart)
        lay_ctrl.addWidget(self.btn_restart)
        
        grp_ctrl.setLayout(lay_ctrl)
        layout.addWidget(grp_ctrl)

        # --- 3. 配置与实验室 ---
        grp_cfg = QGroupBox("⚙️ 配置与功能")
        lay_cfg = QVBoxLayout()
        
        self.chk_dry = QCheckBox("🛡️ 模拟盘 (Dry Run)")
        self.chk_dry.toggled.connect(self.toggle_dry)
        lay_cfg.addWidget(self.chk_dry)
        
        hbox_port = QHBoxLayout()
        hbox_port.addWidget(QLabel("代理端口:"))
        self.line_port = QLineEdit()
        self.btn_save_port = QPushButton("保存")
        self.btn_save_port.clicked.connect(self.save_port)
        hbox_port.addWidget(self.line_port)
        hbox_port.addWidget(self.btn_save_port)
        lay_cfg.addLayout(hbox_port)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        lay_cfg.addWidget(line)

        self.btn_lab = QPushButton("🧪 打开实验室 (回测/下载/优化)")
        self.btn_lab.setStyleSheet("font-weight: bold; padding: 6px;")
        self.btn_lab.clicked.connect(self.open_backtest_window)
        lay_cfg.addWidget(self.btn_lab)

        grp_cfg.setLayout(lay_cfg)
        layout.addWidget(grp_cfg)

        # --- 4. 快捷方式 ---
        grp_link = QGroupBox("🚀 快捷入口")
        lay_link = QHBoxLayout()
        b1 = QPushButton("🌐 FreqUI (网页)")
        b1.clicked.connect(lambda: webbrowser.open("http://127.0.0.1:8080"))
        b2 = QPushButton("📂 打开文件夹")
        b2.clicked.connect(lambda: subprocess.Popen(f'explorer "{APP_ROOT}"'))
        lay_link.addWidget(b1)
        lay_link.addWidget(b2)
        grp_link.setLayout(lay_link)
        layout.addWidget(grp_link)

        self.setLayout(layout)

    # --- 功能函数 ---
    def open_backtest_window(self):
        self.bt_window = BacktestWindow(self)
        self.bt_window.show()

    def open_terminal(self):
        subprocess.Popen(f'start powershell -NoExit -Command "cd \'{APP_ROOT}\'"', shell=True)

    @Slot(bool)
    def update_power_light(self, on):
        self.light_p.setStyleSheet(STYLE_LIGHT_ON if on else STYLE_LIGHT_OFF)
        self.light_p.setToolTip("运行中" if on else "已停止")

    def view_logs(self):
        cmd = f'start powershell -NoExit -Command "cd \'{APP_ROOT}\'; echo 正在连接日志...; docker compose logs -f"'
        subprocess.Popen(cmd, shell=True, cwd=APP_ROOT)

    def load_config(self):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            is_dry = data.get("dry_run", True)
            self.chk_dry.blockSignals(True)
            self.chk_dry.setChecked(is_dry)
            self.chk_dry.blockSignals(False)
            try:
                proxy = data.get("exchange", {}).get("ccxt_config", {}).get("proxies", {}).get("http", "")
                if ":" in proxy: self.line_port.setText(proxy.split(":")[-1].replace("/", ""))
            except: pass
        except: pass

    def toggle_dry(self, chk):
        if not chk:
            reply = QMessageBox.warning(self, "高能预警", 
                                        "🛑 切换到【实盘 (Live)】模式资金将面临风险！\n确定要继续吗？", 
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                self.chk_dry.setChecked(True)
                return
        self.update_json("dry_run", chk)
        QMessageBox.information(self, "保存", f"已切换为 {'模拟盘' if chk else '实盘'}，请点击【重启生效】。")

    def save_port(self):
        port = self.line_port.text().strip()
        if not port.isdigit(): return
        proxy_str = f"http://host.docker.internal:{port}"
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f: data = json.load(f)
            if "exchange" not in data: data["exchange"] = {}
            if "ccxt_config" not in data["exchange"]: data["exchange"]["ccxt_config"] = {"enableRateLimit": True}
            data["exchange"]["ccxt_config"]["proxies"] = {"http": proxy_str, "https": proxy_str}
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "成功", "端口已保存，请点击【重启生效】。")
        except Exception as e: QMessageBox.critical(self, "错误", str(e))

    def update_json(self, k, v):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f: d=json.load(f)
            d[k]=v
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f: json.dump(d,f,indent=4,ensure_ascii=False)
            return True
        except Exception as e: return False

    def run_bg(self, cmd, msg):
        threading.Thread(target=lambda: subprocess.run(cmd,shell=True,cwd=APP_ROOT,creationflags=subprocess.CREATE_NO_WINDOW)).start()
        if msg: QMessageBox.information(self,"提示",msg)

    def confirm_stop(self):
        if QMessageBox.question(self,"关机","确定彻底关闭机器人电源吗？")==QMessageBox.Yes: 
            self.run_bg("docker compose down","已发送关机指令")

    def confirm_restart(self):
        if QMessageBox.question(self,"重启","确定重启容器吗？")==QMessageBox.Yes:
            subprocess.Popen(f'start powershell -NoExit -Command "cd \'{APP_ROOT}\'; docker compose restart; echo 重启完成"', shell=True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = FreqtradeManager()
    w.show()
    sys.exit(app.exec())