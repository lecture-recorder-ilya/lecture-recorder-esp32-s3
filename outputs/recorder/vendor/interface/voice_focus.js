(() => {
  const node = (tag, text) => {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    return item;
  };
  const button = (text, handler) => {
    const item = node('button', text);
    item.type = 'button';
    item.className = 'secondary';
    item.addEventListener('click', handler);
    return item;
  };
  const time = value => Math.floor(value / 60) + ':' + String(Math.floor(value % 60)).padStart(2, '0');

  window.attachVoiceFocus = (card, name) => {
    const panel = node('details');
    panel.className = 'audio-enhancement voice-focus';
    const heading = node('summary', 'Выделить голос преподавателя');
    heading.className = 'enhancement-heading';
    const lead = node('p', 'Пробный режим для разговоров рядом. Выбери образец, где преподаватель говорит один. Сначала можно проверить 20 секунд с позиции основного плеера.');
    lead.className = 'muted';
    const controls = node('div');
    controls.className = 'enhancement-actions';
    const reference = node('select');
    reference.setAttribute('aria-label', 'Запись с образцом голоса');
    const offset = node('input');
    Object.assign(offset, {type:'number', min:'0', step:'0.1', value:'0'});
    const length = node('input');
    Object.assign(length, {type:'number', min:'3', max:'20', step:'0.1', value:'6'});
    const begin = node('label', 'Начало, с ');
    begin.append(offset);
    const span = node('label', 'Длина, с ');
    span.append(length);
    const sample = node('audio');
    sample.controls = true;
    sample.preload = 'none';
    sample.hidden = true;
    sample.setAttribute('aria-label', 'Выбранный образец голоса');
    const status = node('p');
    status.setAttribute('role', 'status');
    const output = node('div');
    let timer, currentId = '', sequence = 0, running = false;

    function params() {
      const start = offset.valueAsNumber, seconds = length.valueAsNumber;
      if (!Number.isFinite(start) || start < 0 || !(seconds >= 3 && seconds <= 20)) {
        throw new Error('Укажи начало и выбери длину образца от 3 до 20 секунд.');
      }
      return {file: name, reference: reference.value, start, end: +(start + seconds).toFixed(3)};
    }

    function clearSample() {
      sample.pause();
      sample.removeAttribute('src');
      sample.hidden = true;
    }

    function listReferences() {
      const selected = reference.value || name;
      const names = new Set([name, ...(typeof studyStatus !== 'undefined' ? studyStatus?.files || [] : [])]);
      reference.replaceChildren(...Array.from(names, file => {
        const option = node('option', file === name ? 'Эта запись' : (cards.get(file)?.lesson?.title || file));
        option.value = file;
        return option;
      }));
      reference.value = names.has(selected) ? selected : name;
      pick.disabled = reference.value !== name;
    }

    const pick = button('Взять с позиции плеера', () => {
      offset.value = (card.audio.currentTime || 0).toFixed(1);
      clearSample();
    });
    const preview = button('Послушать образец', async () => {
      try {
        const p = params();
        sample.src = '/recordings/' + encodeURIComponent(p.reference) + '?' + new URLSearchParams({start:p.start,end:p.end});
        sample.hidden = false;
        card.audio.pause();
        await sample.play();
      } catch (error) { status.textContent = error.message; }
    });
    const quick = button('Проверить 20 секунд', () => submit(true));
    const run = button('Разобрать запись целиком', () => submit(false));
    async function submit(excerpt) {
      const request = ++sequence;
      clearTimeout(timer);
      try {
        const body = params();
        if (excerpt) body.clip_start = card.audio.currentTime || 0;
        running = true;
        run.disabled = quick.disabled = true;
        clearSample();
        const value = await post('/voice-focus', body);
        if (request === sequence) show(value);
      } catch (error) {
        if (request === sequence) { running = false; run.disabled = quick.disabled = false; status.textContent = error.message; }
      }
    }
    function show(value) {
      running = value.status === 'processing';
      run.disabled = quick.disabled = running || !value.available;
      const readyMessage = value.match === 'not_found' ? 'Голос по этому образцу не подтверждён. Попробуй другой отрывок.' :
        value.match === 'partial' ? 'Готово частично. На отмеченных отрезках плеер воспроизводит оригинал.' :
        'Готово. Голос можно сверить с оригиналом на том же моменте.';
      status.textContent = value.message || (value.status === 'ready' ? readyMessage :
        value.available ? '' : 'Локальный модуль голоса ещё не установлен на этом Mac.');
      if (value.audio && currentId !== value.audio) {
        currentId = value.audio;
        output.replaceChildren();
        const title = node('p', value.match === 'not_found' ? 'Исходная дорожка' : 'Дорожка по образцу');
        const selected = value.reference === name ? 'эта запись' : value.reference;
        const base = value.offset || 0;
        const period = Number.isFinite(value.until) ? ' · Разбор ' + time(base) + '–' + time(value.until) : '';
        const metadata = node('p', 'Образец — ' + selected + ', ' + time(value.start) + '–' + time(value.end) + period);
        metadata.className = 'muted';
        const player = node('audio');
        Object.assign(player, {controls:true, preload:'metadata', src:value.audio});
        player.setAttribute('aria-label', 'Выделенный голос');
        player.onplay = () => { card.audio.pause(); sample.pause(); };
        const playAt = (media, at) => {
          const other = media === player ? card.audio : player;
          other.pause();
          sample.pause();
          const seek = () => { media.currentTime = at; media.play().catch(() => {status.textContent='Нажми воспроизведение в плеере.';}); };
          if (media.readyState >= 1) seek();
          else { media.addEventListener('loadedmetadata', seek, {once:true}); media.load(); }
        };
        const compare = button('Сверить с оригиналом', () => playAt(card.audio, base + (player.currentTime || 0)));
        const resume = button('Вернуться к голосу', () => {
          const at = card.audio.currentTime || 0;
          playAt(player, at >= base && (!value.until || at < value.until) ? at - base : 0);
        });
        output.append(title, metadata, player, compare, resume);
        const transcript = node('details');
        transcript.append(node('summary','Текст и таймкоды'));
        const rows = [...(value.segments || [])];
        for (const clip of value.unsure || []) rows.push({...clip, text:'Проверить голос по оригиналу', uncertain:true});
        rows.sort((a,b) => a.start - b.start);
        if (!rows.length) transcript.append(node('p', 'Не удалось уверенно выделить фразы по этому образцу.'));
        for (const row of rows) {
          const entry = node('p');
          entry.append(button(time(row.start), () => playAt(row.uncertain ? card.audio : player, row.uncertain ? row.start : row.start - base)),
            document.createTextNode(' ' + row.text));
          transcript.append(entry);
        }
        output.append(transcript);
      }
      if (!value.audio && currentId) { currentId = ''; output.replaceChildren(); }
      clearTimeout(timer);
      if (running && panel.open && panel.isConnected) timer = setTimeout(check, 1800);
    }
    async function check() {
      const request = ++sequence;
      try {
        const response = await fetch('/voice-focus?' + new URLSearchParams({file:name}), {cache:'no-store'});
        const value = await response.json();
        if (!response.ok) throw new Error(value.error || 'Не удалось проверить разбор.');
        if (request === sequence) show(value);
      } catch (error) { if (request === sequence) status.textContent = error.message; }
    }
    reference.onchange = () => { offset.value = '0'; pick.disabled = reference.value !== name; clearSample(); };
    offset.onchange = length.onchange = clearSample;
    card.audio.addEventListener('play', () => {sample.pause(); output.querySelector('audio')?.pause();});
    sample.addEventListener('play', () => {card.audio.pause(); output.querySelector('audio')?.pause();});
    controls.append(reference, begin, span, pick, preview, quick, run);
    panel.append(heading, lead, controls, sample, status, output);
    panel.ontoggle = () => {
      if (panel.open) { listReferences(); check(); }
      else { clearTimeout(timer); sample.pause(); output.querySelector('audio')?.pause(); }
    };
    card.playerDock.after(panel);
  };
})();
