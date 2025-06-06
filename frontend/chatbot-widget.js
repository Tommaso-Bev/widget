(function () {
  /* -------------------- INIT AFTER SMALL DELAY -------------------- */
  setTimeout(() => {
    /* 0) Inject Intro.js se non già presente */
    if (typeof introJs === 'undefined') {
      console.log('[Tour] Injecting Intro.js assets…');
      const link   = Object.assign(document.createElement('link'), {
        rel : 'stylesheet',
        href: 'https://unpkg.com/intro.js/minified/introjs.min.css'
      });
      const script = Object.assign(document.createElement('script'), {
        src: 'https://unpkg.com/intro.js/minified/intro.min.js'
      });
      document.head.append(link, script);
    }

    /* 1) Chatbot UI */
    const wrapper = document.createElement('div');
    wrapper.innerHTML = `
      <button id="chatbot-icon" class="chatbot-icon"></button>
      <div id="chatbot-window" class="chatbot-window hidden">
        <div id="chatbot-messages" class="chatbot-messages"></div>
        <input id="chatbot-input" class="chatbot-input" placeholder="Type your question…" />
      </div>`;
    document.body.appendChild(wrapper);

    /* 2) Element references */
    const icon       = wrapper.querySelector('#chatbot-icon');
    const chatWin    = wrapper.querySelector('#chatbot-window');
    const inputEl    = wrapper.querySelector('#chatbot-input');
    const messagesEl = wrapper.querySelector('#chatbot-messages');
    if (!icon || !chatWin || !inputEl || !messagesEl) {
      return console.error('[Chatbot] Missing elements!');
    }
    icon.addEventListener('click', () => chatWin.classList.toggle('hidden'));

    /* ---------- utility helpers ---------- */
    const appendMessage = (txt, who) => {
      const div  = document.createElement('div');
      div.textContent = txt;
      div.className   = `chatbot-msg ${who}`;
      messagesEl.appendChild(div);
      setTimeout(() => messagesEl.scrollTop = messagesEl.scrollHeight, 0);
    };

    const forceShowElement = el => {
      if (!el) return;
      const cs = getComputedStyle(el);
      el._orig = {
        d : el.style.display,
        v : el.style.visibility,
        o : el.style.opacity,
        t : el.style.transform
      };
      if (cs.display    === 'none') el.style.display    = 'block';
      if (cs.visibility === 'hidden') el.style.visibility = 'visible';
      if (cs.opacity    === '0')    el.style.opacity    = '1';
      if (cs.transform  && cs.transform !== 'none') el.style.transform = 'none';
    };
    const forceShowHierarchy = (el, max = 2) => {
      let cur = el, lvl = 0;
      while (cur && cur !== document.body && lvl < max) {
        forceShowElement(cur);
        cur = cur.parentElement;
        ++lvl;
      }
    };
    const restoreElement = el => {
      if (!el || !el._orig) return;
      el.style.display    = el._orig.d || '';
      el.style.visibility = el._orig.v || '';
      el.style.opacity    = el._orig.o || '';
      el.style.transform  = el._orig.t || '';
    };

    /* 3) Input handler */
    inputEl.addEventListener('keydown', async e => {
      if (e.key !== 'Enter') return;
      const userTxt = inputEl.value.trim();
      if (!userTxt) return;
      appendMessage(userTxt, 'user');
      inputEl.value = '';

      try {
        const res  = await fetch('http://127.0.0.1:8000/chat', {
          method : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body   : JSON.stringify({ message: userTxt })
        });
        const data = await res.json();
        appendMessage(data.answer, 'bot');
        if (!Array.isArray(data.tour_steps)) return;

        /* ----- map tour steps ----- */
        const steps = data.tour_steps.map(s => {
          const el = document.querySelector(s.selector);
          if (!el) {
            console.warn('[Tour] selector not found:', s.selector);
            return null;
          }
          const rect = el.getBoundingClientRect();   // forza reflow
          return {
            element : el,
            intro   : s.intro,
            position: rect.top < 100 ? 'right' : (s.position || 'bottom')
          };
        }).filter(Boolean);
        if (!steps.length) return;

        /* ----- pre-scroll & show elements ----- */
        await Promise.all(
          steps.map(st => new Promise(resv => {
            forceShowHierarchy(st.element);
            st.element.scrollIntoView({ behavior: 'smooth', block: 'center' });
            setTimeout(resv, 300);
          }))
        );

        /* ----- z-index overlay ----- */
        const zCss = document.createElement('style');
        zCss.textContent = `
          .introjs-overlay,
          .introjs-helper-layer,
          .introjs-tooltip { z-index: 999999 !important; }`;
        document.head.appendChild(zCss);

        /* ----- start tour with resize keep-alive ----- */
        let lastEl = null;
        let resizeInterval;                       // <- intervallo qui

        const intro = introJs().setOptions({ steps, tooltipPosition: 'auto' })
          .onbeforechange(el => {
            if (lastEl && lastEl !== el) restoreElement(lastEl);
            forceShowHierarchy(el);
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            window.dispatchEvent(new Event('resize')); // primo resize
            lastEl = el;
          })
          .onafterchange(() => {
            window.dispatchEvent(new Event('resize')); // ulteriore resize
          })
          .oncomplete(() => {
            clearInterval(resizeInterval);
            restoreElement(lastEl);
          })
          .onexit(() => {
            clearInterval(resizeInterval);
            restoreElement(lastEl);
          });

        /* avvia intervallo ogni 250 ms durante il tour */
        resizeInterval = setInterval(() =>
          window.dispatchEvent(new Event('resize')), 250);

        intro.start();

      } catch (err) {
        console.error('[Chat] Request failed', err);
        appendMessage('Oops! Server error.', 'bot');
      }
    });

  }, 0);

  /* 4) Avvio scraping dopo 10 s */
  setTimeout(() => {
    const url = window.location.href;
    fetch('http://127.0.0.1:8000/api/start-scraping/', {
      method : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body   : JSON.stringify({ url })
    }).then(() => console.log('🔗 URL inviato:', url));
  }, 10000);

})();
