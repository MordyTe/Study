/* Admin page: wizard, slide list, image library, settings. Plain JS, no build step. */
(function () {
  'use strict';
  var view = document.getElementById('view');
  var bar = document.getElementById('bar');
  var heading = document.getElementById('heading');
  var backBtn = document.getElementById('back');
  var menuBtn = document.getElementById('menu');
  var toastEl = document.getElementById('toast');
  var lib = null;          // {categories, templates, themes}
  var images = [];         // file names in the library
  var onBack = null;
  var DAYS = ['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש'];

  // ---------- helpers ----------
  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked' || k === 'disabled' || k === 'hidden') el[k] = !!v;
      else el.setAttribute(k, v);
    });
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(el, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) child.forEach(function (c) { append(el, c); });
    else el.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  function toast(msg, bad) {
    toastEl.textContent = msg;
    toastEl.className = 'on' + (bad ? ' bad' : '');
    clearTimeout(toast.t);
    toast.t = setTimeout(function () { toastEl.className = ''; }, bad ? 4500 : 2200);
  }
  function api(method, url, body, raw) {
    var opts = { method: method, headers: {}, credentials: 'same-origin' };
    if (body instanceof FormData) opts.body = body;
    else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    return fetch(url, opts).then(function (r) {
      if (r.status === 401 && url.indexOf('/api/auth/') !== 0) { showAuth(); throw new Error('נדרשת כניסה מחדש'); }
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          throw new Error(typeof j.detail === 'string' ? j.detail : 'משהו השתבש. נסו שוב');
        });
      }
      return raw ? r.text() : r.json();
    });
  }
  function fail(err) { toast(err.message || 'אין חיבור למסך', true); }
  function screen(title, back, nodes, actions) {
    heading.textContent = title;
    onBack = back || null;
    backBtn.hidden = !back;
    view.textContent = '';
    append(view, nodes);
    if (actions) append(view, h('div', { class: 'actions' }, actions));
    window.scrollTo(0, 0);
  }
  backBtn.addEventListener('click', function () { if (onBack) onBack(); });
  menuBtn.addEventListener('click', function () { showSettings(); });
  function templateOf(id) { return lib.templates.filter(function (t) { return t.id === id; })[0]; }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  /* A 16:9 box showing a slide scaled down. Pass a URL or raw HTML. */
  function frame(src, html) {
    var iframe = h('iframe', { title: 'תצוגה מקדימה', tabindex: '-1', sandbox: 'allow-scripts allow-same-origin' });
    var box = h('div', { class: 'frame' }, iframe);
    if (html) iframe.srcdoc = html; else iframe.src = src;
    function fit() { if (box.clientWidth) iframe.style.transform = 'scale(' + box.clientWidth / 1280 + ')'; }
    requestAnimationFrame(fit);
    window.addEventListener('resize', fit);
    return box;
  }

  // ---------- auth ----------
  function showAuth() {
    bar.hidden = true;
    api('GET', '/api/auth/state').then(function (s) {
      if (s.logged_in) return boot();
      var setup = !s.pin_set;
      var pin = h('input', { class: 'pin', type: 'password', inputmode: 'numeric', autocomplete: setup ? 'new-password' : 'current-password', maxlength: '8', id: 'pin', 'aria-describedby': 'pinhelp' });
      var form = h('form', {
        class: 'card', onsubmit: function (e) {
          e.preventDefault();
          api('POST', setup ? '/api/auth/setup' : '/api/auth/login', { pin: pin.value }).then(boot).catch(function (err) { pin.value = ''; fail(err); });
        }
      },
        h('h2', { text: setup ? 'בחרו קוד כניסה' : 'כניסה לניהול המסך' }),
        h('p', { class: 'muted', id: 'pinhelp', text: setup ? 'קוד של 4 עד 8 ספרות. רק מי שיודע אותו יוכל לשנות את מה שמוצג.' : 'הקלידו את קוד הכניסה.' }),
        h('label', { for: 'pin', text: 'קוד' }), pin,
        h('p', {}), h('button', { class: 'primary', type: 'submit', text: setup ? 'שמירה והמשך' : 'כניסה' }));
      view.textContent = '';
      view.appendChild(form);
      pin.focus();
    }).catch(fail);
  }

  function boot() {
    Promise.all([api('GET', '/api/templates'), api('GET', '/api/images')]).then(function (r) {
      lib = r[0]; images = r[1]; bar.hidden = false; showHome();
    }).catch(fail);
  }

  // ---------- home ----------
  function scheduleText(s) {
    if (!s) return 'מוצג תמיד';
    var days = s.days.length === 7 ? 'כל יום' : 'ימים ' + s.days.map(function (d) { return DAYS[d]; }).join(', ');
    return days + ' · ' + s.start + ' עד ' + s.end;
  }
  function showHome() {
    api('GET', '/api/slides').then(function (slides) {
      var nodes = [];
      if (!slides.length) {
        nodes.push(h('div', { class: 'card empty' },
          h('h2', { text: 'המסך עדיין ריק' }),
          h('p', { class: 'muted', text: 'בחרו תבנית, מלאו כמה שדות, והיא תופיע על המסך.' })));
      } else {
        nodes.push(h('p', { class: 'muted', text: 'השקופיות מוצגות אחת אחרי השנייה, לפי הסדר כאן.' }));
      }
      slides.forEach(function (s, i) {
        var badge = !s.enabled ? h('span', { class: 'badge off', text: 'כבויה' })
          : s.active_now ? h('span', { class: 'badge on', text: 'מוצגת עכשיו' })
            : h('span', { class: 'badge off', text: 'מחוץ לשעות' });
        function move(delta) {
          var ids = slides.map(function (x) { return x.id; });
          ids.splice(i + delta, 0, ids.splice(i, 1)[0]);
          api('POST', '/api/slides/order', { ids: ids }).then(showHome).catch(fail);
        }
        nodes.push(h('div', { class: 'card slide' },
          frame('/render/' + s.id),
          h('div', {},
            h('h3', {}, s.data.title || s.template_name, badge),
            h('div', { class: 'meta', text: s.template_name + ' · ' + s.duration + ' שניות · ' + scheduleText(s.schedule) }),
            h('div', { class: 'btns' },
              h('button', { class: 'small', text: 'עריכה', onclick: function () { editSlide(s); } }),
              h('button', { class: 'small', text: s.enabled ? 'כיבוי' : 'הפעלה', onclick: function () {
                api('PUT', '/api/slides/' + s.id, { data: s.data, duration: s.duration, schedule: s.schedule, enabled: !s.enabled }).then(showHome).catch(fail);
              } }),
              h('button', { class: 'small', 'aria-label': 'העבר למעלה', text: '▲', disabled: i === 0, onclick: function () { move(-1); } }),
              h('button', { class: 'small', 'aria-label': 'העבר למטה', text: '▼', disabled: i === slides.length - 1, onclick: function () { move(1); } }),
              h('button', { class: 'small danger', text: 'מחיקה', onclick: function () {
                if (confirm('למחוק את השקופית "' + (s.data.title || s.template_name) + '"?')) {
                  api('DELETE', '/api/slides/' + s.id).then(function () { toast('נמחקה'); showHome(); }).catch(fail);
                }
              } })))));
      });
      screen('המסך שלי', null, nodes, [
        h('button', { text: 'תמונות', onclick: showImages }),
        h('button', { class: 'primary', text: '+ שקופית חדשה', onclick: wizardCategory })]);
    }).catch(fail);
  }

  // ---------- wizard ----------
  function steps(n) {
    var el = h('div', { class: 'steps', role: 'img', 'aria-label': 'שלב ' + n + ' מתוך 4' });
    for (var i = 1; i <= 4; i++) el.appendChild(h('i', { class: i <= n ? 'on' : '' }));
    return el;
  }
  function wizardCategory() {
    screen('מה המקום?', showHome, [steps(1), lib.categories.map(function (c) {
      return h('button', { class: 'choice', onclick: function () { wizardTemplate(c); } },
        h('b', { text: c.name }), h('span', { text: c.hint }));
    })]);
  }
  function wizardTemplate(cat) {
    var list = lib.templates.filter(function (t) { return t.categories.indexOf(cat.id) >= 0; });
    screen('מה להציג?', wizardCategory, [steps(2), list.map(function (t) {
      return h('button', { class: 'choice', onclick: function () {
        var draft = { template: t.id, data: clone(t.defaults), duration: 12, enabled: true, schedule: null };
        editFields(draft, function () { wizardTemplate(cat); });
      } }, h('b', { text: t.name }), h('span', { text: t.description }));
    })]);
  }
  function editSlide(s) {
    editFields({ id: s.id, template: s.template, data: clone(s.data), duration: s.duration, enabled: s.enabled, schedule: s.schedule }, showHome);
  }

  // ---------- step 3: content ----------
  function editFields(draft, back) {
    var t = templateOf(draft.template);
    var nodes = [steps(3)];
    if (t.help) nodes.push(h('p', { class: 'muted', text: t.help }));
    t.fields.forEach(function (f) { nodes.push(fieldEditor(f, draft.data)); });
    nodes.push(h('label', { text: 'צבעים' }), themePicker(draft.data));
    screen(t.name, back, nodes, [
      h('button', { class: 'primary', text: 'המשך לתצוגה מקדימה', onclick: function () { previewStep(draft, function () { editFields(draft, back); }); } })]);
  }
  function themePicker(data) {
    var box = h('div', { class: 'themes', role: 'group', 'aria-label': 'צבעים' });
    lib.themes.forEach(function (th) {
      var b = h('button', { type: 'button', 'aria-pressed': String(data.theme === th.id), onclick: function () {
        data.theme = th.id;
        Array.prototype.forEach.call(box.children, function (c) { c.setAttribute('aria-pressed', String(c === b)); });
      } }, h('span', { class: 'sw', style: 'background:' + th.bg + ';border-color:' + th.accent }), th.name);
      box.appendChild(b);
    });
    return box;
  }
  function fieldEditor(f, data) {
    var id = 'f_' + f.key;
    var wrap = h('div', {});
    if (f.type === 'rows') { wrap.appendChild(h('label', { text: f.label })); wrap.appendChild(rowsEditor(f, data)); return wrap; }
    if (f.type === 'image' || f.type === 'images') { wrap.appendChild(h('label', { text: f.label })); wrap.appendChild(picker(f, data)); return wrap; }
    wrap.appendChild(h('label', { for: id, text: f.label }));
    var input;
    if (f.type === 'textarea') input = h('textarea', { id: id, maxlength: f.max || 1500 });
    else if (f.type === 'select') {
      input = h('select', { id: id }, f.options.map(function (o) { return h('option', { value: o.value, text: o.label }); }));
    } else if (f.type === 'number') input = h('input', { id: id, type: 'number', inputmode: 'numeric', min: f.min, max: f.max });
    else input = h('input', { id: id, type: 'text', maxlength: f.max || 120 });
    input.value = data[f.key] === undefined ? '' : data[f.key];
    input.addEventListener('input', function () { data[f.key] = input.value; });
    wrap.appendChild(input);
    return wrap;
  }
  function rowsEditor(f, data) {
    var box = h('div', {});
    function draw() {
      box.textContent = '';
      var rows = data[f.key];
      rows.forEach(function (row, i) {
        function swap(j) { var x = rows[i]; rows[i] = rows[j]; rows[j] = x; draw(); }
        box.appendChild(h('div', { class: 'rowedit' },
          h('div', { class: 'cols', style: f.columns.length === 2 ? 'grid-template-columns:2fr 1fr' : null }, f.columns.map(function (c) {
            var inp = h('input', { type: 'text', placeholder: c.label, 'aria-label': c.label + ', שורה ' + (i + 1), maxlength: '120', value: row[c.key] || '' });
            inp.addEventListener('input', function () { row[c.key] = inp.value; });
            return inp;
          })),
          h('div', { class: 'tools' },
            h('button', { type: 'button', class: 'small', 'aria-label': 'העבר שורה למעלה', text: '▲', disabled: i === 0, onclick: function () { swap(i - 1); } }),
            h('button', { type: 'button', class: 'small', 'aria-label': 'העבר שורה למטה', text: '▼', disabled: i === rows.length - 1, onclick: function () { swap(i + 1); } }),
            h('button', { type: 'button', class: 'small danger', text: 'הסרה', onclick: function () { rows.splice(i, 1); draw(); } }))));
      });
      box.appendChild(h('button', { type: 'button', text: '+ הוספת שורה', disabled: rows.length >= 40, onclick: function () {
        var row = {}; f.columns.forEach(function (c) { row[c.key] = ''; }); rows.push(row); draw();
        var inputs = box.querySelectorAll('.rowedit:last-of-type input'); if (inputs[0]) inputs[0].focus();
      } }));
    }
    draw();
    return box;
  }

  /* Image chooser: pick from the library or upload from the phone. */
  function uploadButton(label, done) {
    var input = h('input', { type: 'file', accept: 'image/*', multiple: 'multiple', hidden: true });
    var btn = h('button', { type: 'button', text: label, onclick: function () { input.click(); } });
    input.addEventListener('change', function () {
      var files = Array.prototype.slice.call(input.files), names = [];
      if (!files.length) return;
      btn.disabled = true; btn.textContent = 'מעלה…';
      files.reduce(function (p, file) {
        return p.then(function () {
          var fd = new FormData(); fd.append('file', file);
          return api('POST', '/api/images', fd).then(function (r) { names.push(r.name); images.unshift(r.name); });
        });
      }, Promise.resolve()).then(function () { toast(names.length > 1 ? names.length + ' תמונות עלו' : 'התמונה עלתה'); })
        .catch(fail).then(function () { btn.disabled = false; btn.textContent = label; input.value = ''; done(names); });
    });
    return h('span', {}, btn, input);
  }
  function picker(f, data) {
    var multi = f.type === 'images';
    var box = h('div', {});
    function chosen() { return multi ? data[f.key] : (data[f.key] ? [data[f.key]] : []); }
    function draw() {
      box.textContent = '';
      var sel = chosen();
      if (!images.length) box.appendChild(h('p', { class: 'muted', text: 'עוד אין תמונות. העלו תמונה מהטלפון.' }));
      box.appendChild(h('div', { class: 'pics' }, images.map(function (name) {
        var at = sel.indexOf(name);
        return h('button', { type: 'button', class: 'pic', 'aria-pressed': String(at >= 0), 'aria-label': at >= 0 ? 'תמונה נבחרה' : 'בחירת תמונה', onclick: function () {
          if (multi) { if (at >= 0) data[f.key].splice(at, 1); else data[f.key].push(name); }
          else data[f.key] = at >= 0 ? '' : name;
          draw();
        } }, h('img', { src: '/uploads/' + name, alt: '', loading: 'lazy' }), multi && at >= 0 ? h('span', { class: 'n', text: String(at + 1) }) : null);
      })));
      box.appendChild(h('p', {}));
      box.appendChild(uploadButton('העלאת תמונה מהטלפון', function (names) {
        if (multi) names.forEach(function (n) { data[f.key].push(n); });
        else if (names.length) data[f.key] = names[0];
        draw();
      }));
    }
    draw();
    return box;
  }

  // ---------- step 4: preview, timing, publish ----------
  function previewStep(draft, back) {
    api('POST', '/api/preview', { template: draft.template, data: draft.data }, true).then(function (html) {
      var always = h('input', { type: 'checkbox', id: 'always', checked: !draft.schedule });
      var sched = draft.schedule ? clone(draft.schedule) : { days: [0, 1, 2, 3, 4, 5, 6], start: '08:00', end: '12:00' };
      var schedBox = h('div', { hidden: !draft.schedule });
      var days = h('div', { class: 'days', role: 'group', 'aria-label': 'ימים' }, DAYS.map(function (name, d) {
        var b = h('button', { type: 'button', text: name, 'aria-pressed': String(sched.days.indexOf(d) >= 0), onclick: function () {
          var at = sched.days.indexOf(d);
          if (at >= 0) sched.days.splice(at, 1); else sched.days.push(d);
          b.setAttribute('aria-pressed', String(at < 0));
        } });
        return b;
      }));
      var start = h('input', { type: 'time', id: 'start', value: sched.start });
      var end = h('input', { type: 'time', id: 'end', value: sched.end });
      append(schedBox, [h('label', { text: 'באילו ימים' }), days,
        h('div', { class: 'two' }, h('div', {}, h('label', { for: 'start', text: 'משעה' }), start), h('div', {}, h('label', { for: 'end', text: 'עד שעה' }), end))]);
      always.addEventListener('change', function () { schedBox.hidden = always.checked; });
      var duration = h('input', { type: 'number', id: 'dur', inputmode: 'numeric', min: '5', max: '600', value: draft.duration });

      screen('כך זה ייראה', back, [steps(4), frame(null, html),
        h('label', { for: 'dur', text: 'כמה שניות להציג לפני המעבר לשקופית הבאה' }), duration,
        h('div', { class: 'check' }, always, h('label', { for: 'always', text: 'להציג תמיד', style: 'margin:0' })),
        schedBox
      ], [
        h('button', { text: 'חזרה לעריכה', onclick: back }),
        h('button', { class: 'primary', text: draft.id ? 'שמירה' : 'פרסום למסך', onclick: function () {
          if (!always.checked && !sched.days.length) return toast('בחרו לפחות יום אחד', true);
          var body = {
            template: draft.template, data: draft.data, enabled: draft.enabled,
            duration: parseInt(duration.value, 10) || 12,
            schedule: always.checked ? null : { days: sched.days, start: start.value, end: end.value }
          };
          var req = draft.id ? api('PUT', '/api/slides/' + draft.id, body) : api('POST', '/api/slides', body);
          req.then(function () { toast(draft.id ? 'נשמר. המסך יתעדכן תוך כמה שניות' : 'פורסם. יופיע על המסך תוך כמה שניות'); showHome(); }).catch(fail);
        } })]);
    }).catch(fail);
  }

  // ---------- image library ----------
  function showImages() {
    api('GET', '/api/images').then(function (list) {
      images = list;
      var nodes = [h('p', { class: 'muted', text: 'התמונות שהעליתם. אפשר להשתמש בהן בכל שקופית.' })];
      if (!images.length) nodes.push(h('div', { class: 'card empty' }, h('p', { class: 'muted', text: 'עוד אין תמונות.' })));
      nodes.push(h('div', { class: 'pics' }, images.map(function (name) {
        return h('button', { type: 'button', class: 'pic', 'aria-label': 'מחיקת תמונה', onclick: function () {
          if (confirm('למחוק את התמונה? שקופיות שמשתמשות בה יוצגו בלעדיה.')) {
            api('DELETE', '/api/images/' + name).then(function () { toast('נמחקה'); showImages(); }).catch(fail);
          }
        } }, h('img', { src: '/uploads/' + name, alt: '', loading: 'lazy' }));
      })));
      if (images.length) nodes.push(h('p', { class: 'muted', text: 'לחיצה על תמונה מוחקת אותה (אחרי אישור).', style: 'margin-top:12px' }));
      screen('תמונות', showHome, nodes, [uploadButton('העלאת תמונות', showImages)]);
    }).catch(fail);
  }

  // ---------- settings ----------
  function showSettings() {
    api('GET', '/api/settings').then(function (s) {
      var place = h('input', { id: 'place', type: 'text', maxlength: '60', value: s.place });
      var city = h('select', { id: 'city' }, s.cities.map(function (c) { return h('option', { value: c, text: c }); }));
      city.value = s.city;
      var oldPin = h('input', { id: 'old', class: 'ltr', type: 'password', inputmode: 'numeric', maxlength: '8', autocomplete: 'current-password' });
      var newPin = h('input', { id: 'new', class: 'ltr', type: 'password', inputmode: 'numeric', maxlength: '8', autocomplete: 'new-password' });
      screen('הגדרות', showHome, [
        h('div', { class: 'card' },
          h('label', { for: 'place', text: 'שם המקום', style: 'margin-top:0' }), place,
          h('p', { class: 'muted', text: 'מופיע בקטן בפינת המסך. אפשר להשאיר ריק.', style: 'margin-top:6px' }),
          h('label', { for: 'city', text: 'עיר (לחישוב זמני שבת וזמני היום)' }), city,
          h('p', {}),
          h('button', { class: 'primary', text: 'שמירה', onclick: function () {
            api('PUT', '/api/settings', { place: place.value, city: city.value }).then(function () { toast('נשמר'); }).catch(fail);
          } })),
        h('div', { class: 'card' },
          h('h2', { text: 'כתובת דף הניהול', style: 'margin-top:0' }),
          h('p', { class: 'ltr', text: s.admin_url }),
          h('p', { class: 'muted', text: 'עובדת מכל טלפון או מחשב שמחובר לאותה רשת.' })),
        h('div', { class: 'card' },
          h('h2', { text: 'החלפת קוד כניסה', style: 'margin-top:0' }),
          h('label', { for: 'old', text: 'הקוד הנוכחי' }), oldPin,
          h('label', { for: 'new', text: 'קוד חדש (4 עד 8 ספרות)' }), newPin,
          h('p', {}),
          h('button', { text: 'החלפת קוד', onclick: function () {
            api('POST', '/api/auth/pin', { old: oldPin.value, new: newPin.value }).then(function () { oldPin.value = newPin.value = ''; toast('הקוד הוחלף'); }).catch(fail);
          } })),
        h('button', { class: 'danger', text: 'יציאה', onclick: function () { api('POST', '/api/auth/logout').then(showAuth).catch(fail); } })
      ]);
    }).catch(fail);
  }

  showAuth();
})();
