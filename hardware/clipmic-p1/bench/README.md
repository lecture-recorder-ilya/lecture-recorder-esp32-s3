# Проверка диктофона

Для сравнения двух записей запусти `python3 compare.py esp.wav phone.wav --reference reference.wav --distance 1`. Инструмент ожидает PCM16 и две синхрометки в эталоне.

Чтобы собрать локальный эталон, из корня проекта выполни `python3 tools/prepare_public_asr.py work/p1-source --skip 36 --count 1`, затем `python3 hardware/clipmic-p1/bench/make_reference.py work/p1-source/fleurs-37-clean.wav hardware/clipmic-p1/bench/reference.wav`. Источник речи — [русская тестовая выборка FLEURS, CC BY 4.0](https://huggingface.co/datasets/google/fleurs).
