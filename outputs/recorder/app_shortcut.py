from pathlib import Path


def links_to(link, target):
    try:
        return link.is_symlink() and link.samefile(target)
    except OSError:
        return False


def install_shortcut(project, applications):
    target = project / 'outputs/Запись лекций.app'
    applications.mkdir(parents=True, exist_ok=True)
    for name in ('зу.app', 'зу — локальная.app'):
        link = applications / name
        try:
            link.symlink_to(target, target_is_directory=True)
        except FileExistsError:
            if links_to(link, target):
                return link
        else:
            return link
    for name in ('Коса.app', 'Коса — локальная.app', 'Диктофон.app', 'Диктофон — локальная.app', 'На полях.app', 'На полях — локальная.app', 'Запись лекций.app'):
        link = applications / name
        if links_to(link, target):
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
