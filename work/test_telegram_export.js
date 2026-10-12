const assert=require('node:assert/strict');
const api=require('../outputs/recorder/telegram_export.js');
const result={topic:'Пределы функций',subject:'Математический анализ',teacher:'Иван Иванов',overview:'Обсудили пределы и эквивалентности.',summary:['**Первый** важный вывод.','Второй вывод.'],homework:[{task:'Решить задачи 1–5.',deadline:'К следующей паре'}],formulas:[{latex:String.raw`\lim_{x\to 0}\frac{\sin(3x)}{x}=3`}],segments:[{text:'Первое предложение.'},{text:'Второе предложение.'}]};
let short=api.prepare(result,{},'lecture-2026-10-12-10-00-00.wav');assert.equal(short.parts.length,1);assert(short.parts[0].includes('12.10.2026'));assert(short.text.includes('• Первый важный вывод.'));assert(!short.text.includes('**'));assert(short.text.includes('К следующей паре'));assert(short.text.includes('lim (x→ 0) (sin(3x)) / (x)=3'));
const long={...result,segments:Array.from({length:300},(_,i)=>({text:`Уникальный фрагмент номер ${i}. `+'Содержательная фраза лекции. '.repeat(8)}))};
const data=api.prepare(long,{},'lecture-2026-10-12-10-00-00.wav',true);assert(data.parts.length>10);assert(data.parts.every(x=>x.length<=3900));assert(data.parts[0].includes('Часть 1/'));assert(data.parts.at(-1).includes('номер 299'));
const normalize=t=>t.replace(/\s+/g,' ').trim();const payload=data.parts.map(x=>x.slice(x.indexOf('\n\n')+2)).join(' ');assert.equal(normalize(payload),normalize(api.blocks(long,{},true)));
for(const value of ['🧑‍🔬'.repeat(3000),'я'.repeat(16000)]){const chunks=api.split(value,3700);assert(chunks.every(x=>x.length<=3700));assert.equal(chunks.join(''),value);assert(chunks.every(x=>!/[\uD800-\uDBFF]$/.test(x)&&!/^\u200d/.test(x)))}
assert.equal(api.formula(String.raw`x^{2}+x_{0}=\sqrt{\frac{4}{2}}`),'x²+x₀=√((4) / (2))');
assert.equal(api.prepare({segments:[]},{},'a.wav',true).parts.length,0);
const privateData={...result,recognition:{token:'should-not-export'},password:'secret'};assert(!api.prepare(privateData,{},'',true).text.includes('should-not-export'));assert(!api.prepare(privateData,{},'',true).text.includes('secret'));
console.log('PASS: readable text, complete lecture, bounded messages, Unicode, formulas, no private metadata');

assert(api.prepare({...result,draft:true,topic:'Текст текущей пары'},{subject:'Математика'},'',true).text.startsWith('📚 Математика'));
