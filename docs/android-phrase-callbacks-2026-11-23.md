# Готовые фразы Android относительно f38fd91

Проверены исходники `f38fd91a210e13c56bf8a38b6ab04f8794dda7cd`. Пять ASR-файлов PhoneGigaAm, PhonePhrases, PhoneCtc, PhoneSpeechWindow и PcmWave совпадают побайтово с измеренным head PR `f5d87339ba6f5bfd42edd58d5318150d041a888c`. Доказательство — `work/android-pr2-asr/results/callback-source-check.json`.

В f38 уже есть минимальные точки:

- `PhonePhrases` принимает Consumer<JSONObject>. В `flush()` он собирает готовые start/end/text/needs_review/word_times, добавляет объект в segments и вызывает onPhrase.accept(phrase), затем очищает текущий буфер.
- GigaAM создаёт `new PhonePhrases(job.preview::addPhrase)`; callback вызывается при принятии завершённых слов и делении на фразы, до возврата transcribe.
- `PhoneLectureAnalysis.transcribeVosk` создаёт такой же PhonePhrases. Вход для готовых слов — acceptWaveForm == true, затем getResult и phrases.accept(result); последний результат принимается после getFinalResult.

У Vosk слова getResult обычно приходят без точки в конце. Короткий хвост PhonePhrases может ждать следующего слова с паузой или окончания всего файла. Для немедленной выдачи полностью законченного endpoint после его accept можно вызвать phrases.finish(): в этой реализации это только flush + возврат накопленного массива, объект допускает дальнейший accept. Вариант с отдельным именованным методом сброса endpoint имеет ту же границу. Промежуточные partial-гипотезы не являются этими готовыми результатами. Реальный Vosk здесь не запускался: готового локального vosk-model-small-ru-0.22 в проверенных каталогах нет. Есть JAR, наличие JAR не означает наличие весов.

При переносе callback на наш main нужно сохранить его условие uncertain с speech_conf и путь PhoneWordTimeline. Изменение callback не требует менять параллельность или повторять модельные проходы. Обработчику публикации следует копировать JSONObject, если UI может его редактировать: исходный объект также хранится в итоговых segments. Файлы исполнителя Job/экрана не менялись.

## Реальный GigaAM

Штатный GigaAM-v3-e2e-CTC int8, SHA256 `2e3fcb7a7b66030336fd10c2fcfb033bd1dc7e1bf238fe5cfd83b1d0cfc9d28e`; штатные frontend и токены из f5d87339. Mac M2 / 16 GiB, JDK 21, настольный ONNX Runtime JNI 1.24.3, четыре intra-op потока. В этом существующем PR-коде при 137,95175 с входа включаются два worker. Его параллельность не менялась.

Один фиксированный WAV — синтетическая склейка 24 открытых фрагментов по порядку с паузами 0,25 с. В каждом из трёх повторов callback пришёл до завершения метода:

| Повтор | Первый callback, с | Возврат метода, с | Готовых фраз |
|---|---:|---:|---:|
| 0 | 3,062910 | 7,064781 | 31 |
| 1 | 2,349689 | 6,819769 | 31 |
| 2 | 2,045266 | 6,655588 | 31 |

Текст и сегменты повторились точно. Это готовые гипотезы ASR с метками сомнения, не человеческое подтверждение правильности. Проверено время вызова callback заглушки Job.preview; время экрана и реального телефона не измерено. В измеренном срезе main 186b41e без callback первый массив доступен при возврате метода; повторные времена 13,867583 / 6,946674 / 6,141730 с на том же WAV. Эти числа не являются доказательством ускорения от параллельности: сама публикация и алгоритмы версий различаются.

## Существующий стенд

Скрипт: `work/android-pr2-asr/ours/tools/compare_android_asr.py`. Заглушка поддерживает и старый preview::addPhrase, и новый job::publishPhrase; оба пути учитываются одним счётчиком. Это отдельно проверено test_android_comparison_harness.py без моделей. Готовый лог: `work/android-pr2-asr/results/ilya-long.jsonl`, полный отчёт `ilya-long.json`. Одинаковые поля main — `ours-long.json`. Данные — `work/android-pr2-asr/fixture/long-manifest.json`. Повтор при необходимости только этого одного WAV, без повторения 267:

```sh
bench_repo="${CLIPMIC_BENCH_REPO:-$(git rev-parse --show-toplevel)}"
bench_task="$bench_repo/work/android-pr2-asr"
PYTHONDONTWRITEBYTECODE=1 "$bench_repo/work/asr-env/bin/python" "$bench_task/ours/tools/compare_android_asr.py" run \
  "$bench_task/fixture/long-manifest.json" --source "$bench_task/ilya" \
  --deps "$bench_repo/work/lecture-profile-local-asr/asr-check" \
  --jdk "$bench_repo/work/publish-0.5.5/toolchain/jdk-21.0.13.1+2/Contents/Home" \
  --model "$bench_repo/work/models/gigaam/v3_e2e_ctc.int8.onnx" \
  --repeats 1 --output "$bench_task/results/callback-new-run.json"
```

Чтобы проверить свою копию, заменить только --source на нужный worktree. Он должен предоставлять тот же контракт Context/Store/Job, используемый в заглушке стенда. Новых модельных вычислений для этой записки не запускалось: использованы готовые длинные A/B и проверка исходников.

По умолчанию команда выполняется из основной рабочей копии с готовыми work/asr-env и work/android-pr2-asr. При запуске из другого worktree задайте CLIPMIC_BENCH_REPO корнем этой основной копии.
