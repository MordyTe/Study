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
      if (s.logged_in) return s.setup_done ? boot() : onboarding(s.cities);
      var setup = !s.pin_set;
      var pin = h('input', { class: 'pin', type: 'password', inputmode: 'numeric', autocomplete: setup ? 'new-password' : 'current-password', maxlength: '8', id: 'pin', 'aria-describedby': 'pinhelp' });
      var form = h('form', {
        class: 'card', onsubmit: function (e) {
          e.preventDefault();
          api('POST', setup ? '/api/auth/setup' : '/api/auth/login', { pin: pin.value }).then(showAuth).catch(function (err) { pin.value = ''; fail(err); });
        }
      },
        h('h2', { text: setup ? 'שלב 1 מתוך 2: בחרו קוד כניסה' : 'כניסה לניהול המסך' }),
        h('p', { class: 'muted', id: 'pinhelp', text: setup ? 'קוד של 4 עד 8 ספרות. רק מי שיודע אותו יוכל לשנות את מה שמוצג.' : 'הקלידו את קוד הכניסה.' }),
        h('label', { for: 'pin', text: 'קוד' }), pin,
        h('p', {}), h('button', { class: 'primary', type: 'submit', text: setup ? 'שמירה והמשך' : 'כניסה' }));
      view.textContent = '';
      view.appendChild(form);
      pin.focus();
    }).catch(fail);
  }

  /* First run, after choosing a PIN: three questions, then a ready-made set of slides. */
  function onboarding(cities) {
    var kinds = [['business', 'עסק', 'מסעדה, חנות, מספרה, קליניקה'], ['lobby', 'לובי בניין', 'הודעות ועד, זמני שבת, שעון'],
      ['synagogue', 'בית כנסת', 'זמני תפילות, זמני היום, הודעות'], ['general', 'משהו אחר', 'מתחילים ממסך כמעט ריק']];
    var chosen = 'business';
    var place = h('input', { id: 'oplace', type: 'text', maxlength: '60', autocomplete: 'organization' });
    var city = h('select', { id: 'ocity' }, cities.map(function (c) { return h('option', { value: c, text: c }); }));
    city.value = 'תל אביב';
    var group = h('div', { role: 'radiogroup', 'aria-label': 'סוג המקום' });
    kinds.forEach(function (k) {
      var b = h('button', { type: 'button', class: 'choice', role: 'radio', 'aria-checked': String(k[0] === chosen), onclick: function () {
        chosen = k[0];
        Array.prototype.forEach.call(group.children, function (c) { c.setAttribute('aria-checked', String(c === b)); });
      } }, h('b', { text: k[1] }), h('span', { text: k[2] }));
      group.appendChild(b);
    });
    view.textContent = '';
    view.appendChild(h('form', { onsubmit: function (e) {
      e.preventDefault();
      api('POST', '/api/setup', { place: place.value, city: city.value, category: chosen })
        .then(function () { toast('המסך מוכן. עכשיו אפשר לערוך את השקופיות'); boot(); }).catch(fail);
    } },
      h('div', { class: 'card' },
        h('h2', { text: 'שלב 2 מתוך 2: כמה פרטים על המקום', style: 'margin-top:0' }),
        h('p', { class: 'muted', text: 'לפי התשובות נכין כמה שקופיות מוכנות. את הכול אפשר לשנות אחר כך.' }),
        h('label', { for: 'oplace', text: 'שם המקום' }), place,
        h('label', { for: 'ocity', text: 'עיר' }), city,
        h('label', { text: 'סוג המקום' }), group),
      h('button', { class: 'primary', type: 'submit', text: 'סיום והפעלת המסך', style: 'width:100%' })));
    place.focus();
  }

  function boot() {
    Promise.all([api('GET', '/api/templates'), api('GET', '/api/images')]).then(function (r) {
      lib = r[0]; images = r[1]; bar.hidden = false; showHome();
      var m = /canva=(\w+)/.exec(location.hash);   // returning from Canva's consent page
      if (m) {
        history.replaceState(null, '', location.pathname);
        if (m[1] === 'ok') { toast('חשבון Canva חובר'); showCanva(); }
        else toast(m[1] === 'denied' ? 'החיבור ל-Canva בוטל' : 'החיבור ל-Canva נכשל. נסו שוב', true);
      }
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
        var badge = s.expired ? h('span', { class: 'badge off', text: 'פג תוקף' })
          : !s.enabled ? h('span', { class: 'badge off', text: 'כבויה' })
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
            h('div', { class: 'meta', text: s.template_name + ' · ' + (templateOf(s.template).wait_end ? 'עד סוף הסרטון' : s.duration + ' שניות') + ' · ' + scheduleText(s.schedule) }),
            h('div', { class: 'btns' },
              h('button', { class: 'small', text: 'עריכה', onclick: function () { editSlide(s); } }),
              h('button', { class: 'small', text: s.enabled ? 'כיבוי' : 'הפעלה', onclick: function () {
                api('PUT', '/api/slides/' + s.id, { data: s.data, duration: s.duration, schedule: s.schedule, expires: s.expires, enabled: !s.enabled }).then(showHome).catch(fail);
              } }),
              h('button', { class: 'small', text: 'שכפול', onclick: function () {
                api('POST', '/api/slides/' + s.id + '/copy').then(function () { toast('שוכפלה'); showHome(); }).catch(fail);
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
        h('button', { text: 'מוזיקה', onclick: function () { showMusic(); } }),
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
    editFields({ id: s.id, template: s.template, data: clone(s.data), duration: s.duration, enabled: s.enabled, schedule: s.schedule, expires: s.expires }, showHome);
  }

  // ---------- step 3: content ----------
  function editFields(draft, back) {
    var t = templateOf(draft.template);
    var nodes = [steps(3)];
    if (t.help) nodes.push(h('p', { class: 'muted', text: t.help }));
    t.fields.forEach(function (f) { nodes.push(fieldEditor(f, draft.data)); });
    nodes.push(h('label', { text: 'צבעים' }), themePicker(draft.data));
    if (t.background !== false) nodes.push(h('label', { text: 'רקע' }), backgroundPicker(draft.data));
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
  /* Background: plain theme colour, one of the built-in designs, or the user's own photo. */
  function backgroundPicker(data) {
    var box = h('div', {});
    var photoField = { key: 'background', type: 'image' };
    function isPhoto() { return !!data.background && data.background.indexOf('bg:') !== 0; }
    function draw(showPhotos) {
      box.textContent = '';
      var grid = h('div', { class: 'bgs', role: 'group', 'aria-label': 'רקע' });
      function swatch(id, name, css, pressed, onclick) {
        return h('button', { type: 'button', class: 'bg', 'aria-pressed': String(pressed), onclick: onclick },
          h('span', { class: 'bgsw', style: css ? 'background:' + css : null, text: css ? '' : '—' }), h('span', { text: name }));
      }
      grid.appendChild(swatch('', 'לפי הצבעים', null, !data.background && !showPhotos, function () { data.background = ''; draw(false); }));
      lib.backgrounds.forEach(function (b) {
        // vh units are relative to the TV, so scale the pattern down for the small swatch
        grid.appendChild(swatch(b.id, b.name, b.css.replace(/([\d.]+)vh/g, function (m, n) { return (n * 0.9).toFixed(2) + 'px'; }),
          data.background === b.id, function () { data.background = b.id; draw(false); }));
      });
      grid.appendChild(swatch('photo', 'תמונה שלי', null, isPhoto() || showPhotos, function () { if (!isPhoto()) data.background = ''; draw(true); }));
      box.appendChild(grid);
      if (data.background && !isPhoto()) box.appendChild(h('p', { class: 'muted', text: 'רקע מעוצב מביא איתו צבעי טקסט משלו, במקום הצבעים שנבחרו למעלה.', style: 'margin-top:8px' }));
      if (isPhoto() || showPhotos) {
        box.appendChild(h('p', { class: 'muted', text: 'התמונה תוכהה מעט כדי שהטקסט יישאר קריא.', style: 'margin-top:8px' }));
        box.appendChild(picker(photoField, data));
      }
    }
    draw(false);
    return box;
  }
  function fieldEditor(f, data) {
    var id = 'f_' + f.key;
    var wrap = h('div', {});
    if (f.type === 'rows') { wrap.appendChild(h('label', { text: f.label })); wrap.appendChild(rowsEditor(f, data)); return wrap; }
    if (f.type === 'video') { wrap.appendChild(h('label', { text: f.label })); wrap.appendChild(videoPicker(f, data)); return wrap; }
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

  /* Video chooser: one video per slide; files are uploaded as they are (no conversion). */
  function videoPicker(f, data) {
    var box = h('div', {});
    function draw(list) {
      box.textContent = '';
      if (!list.length) box.appendChild(h('p', { class: 'muted', text: 'עוד אין סרטונים. העלו סרטון מהטלפון.' }));
      box.appendChild(h('div', { class: 'pics' }, list.map(function (name) {
        var on = data[f.key] === name;
        return h('button', { type: 'button', class: 'pic', 'aria-pressed': String(on), 'aria-label': on ? 'סרטון נבחר' : 'בחירת סרטון', onclick: function () { data[f.key] = on ? '' : name; draw(list); } },
          h('video', { src: '/uploads/' + name + '#t=0.5', preload: 'metadata', muted: 'muted', playsinline: 'playsinline', tabindex: '-1' }));
      })));
      var input = h('input', { type: 'file', accept: 'video/mp4,video/webm', hidden: true });
      var btn = h('button', { type: 'button', text: 'העלאת סרטון', onclick: function () { input.click(); } });
      input.addEventListener('change', function () {
        if (!input.files[0]) return;
        var fd = new FormData(); fd.append('file', input.files[0]);
        btn.disabled = true; btn.textContent = 'מעלה… זה יכול לקחת כמה דקות';
        api('POST', '/api/videos', fd).then(function (r) { data[f.key] = r.name; toast('הסרטון עלה'); load(); })
          .catch(function (err) { fail(err); btn.disabled = false; btn.textContent = 'העלאת סרטון'; });
      });
      var tools = h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;margin-top:12px' }, btn, input);
      if (data[f.key]) tools.appendChild(h('button', { type: 'button', class: 'danger', text: 'מחיקת הסרטון הנבחר', onclick: function () {
        if (confirm('למחוק את הסרטון מהמכשיר?')) api('DELETE', '/api/videos/' + data[f.key]).then(function () { data[f.key] = ''; toast('נמחק'); load(); }).catch(fail);
      } }));
      box.appendChild(tools);
    }
    function load() { api('GET', '/api/videos').then(draw).catch(fail); }
    load();
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
      var expires = h('input', { type: 'date', id: 'exp', value: draft.expires || '' });
      var duration = h('input', { type: 'number', id: 'dur', inputmode: 'numeric', min: '5', max: '600', value: draft.duration });

      var waitEnd = !!templateOf(draft.template).wait_end;
      screen('כך זה ייראה', back, [steps(4), frame(null, html),
        waitEnd ? h('p', { class: 'muted', text: 'הסרטון מתנגן עד סופו, ואז עוברים לשקופית הבאה.', style: 'margin-top:12px' }) : [h('label', { for: 'dur', text: 'כמה שניות להציג לפני המעבר לשקופית הבאה' }), duration],
        h('div', { class: 'check' }, always, h('label', { for: 'always', text: 'להציג תמיד', style: 'margin:0' })),
        schedBox,
        h('label', { for: 'exp', text: 'להציג עד תאריך (לא חובה)' }), expires,
        h('p', { class: 'muted', text: 'אחרי התאריך הזה השקופית יורדת מהמסך לבד. מתאים למבצעים ולהודעות זמניות.', style: 'margin-top:6px' })
      ], [
        h('button', { text: 'חזרה לעריכה', onclick: back }),
        h('button', { class: 'primary', text: draft.id ? 'שמירה' : 'פרסום למסך', onclick: function () {
          if (!always.checked && !sched.days.length) return toast('בחרו לפחות יום אחד', true);
          var body = {
            template: draft.template, data: draft.data, enabled: draft.enabled,
            duration: parseInt(duration.value, 10) || 12,
            schedule: always.checked ? null : { days: sched.days, start: start.value, end: end.value },
            expires: expires.value || null
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
      screen('תמונות', showHome, nodes, [h('button', { text: 'ייבוא מ-Canva', onclick: showCanva }), uploadButton('העלאת תמונות', showImages)]);
    }).catch(fail);
  }

  // ---------- background music ----------
  function showMusic(keepMode) {
    api('GET', '/api/music').then(function (m) {
      if (typeof keepMode === 'string') m.mode = keepMode;   // stay on the choice being edited after an upload or delete
      function radio(value, label, hint) {
        var id = 'mode_' + value;
        var input = h('input', { type: 'radio', name: 'mode', id: id, value: value, checked: m.mode === value });
        input.addEventListener('change', function () { m.mode = value; sync(); });
        return h('div', { class: 'check', style: 'align-items:flex-start' }, input,
          h('label', { for: id, style: 'margin:0' }, label, h('span', { class: 'muted', style: 'display:block;font-weight:400', text: hint })));
      }
      var volume = h('input', { type: 'range', id: 'vol', min: '0', max: '100', step: '5', value: m.volume });
      var volText = h('span', { text: m.volume + '%' });
      volume.addEventListener('input', function () { volText.textContent = volume.value + '%'; });
      var shuffle = h('input', { type: 'checkbox', id: 'shuf', checked: m.shuffle });
      var rname = h('input', { id: 'rname', type: 'text', maxlength: '60', value: m.radio_name });
      var rurl = h('input', { id: 'rurl', class: 'ltr', type: 'url', inputmode: 'url', maxlength: '500', placeholder: 'https://', value: m.radio_url });

      var input = h('input', { type: 'file', accept: 'audio/*,.mp3,.m4a,.ogg,.wav', multiple: 'multiple', hidden: true });
      var up = h('button', { type: 'button', text: '+ העלאת שירים', onclick: function () { input.click(); } });
      input.addEventListener('change', function () {
        var files = Array.prototype.slice.call(input.files);
        if (!files.length) return;
        up.disabled = true; up.textContent = 'מעלה…';
        files.reduce(function (p, file) {
          return p.then(function () { var fd = new FormData(); fd.append('file', file); return api('POST', '/api/music/tracks', fd); });
        }, Promise.resolve()).then(function () { toast('עלה'); }).catch(fail).then(function () { showMusic(m.mode); });
      });
      var songs = h('div', { class: 'card' }, h('h2', { text: 'השירים שלי', style: 'margin-top:0' }),
        m.tracks.length ? m.tracks.map(function (t) {
          return h('div', { class: 'track' }, h('span', { text: t.title }),
            h('button', { class: 'small danger', text: 'מחיקה', 'aria-label': 'מחיקת ' + t.title, onclick: function () {
              if (confirm('למחוק את "' + t.title + '"?')) api('DELETE', '/api/music/tracks/' + t.name).then(function () { showMusic(m.mode); }).catch(fail);
            } }));
        }) : h('p', { class: 'muted', text: 'עוד אין שירים. אפשר להעלות קובצי MP3, M4A, OGG או WAV.' }),
        h('div', { class: 'check' }, shuffle, h('label', { for: 'shuf', text: 'לנגן בסדר אקראי', style: 'margin:0' })),
        up, input);
      var station = h('div', { class: 'card' }, h('h2', { text: 'תחנת רדיו', style: 'margin-top:0' }),
        h('label', { for: 'rname', text: 'שם התחנה (לא חובה)' }), rname,
        h('label', { for: 'rurl', text: 'כתובת השידור' }), rurl,
        h('p', { class: 'muted', style: 'margin-top:6px', text: 'כתובת של שידור ישיר (stream) שמסתיימת בדרך כלל ב-mp3 או aac, ולא כתובת של אתר התחנה. דורש אינטרנט.' }));
      function sync() { songs.hidden = m.mode !== 'playlist'; station.hidden = m.mode !== 'radio'; }
      sync();
      screen('מוזיקת רקע', showHome, [
        h('div', { class: 'card', role: 'radiogroup', 'aria-label': 'מה לנגן' },
          radio('off', 'בלי מוזיקה', 'המסך שקט'),
          radio('playlist', 'השירים שלי', 'קבצים שהעליתם, מתנגנים בלולאה. עובד גם בלי אינטרנט'),
          radio('radio', 'רדיו באינטרנט', 'שידור ישיר של תחנה לפי כתובת')),
        songs, station,
        h('div', { class: 'card' },
          h('label', { for: 'vol', style: 'margin-top:0' }, 'עוצמה: ', volText), volume,
          h('p', { class: 'muted', style: 'margin-top:8px', text: 'כשמוצג סרטון עם קול, המוזיקה נעצרת וחוזרת אחריו.' })),
        h('p', { class: 'muted', text: 'שימו לב: השמעת מוזיקה במקום ציבורי או בעסק דורשת בדרך כלל רישיון מארגוני הזכויות (כמו אקו"ם), גם כשמדובר ברדיו.' })
      ], [h('button', { class: 'primary', text: 'שמירה', onclick: function () {
        api('PUT', '/api/music', { mode: m.mode, volume: parseInt(volume.value, 10), shuffle: shuffle.checked, radio_name: rname.value, radio_url: rurl.value })
          .then(function () { toast('נשמר. המסך יתעדכן תוך כמה שניות'); showHome(); }).catch(fail);
      } })]);
    }).catch(fail);
  }

  // ---------- Canva ----------
  function showCanva() {
    api('GET', '/api/canva/status').then(function (st) {
      if (!st.connected) {
        return screen('ייבוא מ-Canva', showImages, [h('div', { class: 'card empty' },
          h('h2', { text: st.configured ? 'חשבון Canva עוד לא מחובר' : 'החיבור ל-Canva עוד לא הוגדר' }),
          h('p', { class: 'muted', text: 'מגדירים ומחברים פעם אחת בהגדרות, ואז העיצובים שלכם מופיעים כאן.' }),
          h('button', { class: 'primary', text: 'להגדרות', onclick: showSettings }))]);
      }
      var grid = h('div', { class: 'pics designs' });
      var more = h('button', { text: 'עוד עיצובים', hidden: true });
      var note = h('p', { class: 'muted', text: 'טוען…' });
      var next = '';
      function load() {
        more.disabled = true;
        api('GET', '/api/canva/designs' + (next ? '?continuation=' + encodeURIComponent(next) : '')).then(function (r) {
          note.textContent = r.items.length || grid.children.length ? 'לחיצה על עיצוב מייבאת אותו לספריית התמונות. עיצוב בגודל 1920×1080 ימלא את המסך בדיוק.' : 'לא נמצאו עיצובים בחשבון.';
          r.items.forEach(function (d) {
            var b = h('button', { type: 'button', class: 'pic design', 'aria-label': 'ייבוא העיצוב ' + d.title, onclick: function () {
              b.disabled = true; toast('מייבא את "' + d.title + '"…');
              api('POST', '/api/canva/import', { design_id: d.id }).then(function (res) {
                res.names.forEach(function (n) { images.unshift(n); });
                toast(res.names.length > 1 ? res.names.length + ' עמודים יובאו לספריית התמונות' : 'יובא לספריית התמונות');
              }).catch(fail).then(function () { b.disabled = false; });
            } }, d.thumbnail ? h('img', { src: d.thumbnail, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' }) : null, h('span', { class: 'cap', text: d.title }));
            grid.appendChild(b);
          });
          next = r.continuation; more.hidden = !next; more.disabled = false;
        }).catch(function (err) { note.textContent = ''; fail(err); });
      }
      more.addEventListener('click', load);
      screen('ייבוא מ-Canva', showImages, [note, grid, h('p', {}), more]);
      load();
    }).catch(fail);
  }
  function canvaCard() {
    var card = h('div', { class: 'card' }, h('h2', { text: 'Canva', style: 'margin-top:0' }), h('p', { class: 'muted', text: 'טוען…' }));
    api('GET', '/api/canva/status').then(function (st) {
      var cid = h('input', { id: 'cid', class: 'ltr', type: 'text', autocomplete: 'off', value: st.client_id });
      var sec = h('input', { id: 'csec', class: 'ltr', type: 'password', autocomplete: 'off', placeholder: st.configured ? 'נשמר. הקלידו רק כדי להחליף' : '' });
      card.textContent = '';
      append(card, [h('h2', { text: 'Canva', style: 'margin-top:0' }),
        h('p', { class: 'muted', text: st.connected ? 'חשבון מחובר. מייבאים עיצובים ממסך "תמונות".' : 'חיבור חשבון Canva מאפשר לייבא עיצובים ישירות לספריית התמונות.' }),
        h('label', { for: 'cid', text: 'Client ID' }), cid,
        h('label', { for: 'csec', text: 'Client secret' }), sec,
        h('p', { class: 'muted', style: 'margin-top:8px' }, 'כתובת החזרה שצריך לרשום ב-Canva: ', h('span', { class: 'ltr', text: st.redirect_uri })),
        h('div', { class: 'btns', style: 'display:flex;gap:8px;flex-wrap:wrap' },
          h('button', { text: 'שמירת פרטי החיבור', onclick: function () {
            api('PUT', '/api/canva/config', { client_id: cid.value, client_secret: sec.value }).then(function () { toast('נשמר'); showSettings(); }).catch(fail);
          } }),
          st.configured && !st.connected ? h('a', { class: 'btn primary', href: '/api/canva/login', text: 'חיבור חשבון Canva' }) : null,
          st.connected ? h('button', { class: 'danger', text: 'ניתוק החשבון', onclick: function () {
            api('POST', '/api/canva/disconnect').then(function () { toast('נותק'); showSettings(); }).catch(fail);
          } }) : null),
        st.configured && !st.connected && location.hostname !== '127.0.0.1' ? h('p', { class: 'muted', style: 'margin-top:8px', text: 'בגרסה הזאת את החיבור עצמו עושים פעם אחת מדפדפן על המכשיר שמריץ את המסך (בכתובת 127.0.0.1), כי Canva לא מאפשרת חזרה לכתובת ברשת הביתית.' }) : null]);
    }).catch(function () { card.lastChild.textContent = 'לא ניתן לטעון את מצב החיבור.'; });
    return card;
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
          h('h2', { text: 'המסך המחובר', style: 'margin-top:0' }),
          h('p', { text: s.display ? s.display.width + ' × ' + s.display.height + ' פיקסלים' + (s.display.live ? '' : ' (התצוגה לא פעילה כרגע)') : 'התצוגה עוד לא נפתחה על המסך.' }),
          h('p', { class: 'muted', text: 'הרזולוציה מזוהה אוטומטית מהמסך דרך ה-HDMI, והשקופיות מתאימות את עצמן לכל גודל. אין מה להגדיר.' })),
        h('div', { class: 'card' },
          h('h2', { text: 'כתובת דף הניהול', style: 'margin-top:0' }),
          h('p', { class: 'ltr', text: s.admin_url }),
          h('p', { class: 'muted', text: 'עובדת מכל טלפון או מחשב שמחובר לאותה רשת.' })),
        canvaCard(),
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
