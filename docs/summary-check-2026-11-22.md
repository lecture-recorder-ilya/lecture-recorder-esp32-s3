# Проверка конспекта и домашки

База: `68f22367e5f496b157d1fb3607aa93e5dfdd37cc`. Сравнение с ней и `v0.5.9` сделано на одних сохранённых ответах. ASR, интерфейс и релиз не менялись.

Исправлены отмена ДЗ, перенос срока в следующей строке, потерянное отрицание и неподтверждённые числа в формуле. Сомнительные цитаты и явные обрывки не становятся уверенными пунктами. Объяснение формулы принимается только как цитата. После правки исходных слов прежние срок и LaTeX сбрасываются; новая расшифровка также сбрасывает старые формулы.

Проверены 75 Python-тестов и Android JVM с настоящими `PhoneSummaryEvidence`, `TranscriptEdits`, `LectureNotes` и файловым хранилищем. Android API в тесте заменён минимальным контекстом. Проверены ручные правки конспекта Mac и телефона, цитаты, неизменные временные границы, смена сегментов, отдельный перезапуск JVM и чтение старого конспекта из файловой истории. На Mac добавлено сохранение прежнего JSON в `analysis/history/<имя>/<SHA256>.json` до замены; ошибки записи проверены отдельно. Интерфейс просмотра истории не проверялся.

## Контрольные данные

- OpenSTT: 36 исходных фрагментов лекций, 36 копий с добавленными шумом и отражениями, две синтетические дорожки без речи. MD5 исходного архива `184a4d0a2016f8f5359bd4365a488fe5`; субтитры сверены с архивом, PCM — с повторной конвертацией и указанной обработкой.
- mTEDx: 18 реальных публичных выступлений с исходным фоном. Parquet SHA256 `636b6437749db49bfad10e628945fc284afee33c75f874f8a1462b4b8b7a6eb9`; WAV, субтитры, ревизия и исходные интервалы сверены повторной подготовкой из Parquet.
- 22 короткие искусственные ловушки находятся в `tests/fixtures/summary/traps.json`. Это фиксированные ответы, а не генерации модели.

| Контроль | v0.5.9 | База 68f2236 | Эта правка |
| --- | ---: | ---: | ---: |
| Ловушки с несовпавшими ожиданиями, Mac | 15 | 13 | 0 |
| Ловушки с несовпавшими ожиданиями, Android JVM | 4 | 4 | 0 |
| Выданные пункты OpenSTT, Mac | 73 | 71 | 24 |
| Выданные пункты OpenSTT, Android JVM | 38 | 38 | 36 |
| Выданные пункты mTEDx, Mac | 27 | 27 | 16 |
| Выданные пункты mTEDx, Android JVM | 20 | 20 | 20 |

Пункты считались при фиксированном выборе первых четырёх строк. Это проверка фильтра, а не качества выбора моделью. Во всех версиях цитаты, ID и временные границы принятых пунктов совпали с поданными строками. ДЗ на этих реальных фрагментах не появилось. Уменьшение числа пунктов показывает более строгий отбор; полнота конспекта не измерена.

Отдельный живой прогон локальной Qwen2.5-7B при temperature=0 завершил два шумных фрагмента OpenSTT пустыми списками summary/homework. Полные ответы сохранены в `work/next-summary-check/live-model.json`; незавершённый третий ответ после прерывания паузы бюджета не учитывался. Искусственная ловушка повторена отдельным прогоном без пауз бюджета (26,6 с): модель ошибочно вернула отменённое ДЗ, новый фильтр его отвергает. Ответ находится в `live-model-remaining.json`; три полных ответа объединены в `live-model-complete.json`. Настройки приложения не менялись. Android-модель не запускалась: в JVM подаются явно фиксированные KEY/TASK.

## Происхождение пункта

Пункт получает отпечаток строк-источников. После сдвига или новой нарезки сегментов уникальная полная цитата перепривязывается к текущим ID и временным границам. При пропаже, сомнении или нескольких совпадениях активный старый таймкод снимается, а текст пункта помечается «Источник нужно сверить». Первоначальные цитата и границы остаются в `original_source`. Ручная отметка проверки учитывается до сверки привязки. Сверка сделана одинаково на Mac и в JVM; общий SHA-256 проверен отдельной регрессией. Уверенность в точности самих ASR-таймкодов по звуку не добавляется.

Проверки: `work/test_summary_sources.py` (6 сценариев), `work/test_phone_summary_state.py` (JVM: сдвиг, дробление цитаты, неоднозначность, восстановление), `work/test_phone_sync.py` (9 тестов), `work/test_lecture_workflow.py` (20 тестов).

## Что остаётся открытым

Субтитры подтверждают произнесённый текст с ограничениями разметки, но не истинность слов лектора. Временные границы ASR не размечались человеком заново. Расстояние до микрофона неизвестно; запись реальной пары с последнего ряда не проверена. В этих корпусных фрагментах нет размеченных реальных ДЗ и формул: для них используются искусственные регрессии. Проверки формулы не доказывают математическую эквивалентность произвольных выражений. Перенос срока ищется в пределах двух следующих строк с промежутком до двух секунд. Нужны проверки на телефоне и с реальными участниками.

## Как повторить

Выполнять из отдельной рабочей копии. `clipmic_repo` — корень общего репозитория, `PY` — существующая среда с numpy; для Parquet используется существующая среда с pyarrow.

```sh
clipmic_repo=/Users/vm/Documents/ChatGPT/esp/lecture-recorder-esp32-s3-main
PY="$clipmic_repo/work/ai-env/bin/python"
export JAVA_HOME=/Users/vm/Documents/ChatGPT/esp/.build-tools/jdk/jdk-17.0.20.1+1/Contents/Home
export ANDROID_JSON_JAR="$clipmic_repo/work/lecture-profile-local-asr/asr-check/android-json.jar"
"$PY" work/test_summary_evidence.py
"$PY" work/test_next_summary.py
"$PY" work/test_phone_summary_state.py
"$PY" tools/prepare_summary_checks.py "$clipmic_repo/work/rear-row/corpus/wav/holdout.json" "$clipmic_repo/work/rear-row/runs/edges-holdout.json" --archive "$clipmic_repo/work/rear-row/corpus/openstt-lecture.tar.gz" --output work/next-summary-check/real-fixed.json
"$PY" tools/prepare_summary_checks.py "$clipmic_repo/work/clipmic-asr-quality/results/mtedx/clips/manifest.json" "$clipmic_repo/work/rear-row/runs/edges-mtedx.json" --mtedx-parquet "$clipmic_repo/work/clipmic-asr-quality/results/mtedx/ru-test.parquet" --parquet-python "$clipmic_repo/work/clipmic-asr-quality/results/data-venv/bin/python" --output work/next-summary-check/mtedx-fixed.json
"$PY" tools/compare_summary_filters.py tests/fixtures/summary/traps.json --baseline v0.5.9 --baseline 68f2236 --output work/next-summary-check/traps-compare.json
"$PY" tools/compare_summary_filters.py work/next-summary-check/real-fixed.json --baseline v0.5.9 --baseline 68f2236 --output work/next-summary-check/real-compare.json
"$PY" tools/compare_summary_filters.py work/next-summary-check/mtedx-fixed.json --baseline v0.5.9 --baseline 68f2236 --output work/next-summary-check/mtedx-compare.json
```
