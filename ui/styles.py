STYLESHEET = r"""
* {
    font-family: "Segoe UI Variable", "Segoe UI";
    font-size: 10.5pt;
    color: #F2F5F7;
}
QMainWindow, QDialog, QWidget#root {
    background: #0E1116;
}
QWidget {
    background: transparent;
}
QFrame#sidebar {
    background: #171C24;
    border-right: 1px solid #2A3340;
}
QFrame#compactNav {
    background: #171C24;
    border-bottom: 1px solid #2A3340;
}
QFrame#compactNav QPushButton {
    padding: 5px 7px;
}
QFrame#compactNav QPushButton:checked {
    background: #253650;
    border-color: #3A8DFF;
}
QLabel#brand {
    font-size: 19pt;
    font-weight: 700;
    color: #FFFFFF;
}
QLabel#pageTitle {
    font-size: 22pt;
    font-weight: 650;
    color: #FFFFFF;
}
QLabel#muted, QLabel.muted {
    color: #9BA6B2;
}
QLabel#previewTitle {
    font-size: 16pt;
    font-weight: 600;
}
QListWidget#navigation {
    background: transparent;
    border: none;
    outline: none;
    padding: 4px 10px;
}
QListWidget#navigation::item {
    color: #9BA6B2;
    padding: 11px 12px;
    margin: 2px 0;
    border-radius: 6px;
}
QListWidget#navigation::item:hover {
    background: #202733;
    color: #F2F5F7;
}
QListWidget#navigation::item:selected {
    background: #253650;
    color: #FFFFFF;
}
QFrame#preview {
    background: #171C24;
    border: 1px solid #303A48;
    border-radius: 6px;
}
QLabel#error {
    color: #FFB4B4;
}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTreeWidget {
    background: #171C24;
    border: 1px solid #303A48;
    border-radius: 5px;
    padding: 8px 10px;
    selection-background-color: #3A8DFF;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QTreeWidget:focus {
    border: 2px solid #3A8DFF;
    padding: 7px 9px;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox QAbstractItemView {
    background: #202733;
    border: 1px solid #3A4657;
    selection-background-color: #2C5F9F;
}
QPushButton {
    background: #202733;
    border: 1px solid #344052;
    border-radius: 5px;
    padding: 8px 14px;
    font-weight: 550;
}
QPushButton:hover {
    background: #293342;
    border-color: #506078;
}
QPushButton:focus {
    border: 2px solid #74ADFF;
    padding: 7px 13px;
}
QPushButton:disabled {
    color: #697482;
    background: #171C24;
    border-color: #262E39;
}
QPushButton#primary {
    background: #3A8DFF;
    border-color: #3A8DFF;
    color: #FFFFFF;
}
QPushButton#primary:hover {
    background: #59A0FF;
}
QPushButton#danger {
    color: #FFB4B4;
    border-color: #734242;
}
QGroupBox {
    border: none;
    border-top: 1px solid #2A3340;
    margin-top: 16px;
    padding-top: 18px;
    font-size: 11pt;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 0;
    padding-right: 10px;
    color: #F2F5F7;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #506078;
    border-radius: 3px;
    background: #171C24;
}
QCheckBox::indicator:checked {
    background: #3A8DFF;
    border-color: #3A8DFF;
}
QHeaderView::section {
    background: #171C24;
    color: #9BA6B2;
    border: none;
    border-bottom: 1px solid #303A48;
    padding: 8px;
    font-weight: 600;
}
QTreeWidget {
    padding: 0;
    alternate-background-color: #141920;
}
QTreeWidget::item {
    padding: 8px 5px;
    border-bottom: 1px solid #222A35;
}
QTreeWidget::item:selected {
    background: #253650;
}
QProgressBar {
    background: #202733;
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: #3A8DFF;
    border-radius: 3px;
}
QScrollArea {
    border: none;
}
QScrollBar:vertical {
    background: #10141A;
    width: 11px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #3A4657;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QStatusBar {
    background: #171C24;
    color: #9BA6B2;
    border-top: 1px solid #2A3340;
}
QToolTip {
    background: #202733;
    color: #F2F5F7;
    border: 1px solid #506078;
    padding: 5px;
}
"""

HIGH_CONTRAST_STYLESHEET = r"""
* { color: #FFFFFF; }
QMainWindow, QDialog, QWidget#root, QFrame#sidebar, QFrame#compactNav,
QFrame#preview, QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTreeWidget {
    background: #000000;
    color: #FFFFFF;
    border-color: #FFFFFF;
}
QLabel#muted { color: #FFFFFF; }
QPushButton, QComboBox { border: 2px solid #FFFFFF; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 3px solid #FFFF00;
}
QPushButton#primary { background: #FFFF00; border-color: #FFFF00; color: #000000; }
QPushButton:disabled { color: #AAAAAA; border-color: #AAAAAA; }
"""
