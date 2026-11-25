const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2] || require('node:path').join(__dirname, '../index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const costJson = html.match(/<script id="cost-data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]);
assert.equal(new Set(ids).size, ids.length);
const elements = Object.fromEntries(ids.map(id => [id, {
  value: '', textContent: '', innerHTML: '', hidden: false, listeners: {},
  addEventListener(type, fn) { this.listeners[type] = fn; },
  setAttribute(name, value) { this[name] = value; },
  removeAttribute(name) { delete this[name]; },
  classList: { add() {}, remove() {}, toggle() {} },
  focus() {}, scrollIntoView() {}, showModal() {}, close() {}
}]));
elements['cost-data'].textContent = costJson;
assert.equal(JSON.parse(costJson).length, 1228);
for (const m of html.matchAll(/<input\b[^>]*>/g)) {
  const id = m[0].match(/\bid="([^"]+)"/)?.[1];
  if (id) elements[id].value = m[0].match(/\bvalue="([^"]*)"/)?.[1] || '';
}
elements['payment-method'].value = 'standard';
vm.runInNewContext(script, {
  document: { getElementById: id => elements[id], querySelectorAll: () => [], documentElement: {} },
  Intl, AbortController, setTimeout, clearTimeout,
  fetch: async () => ({ ok: true, json: async () => ({result:'success',base_code:'CNY',time_last_update_unix:1794355200,rates:{PHP:10,MYR:.5,THB:5,GBP:.1}}) })
});
const set = (id, value) => { elements[id].value = String(value); };
const out = id => elements[id].textContent;
const calc = () => elements.calculator.listeners.input();
const site = code => { set('site', code); elements.site.listeners.change(); };
const near = (a,b) => assert.ok(Math.abs(a-b)<1e-10, `${a} != ${b}`);
(async () => {
  await new Promise(resolve => setImmediate(resolve));
  site('MYR');
  assert.equal(elements.platform.value, '18.88');
  for (const [id,value] of Object.entries({price:100,cost:10,roi:0,commission:0,'loss-rate':0,'label-fee':0,flash:'no'})) set(id,value);
  calc();
  assert.equal(out('profit-local'), '70.7 MYR');
  assert.equal(out('paylater-fee'), '¥0.0');
  const threshold = Number(elements['break-even'].title.split(' ').at(-1));
  near(threshold, 100/70.72);
  set('payment-method','paylater'); set('buyer-shipping',10); calc();
  assert.equal(out('paylater-fee'), '¥2.4');
  assert.equal(out('profit-local'), '69.5 MYR');
  elements['lang-en'].listeners.click();
  assert.equal(out('profit-local'), '69.5 MYR');
  assert.equal(elements['payment-method'].value,'paylater');
  elements['lang-zh'].listeners.click();
  set('buyer-shipping',''); calc(); assert.match(out('status'),/请填写买家支付运费/);
  set('buyer-shipping',-1); calc(); assert.equal(out('profit-local'),'—');
  set('buyer-shipping',10);
  set('roi',10);set('commission',5);set('loss-rate',2);set('label-fee',3.5);set('target-margin',20);
  elements['mode-toggle'].listeners.click();
  const price = Number(out('pricing-local').split(' ')[0]);
  const margin = p => (p*(1-.1888-.0108-.0486-.05-.02-.1)-7.398)/p;
  assert.equal(price,Math.ceil(7.398/.3818*100)/100);
  assert.ok(margin(price)>=.2); assert.ok(margin(price-.01)<.2);
  elements['carry-price'].listeners.click();
  assert.ok(Number(out('margin').replace('%',''))>=20);
  set('payment-method','standard');set('buyer-shipping','');calc();
  assert.notEqual(out('profit-local'),'—');
  set('price',100);set('cost',0);set('roi',0);set('commission',0);set('loss-rate',0);set('label-fee',0);set('flash','yes'); elements.flash.listeners.change();calc();
  assert.equal(out('profit-local'),'73.6 MYR');
  set('payment-method','paylater');set('buyer-shipping',10);
  site('PHP');set('price',100);set('flash','no');set('label-fee',0);calc();
  assert.equal(elements.platform.value,'16.15');assert.equal(out('profit-local'),'78.9 PHP');assert.equal(out('paylater-fee'),'¥0.0');
  site('THB');set('price',100);set('flash','no');set('label-fee',0);calc();
  assert.equal(elements.platform.value,'21.15');assert.equal(out('profit-local'),'77.8 THB');
  site('GBP');set('price',20);set('flash','no');calc();
  assert.equal(out('profit-local'),'11.4 GBP');assert.equal(out('paylater-fee'),'¥0.0');
  console.log('PASS: Malaysia fee update, PayLater shipping base, pricing round-trip, bilingual state, and PH/TH/UK regressions.');
})().catch(error=>{console.error(error);process.exitCode=1;});
