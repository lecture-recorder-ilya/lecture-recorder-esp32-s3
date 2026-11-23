(() => {
  'use strict';

  function formatTime(seconds) {
    const ms = Math.round(seconds * 1000);
    const minutes = Math.floor(ms / 60000);
    const whole = String(Math.floor(ms / 1000) % 60).padStart(2, '0');
    const fraction = String(ms % 1000).padStart(3, '0').replace(/0+$/, '');
    return minutes + ':' + whole + (fraction ? ',' + fraction : '');
  }

  function parseTime(text) {
    const parts = text.trim().replace(',', '.').split(':');
    if (parts.length > 3 || !parts.every((part, i) =>
      (i === parts.length - 1 ? /^\d+(?:\.\d{1,3})?$/ : /^\d+$/).test(part)
      && (i === 0 || Number(part) < 60))) return NaN;
    return parts.reduce((value, part) => value * 60 + Number(part), 0);
  }

  function attach(card, name) {
    const audio = card.audio;
    const panel = el('details', undefined, 'clip-fragment');
    const heading = el('summary', 'Фрагмент записи');
    const area = el('div', undefined, 'clip-fragment-body');
    const fields = el('div', undefined, 'clip-fragment-fields');
    const actions = el('div', undefined, 'clip-fragment-actions');
    const repeat = el('button', 'Повторять фрагмент', 'secondary');
    repeat.type = 'button';
    const download = el('a', 'Сохранить WAV');
    const notice = el('p', '', 'clip-fragment-status');
    notice.setAttribute('role', 'status');

    function field(label) {
      const column = el('div');
      const caption = el('label', label);
      const input = el('input');
      input.type = 'text';
      input.autocomplete = 'off';
      input.placeholder = '0:00';
      const here = el('button', 'Из плеера', 'secondary');
      here.type = 'button';
      here.setAttribute('aria-label', label + ' на текущей позиции');
      here.onclick = () => {
        input.value = formatTime(audio.currentTime || 0);
        edited();
      };
      input.addEventListener('input', edited);
      caption.append(input);
      column.append(caption, here);
      fields.append(column);
      return {input, here};
    }

    const left = field('Начало');
    const right = field('Конец');
    actions.append(repeat, download);
    area.append(fields, actions, notice);
    panel.append(heading, area);
    card.playerDock.after(panel);

    let looping = false;
    let initialized = false;
    let timer = 0;
    const key = 'clip-fragment:' + name;

    function bounds() {
      const start = parseTime(left.input.value);
      const end = parseTime(right.input.value);
      return Number.isFinite(audio.duration) && start >= 0 && end > start
        && end <= audio.duration + 0.0005 ? {start, end: Math.min(end, audio.duration)} : null;
    }
    function paint() {
      const value = bounds();
      repeat.disabled = !value;
      repeat.textContent = looping ? 'Остановить повтор' : 'Повторять фрагмент';
      repeat.setAttribute('aria-pressed', String(looping));
      download.setAttribute('aria-disabled', String(!value));
      if (value) {
        const query = new URLSearchParams({start: value.start, end: value.end});
        download.href = '/recordings/' + encodeURIComponent(name) + '?' + query;
        download.download = name.replace(/\.wav$/i, '') + '-' + Math.round(value.start * 1000)
          + '-' + Math.round(value.end * 1000) + 'ms.wav';
        notice.textContent = (looping ? 'Повтор · ' : 'Длительность · ') + formatTime(value.end - value.start);
      } else {
        download.removeAttribute('href');
        notice.textContent = audio.error ? 'Не удалось открыть аудиозапись.' :
          !Number.isFinite(audio.duration) ? 'Читаю длительность записи…' :
          'Введи время в минутах и секундах. Конец должен быть позже начала и в пределах записи.';
      }
      left.here.disabled = right.here.disabled = !Number.isFinite(audio.duration);
    }
    function stop(pause) {
      clearTimeout(timer);
      if (!looping) return;
      looping = false;
      if (pause) audio.pause();
      paint();
    }
    function edited() {
      stop(false);
      const value = bounds();
      if (value) {
        try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
      }
      paint();
    }
    function ready() {
      if (!panel.open) return;
      if (!initialized && Number.isFinite(audio.duration) && audio.duration > 0) {
        let saved;
        try { saved = JSON.parse(localStorage.getItem(key)); } catch {}
        const duration = audio.duration;
        const valid = Number.isFinite(saved?.start) && Number.isFinite(saved?.end)
          && saved.start >= 0 && saved.start < saved.end && saved.end <= duration + 0.0005;
        const here = Math.max(0, audio.currentTime || 0);
        const start = valid ? saved.start : here >= duration - 0.001 ? 0 : here;
        left.input.value = formatTime(start);
        right.input.value = formatTime(valid ? saved.end : Math.min(duration, start + 15));
        initialized = true;
      }
      paint();
    }
    function playStart() {
      const value = bounds();
      if (!looping || !value) return;
      audio.currentTime = value.start;
      audio.play().catch(() => {
        if (!looping) return;
        stop(false);
        notice.textContent = 'Не удалось начать повтор. Проверь звук в плеере.';
      });
    }
    function schedule() {
      clearTimeout(timer);
      const value = bounds();
      if (!looping || !value || audio.paused || audio.seeking) return;
      if (audio.currentTime >= value.end) playStart();
      else timer = setTimeout(schedule, Math.min(2000, Math.max(16,
        (value.end - audio.currentTime) * 1000 / (audio.playbackRate || 1))));
    }
    repeat.onclick = () => {
      if (looping) return stop(true);
      if (!bounds()) return;
      looping = true;
      paint();
      playStart();
    };
    panel.addEventListener('toggle', () => {
      if (!panel.open) return stop(true);
      window.LectureWorkflow?.bindAudio(card);
      if (!audio.readyState && audio.preload === 'none') {
        audio.preload = 'metadata';
        audio.load();
      }
      ready();
    });
    card.details.addEventListener('toggle', () => {
      if (!card.details.open) stop(true);
    });
    for (const event of ['loadedmetadata', 'durationchange', 'error']) audio.addEventListener(event, ready);
    for (const event of ['playing', 'ratechange', 'timeupdate']) audio.addEventListener(event, schedule);
    audio.addEventListener('seeked', () => {
      const value = bounds();
      if (looping && value && (audio.currentTime + 0.002 < value.start || audio.currentTime > value.end + 0.002)) {
        stop(false);
      } else schedule();
    });
    audio.addEventListener('pause', () => {
      if (!audio.ended) stop(false);
    });
    audio.addEventListener('ended', playStart);
    audio.addEventListener('emptied', () => stop(false));
    paint();
  }

  window.AudioFragment = {attach};
})();
