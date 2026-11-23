const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {randomUUID} = require('node:crypto');

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.listeners = {}; this.value = ''; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(child => child.textContent).join(''); }
  append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
  replaceChildren(...children) { this.children = []; this.text = ''; this.append(...children); }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(item => item !== this); }
  querySelectorAll(tag) { return this.children.flatMap(child => [...(child.tagName === tag ? [child] : []), ...child.querySelectorAll(tag)]); }
  click() { assert(!this.disabled, `disabled ${this.textContent}`); return this.listeners.click?.({preventDefault() {}}); }
}

const source = {key: 'source12345', quote: 'Икс не равен пяти.', start: 1.125, end: 3.875, source_status: 'confirmed'};
const initial = {id: 'card12345678', question: 'Условие?', answer: 'СКРЫТЫЙ ОТВЕТ <img onerror=alert(1)>', source, review_count: 0};
let saved = [structuredClone(initial)], sources = [structuredClone(source)], failure = '', posts = [], requests = new Map();
const fetch = async (url, options = {}) => {
  if (!options.body) return {ok: true, json: async () => ({cards: structuredClone(saved), sources: structuredClone(sources)})};
  const body = JSON.parse(options.body);
  posts.push(body);
  if (failure === '400') { failure = ''; return {ok: false, status: 400, json: async () => ({error: 'Расшифровка изменилась'})}; }
  let result = requests.get(body.request_id);
  if (!result) {
    if (body.action === 'create') {
      result = {card: {...initial, id: randomUUID(), question: body.question, answer: body.answer, source: body.source_key ? source : null}};
      saved.push(result.card);
    } else if (body.action === 'review') {
      const card = saved.find(item => item.id === body.card_id);
      card.review_count++;
      result = {card: structuredClone(card)};
    } else {
      saved = saved.filter(item => item.id !== body.card_id);
      result = {card: null, deleted: true};
    }
    requests.set(body.request_id, result);
  }
  if (failure === 'lost') { failure = ''; throw new Error('Ответ потерян'); }
  return {ok: true, json: async () => structuredClone(result)};
};
const context = {window: {}, document: {createElement: tag => new Element(tag)}, fetch,
                 crypto: {randomUUID}, AbortController, console};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../outputs/recorder/vendor/interface/review_cards.js'), 'utf8'), context);
const tick = () => new Promise(resolve => setImmediate(resolve));
const host = new Element('div');
const all = tag => host.querySelectorAll(tag);
const findButton = label => all('button').find(item => item.textContent === label);
const visibleText = node => node.hidden ? '' : (node.text || '') + node.children.map(visibleText).join('');
const submit = async () => { all('form')[0].listeners.submit({preventDefault() {}}); await tick(); };

(async () => {
  const seeks = [];
  let api = context.window.ClipMicReviewCards.mount(host, {file: 'lecture.wav', onSeek: (...times) => seeks.push(times)});
  await tick();
  assert(!visibleText(host).includes(initial.answer));
  assert(!findButton('Помню'));
  await findButton('К звуку · 0:01').click();
  assert.deepEqual(seeks, [[1.125, 3.875]]);
  findButton('Показать ответ').click();
  assert(visibleText(host).includes(initial.answer));
  assert.equal(all('img').length, 0);
  findButton('Ещё раз').click();
  await tick();
  assert(!visibleText(host).includes(initial.answer));
  assert.equal(saved[0].review_count, 1);
  findButton('Удалить').click();
  assert(findButton('Удалить карточку'));
  findButton('Отмена').click();
  assert.equal(posts.filter(item => item.action === 'delete').length, 0);

  all('textarea')[0].value = 'Новая карточка?';
  all('textarea')[1].value = 'Новый ответ';
  failure = 'lost';
  await submit();
  assert(!findButton('Повторить сохранение').hidden);
  assert(all('textarea')[0].disabled);
  const originalRequest = posts.at(-1).request_id;
  findButton('Повторить сохранение').click();
  await tick();
  assert.equal(posts.at(-1).request_id, originalRequest);
  assert.equal(saved.length, 2);
  assert.equal(all('textarea')[0].value, '');

  all('textarea')[0].value = 'Исправить?';
  all('textarea')[1].value = 'Сохранённый черновик';
  failure = '400';
  await submit();
  assert.equal(all('textarea')[0].value, 'Исправить?');
  assert(!all('textarea')[0].disabled);
  assert(!all('select')[0].disabled);
  assert(findButton('Повторить сохранение').hidden);
  findButton('Обновить фразы').click();
  await tick();
  assert.equal(all('textarea')[1].value, 'Сохранённый черновик');
  assert.equal(all('select')[0].children.length, 2);

  saved[0].source = {quote: source.quote, source_status: 'needs_review'};
  await findButton('К звуку · 0:01').click();
  assert.equal(seeks.length, 1);
  assert(findButton('Источник нужно сверить').disabled);
  findButton('Удалить').click();
  findButton('Удалить карточку').click();
  await tick();
  assert.equal(saved.length, 1);
  api.destroy();
  assert.equal(host.children.length, 0);

  sources = [];
  api = context.window.ClipMicReviewCards.mount(host, {file: 'lecture.wav'});
  await tick();
  assert(!visibleText(host).includes('Новый ответ'));
  assert(visibleText(host).includes('Расшифровки пока нет'));
  findButton('Показать ответ').click();
  findButton('Помню').click();
  await tick();
  assert(visibleText(host).includes('Повторение закончено'));
  findButton('Повторить все').click();
  assert(!visibleText(host).includes('Новый ответ'));
  api.destroy();
  console.log('PASS: hidden answer, exact seek, retry after lost reply, editable 400, refreshed sources, confirmation, deletion, remount and empty transcript');
})().catch(error => { console.error(error); process.exitCode = 1; });
