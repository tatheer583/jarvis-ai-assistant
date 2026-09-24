from PyInstaller.utils.hooks import copy_metadata
hiddenimports = ['_webrtcvad']
datas = copy_metadata('webrtcvad-wheels')
