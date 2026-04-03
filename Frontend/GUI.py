from PyQt5.QtWidgets import (
      QApplication, QMainWindow, QTextEdit, QStackedWidget,
      QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
      QFrame, QLabel, QSizePolicy, QLineEdit
)
from PyQt5.QtGui import (
      QIcon, QPainter, QMovie, QColor, QTextCharFormat,
      QFont, QPixmap, QTextBlockFormat, QTextCursor
)
from PyQt5.QtCore import Qt, QSize, QTimer
from dotenv import dotenv_values
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_vars = dotenv_values(os.path.join(BASE_DIR, ".env"))
Assistantname = env_vars.get("AssistantName", "Assistant")
old_chat_message = ""
TempDirPath = os.path.join(BASE_DIR, "Frontend", "Files")
GraphicsDirPath = os.path.join(BASE_DIR, "Frontend", "Graphics")
RUNTIME_FILES = {
      "Mic.data": "False",
      "Status.data": "Available...",
      "Responses.data": "",
      "Database.data": "",
      "TextInput.data": "",
}


def EnsureRuntimeFiles():
      os.makedirs(TempDirPath, exist_ok=True)
      for filename, default_value in RUNTIME_FILES.items():
            file_path = os.path.join(TempDirPath, filename)
            if not os.path.exists(file_path):
                  with open(file_path, "w", encoding="utf-8") as file:
                        file.write(default_value)


EnsureRuntimeFiles()


def AnswerModifier(Answer):
      lines = Answer.split('\n')
      non_empty_lines = [line for line in lines if line.strip()]
      return '\n'.join(non_empty_lines)


def QueryModifier(Query):
      new_query = Query.lower().strip()
      query_words = new_query.split()
      question_words = ["how", "what", "who", "when", "whose", "whom", "what's", "where's", "how's"]

      if any(word + " " in new_query for word in question_words):
            if query_words[-1][-1] in [',', '?', '!']:
                  new_query = new_query[:-1] + "?"
            else:
                  new_query += "?"
      else:
            if query_words[-1][-1] in ['.', '?', '!']:
                  new_query = new_query[:-1] + "."
            else:
                  new_query += "."

      return new_query.capitalize()


def SetMicrophoneStatus(Command):
      with open(os.path.join(TempDirPath, "Mic.data"), "w", encoding='utf-8') as file:
            file.write(Command)


def GetMicrophoneStatus():
      try:
            with open(os.path.join(TempDirPath, "Mic.data"), "r", encoding='utf-8') as file:
                  return file.read().strip()
      except FileNotFoundError:
            return "False"


def SetAssistantStatus(Status):
      with open(os.path.join(TempDirPath, "Status.data"), "w", encoding='utf-8') as file:
            file.write(Status)


def GetAssistantStatus():
      try:
            with open(os.path.join(TempDirPath, "Status.data"), "r", encoding='utf-8') as file:
                  return file.read().strip()
      except FileNotFoundError:
            return "Available..."


def MicButtonInitialed():
      SetMicrophoneStatus("False")


def MicButtonClosed():
      SetMicrophoneStatus("True")


def GraphicsDirectoryPath(Filename):
      return os.path.join(GraphicsDirPath, Filename)


def TempDirectoryPath(Filename):
      return os.path.join(TempDirPath, Filename)


def showTextToScreen(Text):
      with open(TempDirectoryPath("Responses.data"), "w", encoding='utf-8') as file:
            file.write(Text)


def appendTextToScreen(Text):
      file_path = TempDirectoryPath("Responses.data")
      existing = ""
      try:
            with open(file_path, "r", encoding="utf-8") as file:
                  existing = file.read().strip()
      except FileNotFoundError:
            pass

      new_text = Text.strip()
      if not new_text:
            return

      combined = f"{existing}\n{new_text}".strip() if existing else new_text
      with open(file_path, "w", encoding="utf-8") as file:
            file.write(combined)


def SetTextInput(Text):
      with open(TempDirectoryPath("TextInput.data"), "w", encoding="utf-8") as file:
            file.write(Text.strip())


def GetTextInput():
      try:
            with open(TempDirectoryPath("TextInput.data"), "r", encoding="utf-8") as file:
                  return file.read().strip()
      except FileNotFoundError:
            return ""


def GetScreenSize():
      screen = QApplication.primaryScreen()
      if screen:
            geo = screen.geometry()
            return geo.width(), geo.height()
      return 1920, 1080


def LoadGif(label, gif_name, width, height, fallback_name="jarvise.jpg"):
      gif_path = GraphicsDirectoryPath(gif_name)
      if os.path.exists(gif_path):
            movie = QMovie(gif_path)
            movie.setScaledSize(QSize(width, height))
            movie.setParent(label)
            label.setMovie(movie)
            movie.start()
            return movie
      else:
            fallback_path = GraphicsDirectoryPath(fallback_name)
            if os.path.exists(fallback_path):
                  pixmap = QPixmap(fallback_path)
                  label.setPixmap(pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation))  # type: ignore[attr-defined]
      return None


class TextInputBar(QWidget):

      def __init__(self, placeholder="Type a message to Jarvis and press Send."):
            super().__init__()
            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 8, 12, 8)
            layout.setSpacing(10)

            self.input_field = QLineEdit()
            self.input_field.setPlaceholderText(placeholder)
            self.input_field.returnPressed.connect(self.submit_text)
            self.input_field.setStyleSheet("""
                  QLineEdit {
                        background-color: #111111;
                        color: white;
                        border: 1px solid #333333;
                        border-radius: 10px;
                        padding: 10px 12px;
                        font-size: 13px;
                  }
            """)

            self.send_button = QPushButton("Send")
            self.send_button.clicked.connect(self.submit_text)
            self.send_button.setStyleSheet("""
                  QPushButton {
                        background-color: white;
                        color: black;
                        border-radius: 10px;
                        padding: 10px 18px;
                        font-weight: bold;
                  }
                  QPushButton:hover {
                        background-color: #dddddd;
                  }
            """)

            layout.addWidget(self.input_field)
            layout.addWidget(self.send_button)

      def submit_text(self):
            text = self.input_field.text().strip()
            if not text:
                  return
            SetTextInput(text)
            SetAssistantStatus("Typed message ready...")
            SetMicrophoneStatus("True")
            self.input_field.clear()


class ChatSection(QWidget):

      def __init__(self):
            super(ChatSection, self).__init__()
            layout = QVBoxLayout(self)
            layout.setContentsMargins(-10, 40, 40, 100)
            layout.setSpacing(-10)

            self.chat_text_edit = QTextEdit()
            self.chat_text_edit.setReadOnly(True)
            self.chat_text_edit.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)  # type: ignore[attr-defined]
            self.chat_text_edit.setFrameStyle(QFrame.NoFrame)
            self.chat_text_edit.setPlaceholderText("Your conversation with Jarvis will appear here.")
            layout.addWidget(self.chat_text_edit)

            layout.setSizeConstraint(QVBoxLayout.SetDefaultConstraint)  # type: ignore[attr-defined]
            layout.setStretch(1, 1)
            self.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))

            text_color = QColor(Qt.blue)  # type: ignore[attr-defined]
            text_color_text = QTextCharFormat()
            text_color_text.setForeground(text_color)
            self.chat_text_edit.setCurrentCharFormat(text_color_text)

            self.gif_label = QLabel()
            self.gif_label.setStyleSheet("border: none;")
            self._movie = LoadGif(self.gif_label, 'jarvis.gif', 480, 270)
            self.gif_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)  # type: ignore[attr-defined]
            layout.addWidget(self.gif_label)

            self.label = QLabel("")
            self.label.setStyleSheet("color: white; font-size: 16px; margin-right: 195px; border: none; margin-top: -30px;")
            self.label.setAlignment(Qt.AlignRight)  # type: ignore[attr-defined]
            layout.addWidget(self.label)

            font = QFont()
            font.setPointSize(13)
            self.chat_text_edit.setFont(font)

            self._last_responses_mtime = 0
            self._last_status_mtime = 0

            self.timer = QTimer(self)
            self.timer.timeout.connect(self.loadMessages)
            self.timer.timeout.connect(self.SpeechRecogText)
            self.timer.start(1000)

            self.setStyleSheet("""
                  background-color: black;
                  QScrollBar:vertical {
                        border: none;
                        background: black;
                        width: 10px;
                        margin: 0px;
                  }
                  QScrollBar::handle:vertical {
                        background: white;
                        min-height: 20px;
                  }
                  QScrollBar::add-line:vertical {
                        background: black;
                        subcontrol-position: bottom;
                        subcontrol-origin: margin;
                        height: 10px;
                  }
                  QScrollBar::sub-line:vertical {
                        background: black;
                        subcontrol-position: top;
                        subcontrol-origin: margin;
                        height: 10px;
                  }
                  QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
                        border: none;
                        background: none;
                        color: none;
                  }
                  QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                        background: none;
                  }
            """)

      def loadMessages(self):
            global old_chat_message
            file_path = TempDirectoryPath('Responses.data')
            try:
                  mtime = os.path.getmtime(file_path)
            except OSError:
                  return
            if mtime == self._last_responses_mtime:
                  return
            self._last_responses_mtime = mtime

            try:
                  with open(file_path, "r", encoding='utf-8') as file:
                        messages = file.read()
            except (FileNotFoundError, IOError):
                  return

            if not messages or len(messages) <= 1:
                  return
            if str(old_chat_message) == str(messages):
                  return

            self.chat_text_edit.setPlainText(messages)
            self.chat_text_edit.moveCursor(QTextCursor.End)  # type: ignore[arg-type]
            old_chat_message = messages

      def SpeechRecogText(self):
            try:
                  with open(TempDirectoryPath('Status.data'), "r", encoding='utf-8') as file:
                        messages = file.read()
                        self.label.setText(messages)
            except (FileNotFoundError, IOError):
                  pass

      def addMessage(self, message, color):
            cursor = self.chat_text_edit.textCursor()
            char_format = QTextCharFormat()
            block_format = QTextBlockFormat()
            block_format.setTopMargin(10)
            block_format.setLeftMargin(10)
            char_format.setForeground(QColor(color))
            cursor.setCharFormat(char_format)
            cursor.setBlockFormat(block_format)
            cursor.insertText(message + "\n")
            self.chat_text_edit.setTextCursor(cursor)


class InitialScreen(QWidget):

      def __init__(self, parent=None):
            super().__init__(parent)
            screen_width, screen_height = GetScreenSize()

            content_layout = QVBoxLayout()
            content_layout.setContentsMargins(0, 0, 0, 0)

            gif_label = QLabel()
            max_gif_size_H = int(screen_width / 16 * 9)
            self._movie = LoadGif(gif_label, 'jarvis.gif', screen_width, max_gif_size_H)
            gif_label.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]
            gif_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

            self.icon_label = QLabel()
            pixmap = QPixmap(GraphicsDirectoryPath('Mic_on.png'))
            new_pixmap = pixmap.scaled(60, 60)
            self.icon_label.setPixmap(new_pixmap)
            self.icon_label.setFixedSize(150, 150)
            self.icon_label.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]

            self.label = QLabel("")
            self.label.setStyleSheet("color: white; font-size: 16px; margin-bottom: 0;")

            self.helper_label = QLabel("Click the microphone to start or pause Jarvis listening.")
            self.helper_label.setStyleSheet("color: #b8b8b8; font-size: 13px; margin-top: 4px;")
            self.helper_label.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]
            self.text_input_bar = TextInputBar("If voice is unavailable, type here and press Send.")
            self.toggled = GetMicrophoneStatus() == "True"
            self._apply_mic_visual_state()
            self.icon_label.mousePressEvent = self.toggle_icon  # type: ignore[assignment]

            content_layout.addWidget(gif_label, alignment=Qt.AlignCenter)  # type: ignore[attr-defined]
            content_layout.addWidget(self.label, alignment=Qt.AlignCenter)  # type: ignore[attr-defined]
            content_layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)  # type: ignore[attr-defined]
            content_layout.addWidget(self.helper_label, alignment=Qt.AlignCenter)  # type: ignore[attr-defined]
            content_layout.addWidget(self.text_input_bar)
            content_layout.setContentsMargins(0, 0, 0, 150)

            self.setLayout(content_layout)
            self.setFixedHeight(screen_height)
            self.setFixedWidth(screen_width)
            self.setStyleSheet("background-color: black;")

            self.timer = QTimer(self)
            self.timer.timeout.connect(self.SpeechRecogText)
            self.timer.timeout.connect(self.syncMicState)
            self.timer.start(750)

      def SpeechRecogText(self):
            try:
                  with open(TempDirectoryPath('Status.data'), "r", encoding='utf-8') as file:
                        messages = file.read()
                        self.label.setText(messages)
                        if "Voice unavailable" in messages:
                              self.helper_label.setText("Voice is unavailable. Type your message below and press Send.")
            except (FileNotFoundError, IOError):
                  pass

      def load_icon(self, path, width=60, height=60):
            pixmap = QPixmap(path)
            new_pixmap = pixmap.scaled(width, height)
            self.icon_label.setPixmap(new_pixmap)

      def syncMicState(self):
            active = GetMicrophoneStatus() == "True"
            if active == self.toggled:
                  return
            self.toggled = active
            self._apply_mic_visual_state()

      def _apply_mic_visual_state(self):
            if self.toggled:
                  self.load_icon(GraphicsDirectoryPath('Mic_off.png'), 60, 60)
                  self.helper_label.setText("Listening is on. Click the microphone to pause.")
            else:
                  self.load_icon(GraphicsDirectoryPath('Mic_on.png'), 60, 60)
                  self.helper_label.setText("Click the microphone to start or pause Jarvis listening.")

      def toggle_icon(self, event=None):
            self.toggled = not self.toggled
            self._apply_mic_visual_state()
            if self.toggled:
                  MicButtonClosed()
            else:
                  MicButtonInitialed()


class MessageScreen(QWidget):

      def __init__(self, parent=None):
            super().__init__(parent)
            screen_width, screen_height = GetScreenSize()

            layout = QVBoxLayout()
            label = QLabel("")
            layout.addWidget(label)
            chat_section = ChatSection()
            layout.addWidget(chat_section)
            layout.addWidget(TextInputBar())

            self.setLayout(layout)
            self.setStyleSheet("background-color: black;")
            self.setFixedHeight(screen_height)
            self.setFixedWidth(screen_width)


class CustomTopBar(QWidget):

      def __init__(self, parent, stacked_widget):
            super().__init__(parent)
            self.current_screen = None
            self.stacked_widget = stacked_widget
            self.draggable = True
            self.offset = None
            self.initUI()

      def initUI(self):
            self.setFixedHeight(50)
            layout = QHBoxLayout(self)
            layout.setAlignment(Qt.AlignRight)  # type: ignore[attr-defined]

            home_button = QPushButton()
            home_button.setIcon(QIcon(GraphicsDirectoryPath("Home.png")))
            home_button.setText(" Home")
            home_button.setStyleSheet("height: 40px; line-height: 40px; background-color: black;")

            message_button = QPushButton()
            message_button.setIcon(QIcon(GraphicsDirectoryPath("Chat.png")))
            message_button.setText(" Chat")
            message_button.setStyleSheet("height: 40px; background-color: white; color: black;")

            minimize_button = QPushButton()
            minimize_button.setIcon(QIcon(GraphicsDirectoryPath('Minimize2.png')))
            minimize_button.setStyleSheet("background-color: white;")
            minimize_button.clicked.connect(self.minimizeWindow)

            self.maximize_button = QPushButton()
            self.maximize_icon = QIcon(GraphicsDirectoryPath('Maximize.png'))
            self.restore_icon = QIcon(GraphicsDirectoryPath('Minimize.png'))
            self.maximize_button.setIcon(self.maximize_icon)
            self.maximize_button.setCheckable(True)
            self.maximize_button.setStyleSheet("background-color: white;")
            self.maximize_button.clicked.connect(self.maximizeWindow)

            close_button = QPushButton()
            close_button.setIcon(QIcon(GraphicsDirectoryPath('Close.png')))
            close_button.setStyleSheet("background-color: white;")
            close_button.clicked.connect(self.closeWindow)

            line_frame = QFrame()
            line_frame.setFixedHeight(1)
            line_frame.setFrameShape(QFrame.HLine)
            line_frame.setFrameShadow(QFrame.Sunken)
            line_frame.setStyleSheet("border-color: black;")

            title_label = QLabel(f" {str(Assistantname).capitalize()} AI  ")
            title_label.setStyleSheet("color: black; font-size: 18px; background-color: white;")

            home_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
            message_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))

            layout.addWidget(title_label)
            layout.addStretch(1)
            layout.addWidget(home_button)
            layout.addWidget(message_button)
            layout.addStretch(1)
            layout.addWidget(minimize_button)
            layout.addWidget(self.maximize_button)
            layout.addWidget(close_button)
            layout.addWidget(line_frame)

      def paintEvent(self, event):  # type: ignore[override]
            painter = QPainter(self)
            painter.fillRect(self.rect(), Qt.white)  # type: ignore[attr-defined]
            super().paintEvent(event)

      def minimizeWindow(self):
            self.parent().showMinimized()  # type: ignore[union-attr]

      def maximizeWindow(self):
            if self.parent().isMaximized():  # type: ignore[union-attr]
                  self.parent().showNormal()  # type: ignore[union-attr]
                  self.maximize_button.setIcon(self.maximize_icon)
            else:
                  self.parent().showMaximized()  # type: ignore[union-attr]
                  self.maximize_button.setIcon(self.restore_icon)

      def closeWindow(self):
            self.parent().close()  # type: ignore[union-attr]

      def mousePressEvent(self, event):  # type: ignore[override]
            if self.draggable:
                  self.offset = event.pos()

      def mouseMoveEvent(self, event):  # type: ignore[override]
            if self.draggable and self.offset:
                  new_pos = event.globalPos() - self.offset
                  self.parent().move(new_pos)  # type: ignore[union-attr]


class MainWindow(QMainWindow):

      def __init__(self):
            super().__init__()
            self.setWindowFlags(Qt.FramelessWindowHint)  # type: ignore[attr-defined]
            self.initUI()

      def initUI(self):
            screen_width, screen_height = GetScreenSize()
            stacked_widget = QStackedWidget(self)
            initial_screen = InitialScreen()
            message_screen = MessageScreen()
            stacked_widget.addWidget(initial_screen)
            stacked_widget.addWidget(message_screen)
            self.setGeometry(0, 0, screen_width, screen_height)
            self.setStyleSheet("background-color: black;")
            top_bar = CustomTopBar(self, stacked_widget)
            self.setMenuWidget(top_bar)
            self.setCentralWidget(stacked_widget)


def GraphicalUserInterface():
      app = QApplication(sys.argv)
      window = MainWindow()
      window.show()
      sys.exit(app.exec_())


if __name__ == "__main__":
      GraphicalUserInterface()

