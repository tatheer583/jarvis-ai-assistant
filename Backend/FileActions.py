"""Explicit local file actions. Existing destinations are never overwritten."""
import os
import shutil
from pathlib import Path
from Backend.ActionResult import ActionResult
from Backend.Tasks import checkpoint

class FileActions:
    def __init__(self, config, index):
        self.config, self.index = config, index

    def resolve(self, value, *, existing=True):
        from Backend.Desktop import known_folder
        value = self.config.settings.aliases.get(value.casefold(), value)
        folder = known_folder(value)
        if folder:
            path = folder
        else:
            path = Path(os.path.expandvars(value)).expanduser()
            if not path.is_absolute():
                hits = self.index.search(value)
                hits = [h for h in hits if h['score'] >= 0.9 and Path(h['path']).exists()]
                if len(hits) != 1:
                    raise ValueError('Give the complete path or a saved voice name so I can choose the exact file.')
                path = Path(hits[0]['path'])
        path = path.resolve()
        if existing and not path.exists():
            raise ValueError('That file or folder is unavailable.')
        return path

    def protected(self, path):
        from Backend.Config import PROJECT_DIR
        from Backend.Desktop import known_folder
        roots = [Path(path.anchor), Path.home(), PROJECT_DIR, self.config.directory]
        roots.extend(known_folder(name) for name in ('desktop', 'documents', 'downloads', 'pictures', 'music', 'videos'))
        system = [Path(os.environ[name]).resolve() for name in ('WINDIR', 'PROGRAMFILES', 'PROGRAMDATA', 'ProgramFiles(x86)') if os.environ.get(name)]
        return any(root and path == root.resolve() for root in roots) or any(path == root or path.is_relative_to(root) for root in system)

    def execute(self, operation, source, destination='', *, confirmed=False):
        try:
            checkpoint()
            if operation in {'create_folder', 'create_file'}:
                base = self.resolve(destination)
                if not base.is_dir():
                    raise ValueError('Choose an existing destination folder.')
                if not source or Path(source).name != source or source in {'.', '..'} or any(c in source for c in '<>:"/\\|?*'):
                    raise ValueError('Use a simple file or folder name without path characters.')
                if base == self.config.directory.resolve() or base.is_relative_to(self.config.directory.resolve()):
                    raise ValueError("Use Settings to manage Jarvis application data.")
                target = base / source
                if target.exists():
                    raise ValueError('That name already exists. Choose a different name.')
                if operation == 'create_folder':
                    target.mkdir()
                else:
                    with target.open('x', encoding='utf-8'):
                        pass
                return ActionResult.ok('file_action', f'Created {target.name}.', path=str(target), verification='verified')
            origin = self.resolve(source)
            if origin == self.config.directory.resolve() or origin.is_relative_to(self.config.directory.resolve()):
                raise ValueError('Jarvis internal data cannot be changed through file commands.')
            if operation in {'move', 'rename', 'recycle'} and self.protected(origin):
                raise ValueError('Choose an individual personal file or subfolder for this action.')
            if operation == 'recycle':
                if not confirmed:
                    return ActionResult.ok('confirmation', f'Move {origin.name} to the Recycle Bin? Say yes or no.',
                                           confirmation=True, file_confirmation={'source': str(origin), 'operation': operation})
                from win32com.shell import shell, shellcon
                result, aborted = shell.SHFileOperation((0, shellcon.FO_DELETE, str(origin) + '\0', None,
                    shellcon.FOF_ALLOWUNDO | shellcon.FOF_NOCONFIRMATION | shellcon.FOF_NOERRORUI | shellcon.FOF_SILENT, None, None))
                if result or aborted:
                    raise OSError('Windows did not recycle the item.')
                return ActionResult.ok('file_action', f'Moved {origin.name} to the Recycle Bin.')
            if operation == 'rename':
                if Path(destination).name != destination or destination in {'', '.', '..'} or any(c in destination for c in '<>:"/\\|?*'):
                    raise ValueError('Give only the new name for a rename operation.')
                target = origin.with_name(destination)
            else:
                folder = self.resolve(destination)
                if not folder.is_dir():
                    raise ValueError('Choose an existing destination folder.')
                if folder == self.config.directory.resolve() or folder.is_relative_to(self.config.directory.resolve()):
                    raise ValueError('Use Settings to manage Jarvis application data.')
                target = folder / origin.name
            if target.exists():
                raise ValueError('The destination already exists. I have not overwritten it.')
            if origin.is_dir() and target.resolve().is_relative_to(origin):
                raise ValueError('Choose a destination outside the source folder.')
            if operation == 'copy':
                if origin.is_dir():
                    shutil.copytree(origin, target, symlinks=True, copy_function=self._copy_file)
                else:
                    self._copy_file(origin, target)
            elif operation in {'move', 'rename'}:
                shutil.move(str(origin), str(target))
            else:
                raise ValueError('Unknown file operation.')
            checkpoint()
            if not target.exists() or (operation in {'move', 'rename'} and origin.exists()):
                raise OSError('The expected file change could not be verified.')
            return ActionResult.ok('file_action', f'{operation.title()} completed: {target.name}.', path=str(target), verification='verified')
        except Exception as exc:
            return ActionResult.fail('file_action', str(exc))

    @staticmethod
    def _copy_file(source, destination):
        checkpoint()
        # Exclusive creation also prevents a race from overwriting a new destination.
        with open(source, 'rb') as reader, open(destination, 'xb') as writer:
            while True:
                checkpoint()
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                writer.write(chunk)
        checkpoint()
        shutil.copystat(source, destination)
        if os.path.getsize(source) != os.path.getsize(destination):
            raise OSError('Copied file size could not be verified.')
        return str(destination)
