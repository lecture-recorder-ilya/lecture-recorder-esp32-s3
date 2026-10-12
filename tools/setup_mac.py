"""Set up a checkout without modifying running services or recording data."""
import subprocess,sys,venv
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
work=ROOT/'work';work.mkdir(exist_ok=True)
for name,requirements in [('ai-env','requirements-ai.txt'),('esp-check-env','requirements-recorder.txt'),('vision-env','requirements-vision.txt')]:
 target=work/name
 if not (target/'bin/python').exists():venv.EnvBuilder(with_pip=True).create(target)
 subprocess.run([str(target/'bin/python'),'-m','pip','install','-r',str(ROOT/'outputs/recorder'/requirements)],check=True)
asr=work/'asr-env'
if not asr.exists():asr.symlink_to('ai-env',target_is_directory=True)
print('Окружения готовы. Следующий шаг: tools/download_models.py и tools/build_mac.py.')
