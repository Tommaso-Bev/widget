(function () {
  /* -------------------- ESEGUE IL PRIMA POSSIBILE -------------------- */
  setTimeout(() => {
    /* Metto introjs tra il link e script */
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

    /* Chatbot UI (Frontend) */
    const wrapper = document.createElement('div');
    wrapper.innerHTML = `
      <button id="chatbot-icon" class="chatbot-icon"></button>
      <div id="chatbot-window" class="chatbot-window hidden">
        <div id="chatbot-messages" class="chatbot-messages"></div>
        <input id="chatbot-input" class="chatbot-input" placeholder="Type your question…" />
      </div>`;
    document.body.appendChild(wrapper);

    /* Riferimenti ai vari elementi del frontend tramite id */
    const icon      = wrapper.querySelector('#chatbot-icon');
    const chatWin   = wrapper.querySelector('#chatbot-window');
    const inputEl   = wrapper.querySelector('#chatbot-input');
    const messagesEl = wrapper.querySelector('#chatbot-messages');
    if (!icon || !chatWin || !inputEl || !messagesEl) {
      return console.error('[Chatbot] Missing elements!');
    }

    let chatbotHiddenByOverlap = false; // flag che indica se il chatbot è stato nascosto tramite la logica di overlapping
    let lastKnownChatbotRect = null;    // possiede le specifiche dell'ultimo rettangolo della chat testuale

    // inizializziamo il rettangolo di chatwin se esso è visibile per default
    if (!chatWin.classList.contains('hidden')) {
      lastKnownChatbotRect = chatWin.getBoundingClientRect();
    }

    icon.addEventListener('click', () => {
      // prima di fare il toggle del button e quindi mostrare/nascondere il chatbot, salviamo il rettangolo box del chatbot
      if (!chatWin.classList.contains('hidden')) {
        lastKnownChatbotRect = chatWin.getBoundingClientRect();
      }
      chatWin.classList.toggle('hidden');
      chatbotHiddenByOverlap = false;
      console.log('[Chatbot] User clicked icon. chatbotHiddenByOverlap reset to false.');
    });

    /* FUNZIONI DI UTILITA' */
    const appendMessage = (txt, who) => {
      const div = document.createElement('div');
      div.className = `chatbot-msg ${who}`;

      if (who === 'bot') {
        const urlRegex = /(https?:\/\/[^\s]+)/g;
        const moreInfoRegex = /(More info:\s*)(https?:\/\/[^\s]+)/g;

        let processedTxt = txt;

        processedTxt = processedTxt.replace(moreInfoRegex, (match, p1, url) => {
            return `${p1}<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`;
        });

        processedTxt = processedTxt.replace(urlRegex, (url) => {
            if (!url.includes('<a href=')) {
                return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`;
            }
            return url;
        });

        div.innerHTML = processedTxt;
      } else {
        div.textContent = txt;
      }

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

    // identifica se due rettangoli in entrata siano o meno in overlapping
    const elementsOverlap = (el1, rect2_or_el2) => {
        if (!el1 || !rect2_or_el2) return false;
        const rect1 = el1.getBoundingClientRect();
        let rect2;
        if (rect2_or_el2 instanceof HTMLElement) {
            rect2 = rect2_or_el2.getBoundingClientRect();
        } else {
            rect2 = rect2_or_el2;
        }


        return !(
            rect1.right < rect2.left ||
            rect1.left > rect2.right ||
            rect1.bottom < rect2.top ||
            rect1.top > rect2.bottom
        );
    };

    let overlapCheckInterval; // variabile di overlapping

    /* Funzione per capire dinamicamente se rendere visibile/invisibile il chatbot durante la guida visuale, in particolare se c'è overlap fra le due cose */
    const handleChatbotVisibilityBasedOnTourElements = () => {
        if (!chatWin || !document.body.contains(chatWin)) {
            console.warn('[Chatbot] Chat window not found or removed from DOM. Stopping overlap check.');
            clearInterval(overlapCheckInterval);
            return;
        }

        const introjsTooltip = document.querySelector('.introjs-tooltip');
        const introjsHelperLayer = document.querySelector('.introjs-helperLayer');

        const isChatbotHidden = chatWin.classList.contains('hidden');
        let shouldHideChatbot = false; // default

        const isTourActive = introjsTooltip || introjsHelperLayer; // guarda se la guida visuale sia presente attualmente

        // per determinare quale rettangolo utilizzare tra quello precedente o attuale per capire se c'è overlap o meno
        let currentChatbotRectForOverlap = isChatbotHidden ? lastKnownChatbotRect : chatWin.getBoundingClientRect();
        if (isChatbotHidden && !currentChatbotRectForOverlap) {
            console.log('[Chatbot] Chatbot hidden, no last known rect. Skipping overlap check for now.');
            return;
        }

        if (isTourActive) {
            // se la guida visuale è attiva bisogna capire se nascondere o meno il chatbot nei casi di overlap
            if ((introjsTooltip && elementsOverlap(introjsTooltip, currentChatbotRectForOverlap)) ||
                (introjsHelperLayer && elementsOverlap(introjsHelperLayer, currentChatbotRectForOverlap))) {
                shouldHideChatbot = true; // con l'overlap nascondiamo il chatbot
            } else {
                shouldHideChatbot = false; // non c'è overlap quindi può essere mostrato
            }
        } else {
            // se la guida visuale non è attiva il chatbot dovrebbe essere mostrato
            shouldHideChatbot = false;
        }

        // core Logic per prevenire i loop
        if (shouldHideChatbot && !isChatbotHidden) {
            console.log('[Chatbot] Overlap detected and chatbot is visible. Hiding chatbot.');
            icon.click();
            chatbotHiddenByOverlap = true; // c'è stato overlap quindi si blocca
        } else if (!shouldHideChatbot && isChatbotHidden) {
            if (chatbotHiddenByOverlap || !isTourActive) {
                console.log('[Chatbot] No overlap/Tour not active, and chatbot is hidden. Showing chatbot.');
                icon.click();
                chatbotHiddenByOverlap = false;
            } else {
                 console.log('[Chatbot] Chatbot is hidden, no overlap, but not hidden by automation. User choice respected.');
            }
        }
    };


    /* Gestione input da parte del frontend */
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
          body   : JSON.stringify({
            message: userTxt,
            current_page_url: window.location.href
          })
        });
        const data = await res.json();
        appendMessage(data.answer, 'bot');
        if (!Array.isArray(data.tour_steps)) return;

        const steps = data.tour_steps.map(s => {
          const el = document.querySelector(s.selector);
          if (!el) {
            console.warn('[Tour] selector not found:', s.selector);
            return null;
          }
          const rect = el.getBoundingClientRect();
          return {
            element : el,
            intro   : s.intro,
            position: rect.top < 100 ? 'right' : (s.position || 'bottom')
          };
        }).filter(Boolean);
        if (!steps.length) return;

        await Promise.all(
          steps.map(st => new Promise(resv => {
            forceShowHierarchy(st.element);
            st.element.scrollIntoView({ behavior: 'smooth', block: 'center' });
            setTimeout(resv, 300);
          }))
        );

        const zCss = document.createElement('style');
        zCss.textContent = `
          .introjs-overlay,
          .introjs-helper-layer,
          .introjs-tooltip { z-index: 999999 !important; }`;
        document.head.appendChild(zCss);

        let lastEl = null;
        let resizeInterval;
        const intro = introJs().setOptions({ steps, tooltipPosition: 'auto' })
          .onbeforechange(el => {
            if (!el) {
                console.log('[Tour] onbeforechange called with undefined element (likely tour ending). Skipping element manipulation.');
                return; // non procedere se il tour  finito
            }
            if (lastEl && lastEl !== el) restoreElement(lastEl);
            forceShowHierarchy(el);
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            window.dispatchEvent(new Event('resize'));
            handleChatbotVisibilityBasedOnTourElements(); // si fa il check subito prima della modifica
            lastEl = el;
          })
          .onafterchange(el => {
            if (!el) {
                console.log('[Tour] onafterchange called with undefined element (likely tour ending). Skipping element manipulation.');
                return; // Do not proceed if el is undefined
            }
            window.dispatchEvent(new Event('resize'));
            handleChatbotVisibilityBasedOnTourElements(); // si fa il check subito dopo la modifica
          })
          .oncomplete(() => {
            clearInterval(resizeInterval);
            clearInterval(overlapCheckInterval);
            restoreElement(lastEl);
            // il chatbot deve essere visibile quando la guida viene terminata
            if (chatWin.classList.contains('hidden')) {
                console.log('[Chatbot] Tour complete, ensuring chatbot is shown.');
                icon.click();
            }
            chatbotHiddenByOverlap = false;
            if (!chatWin.classList.contains('hidden')) {
                lastKnownChatbotRect = chatWin.getBoundingClientRect();
            }
            if (zCss.parentNode) {
                zCss.parentNode.removeChild(zCss);
            }
          })
          .onexit(() => {
            clearInterval(resizeInterval);
            clearInterval(overlapCheckInterval);
            restoreElement(lastEl);
            // il chatbot deve essere visibile quando la guida viene terminata
            if (chatWin.classList.contains('hidden')) {
                console.log('[Chatbot] Tour exited, ensuring chatbot is shown.');
                icon.click();
            }
            chatbotHiddenByOverlap = false; // reset flag una volta usciti dalla guida visuale
            if (!chatWin.classList.contains('hidden')) {
                lastKnownChatbotRect = chatWin.getBoundingClientRect();
            }
            if (zCss.parentNode) {
                zCss.parentNode.removeChild(zCss);
            }
          });

        overlapCheckInterval = setInterval(handleChatbotVisibilityBasedOnTourElements, 50);

        resizeInterval = setInterval(() => window.dispatchEvent(new Event('resize')), 250);

        intro.start();
      }
      catch (err) {
        console.error('[Chat] Request failed', err);
        appendMessage('Oops! Server error.', 'bot');
      }
    });
  }, 0);

  /* Avviamento dello scraping dopo 10 s per aspettare che tutto sia "pronto" */
  setTimeout(() => {
    const url = window.location.href;
    fetch('http://127.0.0.1:8000/api/start-scraping/', {
      method : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body   : JSON.stringify({ url })
    }).then(() => console.log('🔗 URL inviato:', url));
  }, 10000);

})();