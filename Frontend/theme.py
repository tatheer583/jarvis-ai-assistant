STYLE = """
QMainWindow, QWidget#Root { background: #0b1018; color: #e9f1fa; }
QWidget { color: #e9f1fa; font-family: 'Segoe UI'; font-size: 14px; }
QFrame#Sidebar { background: #101722; border-right: 1px solid #233044; }
QFrame#Card { background: #121c29; border: 1px solid #263449; border-radius: 16px; }
QLabel#Eyebrow { color: #69e2ca; font-size: 11px; font-weight: 600; letter-spacing: 2px; }
QLabel#Title { font-size: 28px; font-weight: 600; color: #f1f6ff; }
QLabel#Heading { font-size: 19px; font-weight: 600; }
QLabel#Muted { color: #95a9c3; }
QLabel#Status { color: #69e2ca; font-size: 14px; }
QPushButton { background: #192637; border: 1px solid #304258; padding: 10px 16px; border-radius: 9px; font-weight: 600; }
QPushButton:hover { background: #24364b; border-color: #6588a2; }
QPushButton:disabled { color: #65758a; background: #15202e; border-color: #253145; }
QPushButton#Primary { background: #6ee7cf; color: #09211d; border: 1px solid #6ee7cf; }
QPushButton#Primary:hover { background: #9cf5e2; }
QPushButton#Primary:checked { background: #d89282; color: #24100d; border-color: #d89282; }
QPushButton#Nav { background: transparent; border: none; text-align: left; padding: 13px 17px; color: #a3b4cb; }
QPushButton#Nav:checked { background: #1b2f36; color: #82ebd5; }
QPushButton#Nav:hover { background: #1a2534; }
QLineEdit, QComboBox, QSpinBox, QTextEdit, QTextBrowser, QListWidget {
    background: #0e1622; border: 1px solid #2a3a50; border-radius: 9px; padding: 9px; selection-background-color: #2d6d65;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #6ee7cf; }
QComboBox QAbstractItemView { background: #162131; color: #e9f1fa; selection-background-color: #2b5c58; }
QListWidget::item { padding: 9px; border-bottom: 1px solid #223047; }
QListWidget::item:selected { background: #214039; color: #9ff4df; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #101824; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #3b4e64; min-height: 30px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QGroupBox { border: 1px solid #263449; border-radius: 12px; margin-top: 14px; padding: 18px 12px 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #456078; border-radius: 4px; background: #132030; }
QCheckBox::indicator:checked { background: #6ee7cf; border-color: #6ee7cf; }
QProgressBar { border: none; background: #243447; border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { background: #6ee7cf; border-radius: 3px; }
QToolTip { color: #e9f1fa; background: #203047; border: 1px solid #3d566c; padding: 6px; }
QMenu { background: #152233; border: 1px solid #2b4258; }
QMenu::item { padding: 8px 22px; }
QMenu::item:selected { background: #28554e; }
"""
