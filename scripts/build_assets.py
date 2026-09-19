import os
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
from PyQt5.QtWidgets import QApplication
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtCore import Qt
from PIL import Image
folder=Path(__file__).resolve().parent.parent/'desktop/src-tauri/icons'
folder.mkdir(parents=True,exist_ok=True)
svg='<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256"><rect x="8" y="8" width="240" height="240" rx="57" fill="#16211b"/><rect x="9" y="9" width="238" height="238" rx="57" fill="none" stroke="#54745e" stroke-width="2"/><g fill="#b0e9c9" transform="translate(20 0) skewX(-9)"><rect x="71" y="103" width="16" height="63" rx="8"/><rect x="102" y="63" width="16" height="130" rx="8"/><rect x="133" y="84" width="16" height="99" rx="8"/><rect x="164" y="111" width="16" height="50" rx="8"/></g></svg>'
(folder/'icon.svg').write_text(svg,encoding='utf-8')
app=QApplication([])
canvas=QImage(256,256,QImage.Format_ARGB32)
canvas.fill(Qt.transparent)
painter=QPainter(canvas)
QSvgRenderer(svg.encode()).render(painter)
painter.end()
canvas.save(str(folder/'icon.png'))
Image.open(folder/'icon.png').save(folder/'icon.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('App icons ready.')
