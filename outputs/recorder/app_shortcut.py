from pathlib import Path


def install_shortcut(project, applications):
    target = project / 'outputs/Запись лекций.app'
    applications.mkdir(parents=True, exist_ok=True)
    for name in ('Диктофон.app', 'Диктофон — локальная.app'):
        link = applications / name
        try:
            link.symlink_to(target, target_is_directory=True)
        except FileExistsError:
            try:
                if link.is_symlink() and link.samefile(target):
                    return link
            except OSError:
                pass
            continue
        return link
    return target


def refresh_installed_shortcut(project):
    home = Path.home()
    if project != home / 'Library/Application Support/Lecture Recorder/project':
        return
    try:
        install_shortcut(project, home / 'Applications')
    except OSError:
        return
