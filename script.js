(() => {
  const menuToggle = document.getElementById('menuToggle');
  const nav = document.getElementById('siteNav');
  if (menuToggle && nav) {
    menuToggle.addEventListener('click', () => {
      const isOpen = nav.classList.toggle('open');
      menuToggle.setAttribute('aria-expanded', String(isOpen));
      menuToggle.setAttribute('aria-label', isOpen ? 'Close navigation' : 'Toggle navigation');
      menuToggle.textContent = isOpen ? '×' : '☰';
    });
    nav.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
      nav.classList.remove('open');
      menuToggle.setAttribute('aria-expanded', 'false');
      menuToggle.setAttribute('aria-label', 'Toggle navigation');
      menuToggle.textContent = '☰';
    }));
  }

  const filters = [...document.querySelectorAll('.filter-chip')];
  const cards = [...document.querySelectorAll('.music-card')];
  const musicGrid = document.getElementById('musicGrid');
  const sortButtons = [...document.querySelectorAll('.sort-chip')];
  let currentSort = 'latest';
  const originalCardOrder = new Map(cards.map((card, index) => [card, index]));

  // Sort cards in place so their descriptions, thumbnails and category filters stay connected.
  const sortMusicCards = () => {
    if (!musicGrid) return;
    const sortedCards = [...cards].sort((a, b) => {
      const aRank = Number(a.dataset.latestRank) || Number.MAX_SAFE_INTEGER;
      const bRank = Number(b.dataset.latestRank) || Number.MAX_SAFE_INTEGER;

      if (currentSort === 'popular') {
        const aHasViews = a.dataset.viewCount !== undefined && a.dataset.viewCount !== '';
        const bHasViews = b.dataset.viewCount !== undefined && b.dataset.viewCount !== '';
        // Never treat a missing public view count as zero: place unverified entries after ranked entries.
        if (aHasViews !== bHasViews) return aHasViews ? -1 : 1;
        if (aHasViews && bHasViews) {
          const viewDifference = Number(b.dataset.viewCount) - Number(a.dataset.viewCount);
          if (viewDifference !== 0) return viewDifference;
        }
      }

      return (aRank - bRank) || (originalCardOrder.get(a) - originalCardOrder.get(b));
    });

    const fragment = document.createDocumentFragment();
    sortedCards.forEach(card => fragment.appendChild(card));
    musicGrid.appendChild(fragment);
  };

  sortButtons.forEach(button => button.addEventListener('click', () => {
    currentSort = button.dataset.sort === 'popular' ? 'popular' : 'latest';
    sortButtons.forEach(option => {
      const active = option === button;
      option.classList.toggle('active', active);
      option.setAttribute('aria-pressed', String(active));
    });
    sortMusicCards();
    if (typeof window.__vpUpdateDirectionalRevealStates === 'function') {
      window.__vpUpdateDirectionalRevealStates();
    }
  }));

  // Latest is the default each time the gallery loads.
  sortMusicCards();

  // Bidirectional scroll reveals with an edge-aware exit while each element is still visible.
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduceMotion && 'IntersectionObserver' in window) {
    const revealTargets = [...new Set([
      ...cards,
      ...document.querySelectorAll(
        '.hero-content, .hero-art, .intro-strip, .about-section, .artist-portrait, .about-copy, ' +
        '.hero-content .eyebrow, .hero-content h1, .hero-copy, .hero-actions, .hero-note, ' +
        '.about-copy > .eyebrow, .about-copy h2, .about-copy p, .about-copy .text-link, ' +
        '.artist-portrait img, .artist-portrait figcaption, .section-heading, .section-intro, .filter-row, ' +
        '.mood-card, .request-copy, .request-form, .connect-section, ' +
        '.connect-section > .eyebrow, #vpSocialTitle, .connect-section > p:not(.eyebrow), ' +
        '.connect-actions, .vp-social-intro, .vp-social-grid, .site-footer'
      )
    ])];

    revealTargets.forEach((element, index) => {
      if (!element.classList.contains('music-card')) element.classList.add('scroll-reveal');
      if (element.classList.contains('mood-card')) element.style.transitionDelay = (index % 4) * 70 + 'ms';
      if (element.matches('.hero-content .eyebrow')) element.style.transitionDelay = '80ms';
      if (element.matches('.hero-content h1')) element.style.transitionDelay = '180ms';
      if (element.matches('.hero-copy')) element.style.transitionDelay = '300ms';
      if (element.matches('.hero-actions')) element.style.transitionDelay = '410ms';
      if (element.matches('.hero-note')) element.style.transitionDelay = '520ms';
      if (element.matches('.hero-art')) element.classList.add('reveal-from-right');
      if (element.matches('.artist-portrait')) element.classList.add('reveal-from-left');
      if (element.matches('.artist-portrait img')) element.classList.add('reveal-soft-scale');
      if (element.matches('.about-copy > .eyebrow')) element.style.transitionDelay = '80ms';
      if (element.matches('.about-copy h2')) element.style.transitionDelay = '170ms';
      if (element.matches('.about-copy p:nth-of-type(2)')) element.style.transitionDelay = '280ms';
      if (element.matches('.about-copy p:nth-of-type(3)')) element.style.transitionDelay = '380ms';
      if (element.matches('.about-copy .text-link')) element.style.transitionDelay = '480ms';
      if (element.matches('.connect-section > .eyebrow')) element.style.transitionDelay = '80ms';
      if (element.matches('#vpSocialTitle')) element.style.transitionDelay = '170ms';
      if (element.matches('.connect-section > p:not(.eyebrow)')) element.style.transitionDelay = '260ms';
      if (element.matches('.connect-actions')) element.style.transitionDelay = '350ms';
      if (element.matches('.vp-social-intro')) element.style.transitionDelay = '440ms';
      if (element.matches('.vp-social-grid')) element.style.transitionDelay = '530ms';
    });
    document.body.classList.add('motion-ready');

    const classForState = (element, state, prefix) => {
      const visible = prefix === 'vp' ? 'vp-visible' : 'is-visible';
      const up = prefix === 'vp' ? 'vp-exit-up' : 'exit-up';
      const down = prefix === 'vp' ? 'vp-exit-down' : 'exit-down';
      const next = state === 'visible' ? visible : state === 'up' ? up : down;
      if (element.classList.contains(next)) return;
      element.classList.remove(visible, up, down);
      element.classList.add(next);
    };

    // While scrolling, change state before an element fully leaves the screen.
    // This is the key distinction from the old observer-only implementation:
    // IntersectionObserver reports exit after an element has already crossed its boundary.
    let revealFrame = 0;
    let lastScrollY = window.scrollY || 0;
    let scrollDirection = 0;
    const updateDirectionalRevealStates = () => {
      revealFrame = 0;
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
      // Keep the original trigger zone for entrances. Outgoing elements start earlier,
      // so the fade/blur is visible before fixed bars obscure them.
      const edgeZone = Math.min(160, Math.max(96, viewportHeight * 0.14));
      const exitEdgeZone = Math.min(280, Math.max(220, viewportHeight * 0.24));

      // Read all geometry first, then change classes in a second pass to avoid
      // read/write layout thrashing while the visitor scrolls.
      const states = [...document.querySelectorAll('.music-card, .scroll-reveal, .vp-reveal') ]
        .map(element => ({
          element,
          rect: element.getBoundingClientRect(),
          hasMainReveal: element.dataset.revealSeen === 'true',
          hasPremiumReveal: element.dataset.vpRevealSeen === 'true'
        }))
        .filter(item => item.hasMainReveal || item.hasPremiumReveal)
        .map(item => {
          let state;
          if (scrollDirection > 0) {
            // Scrolling down: extend only the top-edge outro; keep bottom entrances unchanged.
            state = item.rect.bottom <= exitEdgeZone
              ? 'up'
              : item.rect.top >= viewportHeight - edgeZone
                ? 'down'
                : 'visible';
          } else if (scrollDirection < 0) {
            // Scrolling up: extend only the bottom-edge outro; keep top entrances unchanged.
            state = item.rect.top >= viewportHeight - exitEdgeZone
              ? 'down'
              : item.rect.bottom <= edgeZone
                ? 'up'
                : 'visible';
          } else {
            // Initial layout retains the established reveal thresholds.
            state = item.rect.bottom <= edgeZone
              ? 'up'
              : item.rect.top >= viewportHeight - edgeZone
                ? 'down'
                : 'visible';
          }
          return { ...item, state };
        });

      states.forEach(({ element, state, hasMainReveal, hasPremiumReveal }) => {
        if (hasMainReveal) classForState(element, state, 'main');
        if (hasPremiumReveal) classForState(element, state, 'vp');
      });
    };
    const scheduleDirectionalRevealUpdate = () => {
      const nextScrollY = window.scrollY || 0;
      if (nextScrollY > lastScrollY) scrollDirection = 1;
      else if (nextScrollY < lastScrollY) scrollDirection = -1;
      lastScrollY = nextScrollY;
      if (revealFrame) return;
      revealFrame = window.requestAnimationFrame(updateDirectionalRevealStates);
    };
    // The premium-effects script calls the same state updater so overlapping sections
    // cannot receive conflicting incoming/outgoing states from separate observers.
    window.__vpUpdateDirectionalRevealStates = scheduleDirectionalRevealUpdate;

    window.addEventListener('scroll', scheduleDirectionalRevealUpdate, { passive: true });
    window.addEventListener('resize', scheduleDirectionalRevealUpdate, { passive: true });

    const revealObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.dataset.revealSeen = 'true';
        }
      });
      scheduleDirectionalRevealUpdate();
    }, { threshold: 0, rootMargin: '0px' });

    revealTargets.forEach(element => revealObserver.observe(element));
  }

  const emptyState = document.getElementById('emptyState');
  filters.forEach(button => button.addEventListener('click', () => {
    const filter = button.dataset.filter;
    filters.forEach(item => {
      const selected = item === button;
      item.classList.toggle('active', selected);
      item.setAttribute('aria-pressed', String(selected));
    });
    let visibleCount = 0;
    cards.forEach(card => {
      const visible = filter === 'all' || card.dataset.category === filter;
      card.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    if (emptyState) emptyState.hidden = visibleCount !== 0;
  }));

  const category = document.getElementById('songCategory');
  document.querySelectorAll('[data-mood]').forEach(link => link.addEventListener('click', () => {
    const mood = link.dataset.mood;
    const match = [...category.options].find(option => option.text.toLowerCase().includes(mood.toLowerCase()));
    if (match) category.value = match.value;
  }));

  const form = document.getElementById('songRequestForm');
  const status = document.getElementById('formStatus');
  if (form && status) form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const submitButton = form.querySelector('[type="submit"]');
    const originalLabel = submitButton ? submitButton.innerHTML : '';
    const data = new FormData(form);
    const song = String(data.get('songTitle') || '').trim();
    data.set('_subject', 'Song request for Violin Prince: ' + song);
    if (submitButton) { submitButton.disabled = true; submitButton.textContent = 'Sending your request…'; }
    status.className = 'form-status';
    status.textContent = 'Sending your song request…';
    try {
      const response = await fetch(form.dataset.endpoint, {method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(Object.fromEntries(data.entries()))});
      let result = {};
      try { result = await response.json(); } catch (error) {}
      const serviceMessage = String(result.message || result.error || '');
      const validationErrors = Array.isArray(result.errors) ? result.errors : [];
      if (!response.ok || result.ok === false || result.success === false || result.success === 'false' || Boolean(result.error) || validationErrors.length > 0) {
        const details = validationErrors.map(item => item.message || item.field || '').filter(Boolean).join(' ');
        throw new Error(details || serviceMessage || 'Formspree did not accept the request.');
      }
      form.reset();
      status.className = 'form-status is-success';
      status.textContent = 'Thank you! Your song request has been sent to Violin Prince.';
    } catch (error) {
      console.error('Song request submission failed:',error);
      status.className = 'form-status is-error';
      status.textContent = 'Your request could not be sent right now. Please try again. If the problem continues, check that the Formspree form is active and its notification email is verified.';
    } finally {
      if (submitButton) { submitButton.disabled = false; submitButton.innerHTML = originalLabel; }
    }
  });

  
  // Support finale: floral fireworks on support; a short, playful dodge with a real opt-out.
  const supportYes = document.getElementById('supportYes');
  const supportNo = document.getElementById('supportNo');
  const supportStage = document.getElementById('supportActionStage');
  const supportReward = document.getElementById('supportReward');
  const supportStatus = document.getElementById('supportStatus');
  const supportCelebration = document.getElementById('supportCelebration');
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let supportNoDodgeCount = 0;
  let supportNoHasDodgePosition = false;
  let supportCelebrationTimer = null;

  function clearSupportCelebration() {
    if (supportCelebrationTimer) window.clearTimeout(supportCelebrationTimer);
    if (supportCelebration) supportCelebration.replaceChildren();
    supportCelebrationTimer = null;
  }

  function launchSupportFlowers() {
    if (!supportCelebration || prefersReducedMotion) return;
    clearSupportCelebration();
    const flowers = ['✿','❀','✽','✾','❋','✦','✧','✺'];
    const colors = ['#f4dca4','#d6b77a','#f4b8c8','#f2eee0','#c4d890','#f0a7a7','#b9d8bc'];
    const centers = [
      {x:18,y:58},{x:50,y:50},{x:82,y:58}
    ];
    centers.forEach((center, burstIndex) => {
      const count = 24;
      for (let i=0;i<count;i+=1) {
        const angle = (Math.PI*2*i/count) + (Math.random()*.12);
        const distance = 120 + Math.random()*260;
        const drift = 18 + Math.random()*90;
        const particle = document.createElement('span');
        particle.className = 'support-particle';
        particle.textContent = flowers[Math.floor(Math.random()*flowers.length)];
        particle.style.setProperty('--start-x', center.x + '%');
        particle.style.setProperty('--start-y', center.y + '%');
        particle.style.setProperty('--dx', Math.cos(angle)*distance + 'px');
        particle.style.setProperty('--dy', Math.sin(angle)*distance + 'px');
        particle.style.setProperty('--dx2', (Math.cos(angle)*distance + (Math.random()-.5)*drift) + 'px');
        particle.style.setProperty('--dy2', (Math.sin(angle)*distance + 65 + Math.random()*95) + 'px');
        particle.style.setProperty('--spin', (Math.random()>.5?1:-1)*(100+Math.random()*600) + 'deg');
        particle.style.setProperty('--particle-color',colors[Math.floor(Math.random()*colors.length)]);
        particle.style.setProperty('--particle-size',(13+Math.random()*23)+'px');
        particle.style.setProperty('--particle-delay',(Math.random()*.46+burstIndex*.08)+'s');
        supportCelebration.appendChild(particle);
      }
    });
    supportCelebrationTimer = window.setTimeout(clearSupportCelebration, 3900);
  }

  let supportNavigationPending = false;

  if (supportYes && supportReward && supportStatus) {
    supportYes.addEventListener('click', (event) => {
      // Keep the visitor on this page for the full celebration before opening YouTube.
      event.preventDefault();
      if (supportNavigationPending) return;
      supportNavigationPending = true;
      supportYes.setAttribute('aria-disabled', 'true');
      supportReward.hidden = false;
      supportStatus.textContent = 'You unlocked the Golden Bloom — thank you for the encouragement!';
      launchSupportFlowers();

      const rewardHeading = supportReward.querySelector('h3');
      if (rewardHeading) rewardHeading.setAttribute('tabindex', '-1');
      window.setTimeout(() => {
        if (rewardHeading) rewardHeading.focus({ preventScroll: true });
      }, 80);

      // The flowers animate for about four seconds; then continue to the channel.
      window.setTimeout(() => {
        window.location.assign(supportYes.href);
      }, 4200);
    });
  }

  let supportNoIsBouncing = false;
  let supportBounceAnimation = null;
  let supportBounceRunId = 0;

  function resetSupportNoPosition() {
    if (!supportNo) return;
    supportNo.classList.remove('is-bouncing');
    // Clear temporary inline positioning so the original desktop/mobile CSS is restored.
    // Keeping "position: relative" inline overrides the phone layout after the first tap.
    supportNo.style.position = '';
    supportNo.style.left = '';
    supportNo.style.top = '';
    supportNo.style.right = '';
    supportNo.style.bottom = '';
    supportNo.style.width = '';
    supportNo.style.margin = '';
    supportNo.style.transform = '';
    supportNo.style.pointerEvents = '';
    supportNo.style.transition = '';
    if (supportBounceAnimation) {
      try { supportBounceAnimation.cancel(); } catch (error) {}
      supportBounceAnimation = null;
    }
  }

  function settleSupportNoButton(runId) {
    if (!supportNo || (runId !== undefined && runId !== supportBounceRunId)) return;
    supportNoIsBouncing = false;
    resetSupportNoPosition();
    supportNo.textContent = 'Not this time';
    if (supportStatus) {
      supportStatus.textContent = 'Not this time 🌿 Click again to replay the ping-pong.';
    }
  }

  function startSupportNoPingPong(event) {
    if (!supportNo || !supportStage || !supportStatus || supportNoIsBouncing) return;

    // Respect reduced-motion settings, but otherwise replay the bouncing sequence on every click.
    // After each round, the button settles with the same "Not this time" label.
    if (prefersReducedMotion) {
      supportNo.textContent = 'Not this time';
      supportStatus.textContent = 'Not this time 🌿';
      return;
    }

    supportNoIsBouncing = true;
    supportNo.classList.add('is-bouncing');
    supportNo.textContent = 'Not this time';
    supportNo.style.pointerEvents = 'none';
    supportStatus.textContent = 'Ping… pong… ping… pong!';

    const stageRect = supportStage.getBoundingClientRect();
    const buttonRect = supportNo.getBoundingClientRect();
    const maxX = Math.max(0, stageRect.width - buttonRect.width);
    const maxY = Math.max(0, stageRect.height - buttonRect.height);
    const startX = Math.max(0, Math.min(maxX, buttonRect.left - stageRect.left));
    const startY = Math.max(0, Math.min(maxY, buttonRect.top - stageRect.top));

    supportNo.style.position = 'absolute';
    supportNo.style.right = 'auto';
    supportNo.style.bottom = 'auto';
    supportNo.style.width = buttonRect.width + 'px';
    supportNo.style.margin = '0';
    supportNo.style.left = startX + 'px';
    supportNo.style.top = startY + 'px';
    supportNo.style.transform = 'translate(0px, 0px)';

    const corners = [
      {x:maxX, y:0},
      {x:0, y:maxY},
      {x:maxX, y:maxY},
      {x:0, y:0},
      {x:maxX*.5, y:maxY},
      {x:maxX*.5, y:0}
    ];
    let move = 0;
    let currentX = 0;
    let currentY = 0;
    const runId = ++supportBounceRunId;

    function nextBounce() {
      if (!supportNo || !supportNoIsBouncing || runId !== supportBounceRunId) return;
      if (move >= corners.length) {
        settleSupportNoButton(runId);
        return;
      }

      const point = corners[move];
      const nextX = Math.max(0, Math.min(maxX, point.x)) - startX;
      const nextY = Math.max(0, Math.min(maxY, point.y)) - startY;
      const from = 'translate(' + currentX + 'px, ' + currentY + 'px)';
      const to = 'translate(' + nextX + 'px, ' + nextY + 'px)';
      move += 1;

      if (typeof supportNo.animate === 'function') {
        supportBounceAnimation = supportNo.animate(
          [{transform:from},{transform:to}],
          {duration:300, easing:'cubic-bezier(.22,.8,.25,1)', fill:'forwards'}
        );
        supportBounceAnimation.onfinish = () => {
          if (!supportNoIsBouncing || runId !== supportBounceRunId) return;
          currentX = nextX;
          currentY = nextY;
          supportNo.style.transform = to;
          if (supportBounceAnimation) {
            supportBounceAnimation.onfinish = null;
            supportBounceAnimation.cancel();
            supportBounceAnimation = null;
          }
          window.setTimeout(nextBounce, 50);
        };
      } else {
        // Fallback for browsers without the Web Animations API.
        supportNo.style.transition = 'left 300ms ease, top 300ms ease';
        supportNo.style.left = Math.max(0, Math.min(maxX, point.x)) + 'px';
        supportNo.style.top = Math.max(0, Math.min(maxY, point.y)) + 'px';
        currentX = nextX;
        currentY = nextY;
        window.setTimeout(nextBounce, 350);
      }
    }

    void supportNo.offsetWidth;
    window.setTimeout(nextBounce, 60);
  }

  if (supportNo && supportStage && supportStatus) {
    supportNo.addEventListener('click', startSupportNoPingPong);
    supportNo.addEventListener('focus', () => {
      // Keep the button keyboard reachable, and don't change its current label on focus.
      if (supportNoIsBouncing) {
        supportNoIsBouncing = false;
        supportBounceRunId += 1;
      }
      resetSupportNoPosition();
    });
  }

})();