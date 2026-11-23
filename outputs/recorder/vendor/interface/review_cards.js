(() => {
  const instances = new WeakMap();
  const make = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const button = (text, action) => {
    const element = make('button', text);
    element.type = 'button';
    element.addEventListener('click', action);
    return element;
  };
  const timeLabel = seconds => {
    const total = Math.max(0, Math.floor(seconds));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
  };
  async function request(url, body, signal) {
    const response = await fetch(url, body === undefined ? {signal} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), signal
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || 'Не удалось сохранить карточку');
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function mount(host, {file, onSeek} = {}) {
    instances.get(host)?.destroy();
    const controller = new AbortController();
    const root = make('section', undefined, 'review-cards');
    root.setAttribute('aria-label', 'Карточки этой записи');
    const heading = make('h3', 'Карточки для повторения');
    const status = make('p', '', 'review-cards-status');
    status.setAttribute('role', 'status');
    const retry = button('Повторить сохранение', () => savePending());
    retry.hidden = true;
    const form = make('form', undefined, 'review-cards-form');
    const question = make('textarea');
    question.rows = 2;
    question.maxLength = 4000;
    question.required = true;
    const answer = make('textarea');
    answer.rows = 3;
    answer.maxLength = 8000;
    answer.required = true;
    const source = make('select');
    const preview = make('blockquote', '', 'review-cards-quote');
    preview.hidden = true;
    const sourceNote = make('p', '', 'review-cards-source-note');
    const submit = make('button', 'Сохранить карточку');
    submit.type = 'submit';
    const reload = button('Обновить фразы', () => refresh());
    for (const [title, control] of [['Вопрос', question], ['Ответ', answer], ['Фраза из расшифровки', source]]) {
      const label = make('label', title);
      control.setAttribute('aria-label', title);
      label.append(control);
      form.append(label);
    }
    form.append(preview, sourceNote, reload, submit);
    const review = make('section', undefined, 'review-cards-session');
    root.append(heading, form, status, retry, review);
    host.append(root);
    let cards = [], sources = [], queue = [], revealed = false, pending = null, confirming = false;
    let busy = false, disposed = false, loaded = false, generation = 0;

    function availability() {
      submit.disabled = !loaded || busy || Boolean(pending);
      reload.disabled = busy || Boolean(pending);
      for (const control of [question, answer, source]) control.disabled = busy || Boolean(pending);
      retry.disabled = busy;
    }
    function sourcePreview() {
      const selected = sources.find(item => item.key === source.value);
      preview.hidden = !selected;
      preview.textContent = selected?.quote || '';
      sourceNote.textContent = selected?.source_note
        ? selected.source_note
        : sources.length ? 'Цитата и время сохранятся дословно.' : 'Расшифровки пока нет. Карточку можно сохранить без цитаты.';
    }
    function sourceChoices() {
      const selected = source.value;
      source.replaceChildren();
      const empty = make('option', 'Без цитаты');
      empty.value = '';
      source.append(empty);
      for (const item of sources) {
        const option = make('option', `${timeLabel(item.start)} · ${item.quote.slice(0, 140)}`);
        option.value = item.key;
        source.append(option);
      }
      source.value = sources.some(item => item.key === selected) ? selected : '';
      sourcePreview();
    }
    function renderReview() {
      review.replaceChildren();
      heading.textContent = `Карточки для повторения · ${cards.length}`;
      const card = cards.find(item => item.id === queue[0]);
      if (!card) {
        review.append(make('p', cards.length ? 'Повторение закончено.' : 'Добавь вопрос и ответ по этой записи.'));
        if (cards.length) review.append(button('Повторить все', () => {
          queue = cards.map(item => item.id);
          revealed = false;
          renderReview();
        }));
        return;
      }
      review.append(make('p', `Осталось: ${queue.length}`, 'review-cards-progress'), make('h4', card.question));
      if (confirming) {
        const confirmation = make('div', undefined, 'review-cards-grades');
        confirmation.append(make('p', 'Удалить эту карточку?'), button('Удалить карточку', () => {
          mutate({action: 'delete', card_id: card.id}, () => {
            cards = cards.filter(item => item.id !== card.id);
            queue = queue.filter(id => id !== card.id);
            revealed = false;
            confirming = false;
          });
        }), button('Отмена', () => { confirming = false; renderReview(); }));
        for (const control of confirmation.querySelectorAll('button')) control.disabled = busy || Boolean(pending);
        review.append(confirmation);
        return;
      }
      const remove = button('Удалить', () => { confirming = true; renderReview(); });
      remove.disabled = busy || Boolean(pending);
      review.append(remove);
      const citation = card.source;
      if (citation) {
        const verified = citation.source_status === 'confirmed';
        const listen = button(verified ? `К звуку · ${timeLabel(citation.start)}` : 'Источник нужно сверить', async () => {
          try {
            const latest = await request('/review-cards?file=' + encodeURIComponent(file), undefined, controller.signal);
            if (disposed) return;
            cards = latest.cards;
            const anchor = cards.find(item => item.id === card.id)?.source;
            if (anchor?.source_status !== 'confirmed') {
              status.textContent = 'Источник изменился. Нужно сверить цитату.';
              renderReview();
              return;
            }
            await onSeek(anchor.start, anchor.end);
            renderReview();
          } catch (error) { if (!disposed) status.textContent = error.message; }
        });
        listen.disabled = !verified || typeof onSeek !== 'function';
        review.append(listen);
        if (citation.source_note || !verified) review.append(make('p', citation.source_note || 'Источник нужно сверить.', 'review-cards-source-note'));
      }
      if (!revealed) {
        const flip = button('Показать ответ', () => { revealed = true; renderReview(); });
        flip.disabled = busy || Boolean(pending);
        review.append(flip);
        return;
      }
      review.append(make('p', card.answer, 'review-cards-answer'));
      if (citation) review.append(make('blockquote', citation.quote, 'review-cards-quote'));
      const grades = make('div', undefined, 'review-cards-grades');
      for (const [label, result] of [['Помню', 'remember'], ['Ещё раз', 'again']]) {
        const grade = button(label, () => mutate({action: 'review', card_id: card.id, result}, data => {
          cards = data.card ? cards.map(item => item.id === card.id ? data.card : item) : cards.filter(item => item.id !== card.id);
          queue = queue.filter(id => id !== card.id);
          if (data.card && result === 'again') queue.push(card.id);
          revealed = false;
          renderReview();
        }));
        grade.disabled = busy || Boolean(pending);
        grades.append(grade);
      }
      review.append(grades);
    }
    async function savePending() {
      if (busy || !pending || disposed) return;
      busy = true;
      status.textContent = 'Сохраняю…';
      retry.hidden = true;
      availability();
      renderReview();
      try {
        const data = await request('/review-cards', pending.body, controller.signal);
        if (disposed) return;
        const done = pending.done;
        pending = null;
        busy = false;
        done(data);
        status.textContent = data.deleted ? 'Карточка удалена.' : 'Сохранено на этом Mac.';
      } catch (error) {
        if (disposed) return;
        status.textContent = error.message;
        if (error.status >= 400 && error.status < 500) pending = null;
        retry.hidden = !pending;
      } finally {
        busy = false;
        if (!disposed) { availability(); renderReview(); }
      }
    }
    function mutate(body, done) {
      if (pending || busy) return;
      pending = {body: {...body, file, request_id: crypto.randomUUID()}, done};
      savePending();
    }
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (!question.value.trim() || !answer.value.trim()) return;
      mutate({action: 'create', question: question.value, answer: answer.value, source_key: source.value || null}, data => {
        if (!data.card) return;
        if (!cards.some(card => card.id === data.card.id)) cards.push(data.card);
        if (!queue.includes(data.card.id)) queue.push(data.card.id);
        question.value = '';
        answer.value = '';
        source.value = '';
        sourcePreview();
        revealed = false;
      });
    });
    source.addEventListener('change', sourcePreview);

    async function refresh() {
      const current = ++generation;
      try {
        const data = await request('/review-cards?file=' + encodeURIComponent(file), undefined, controller.signal);
        if (disposed || current !== generation) return;
        cards = data.cards;
        sources = data.sources;
        queue = cards.map(card => card.id);
        revealed = false;
        confirming = false;
        loaded = true;
        status.textContent = '';
        sourceChoices();
        renderReview();
        availability();
      } catch (error) {
        if (!disposed) status.textContent = error.message;
      }
    }
    const api = {refresh, destroy() {
      disposed = true;
      controller.abort();
      root.remove();
      if (instances.get(host) === api) instances.delete(host);
    }};
    instances.set(host, api);
    availability();
    refresh();
    return api;
  }
  window.ClipMicReviewCards = {mount};
})();
