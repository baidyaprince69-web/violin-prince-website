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
        '.mood-card, .request-copy, .request-form, .connect-section, .site-footer'
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
    const updateDirectionalRevealStates = () => {
      revealFrame = 0;
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
      const edgeZone = Math.min(160, Math.max(96, viewportHeight * 0.14));
      document.querySelectorAll('.music-card, .scroll-reveal, .vp-reveal').forEach(element => {
        const hasMainReveal = element.dataset.revealSeen === 'true';
        const hasPremiumReveal = element.dataset.vpRevealSeen === 'true';
        if (!hasMainReveal && !hasPremiumReveal) return;

        const rect = element.getBoundingClientRect();
        let state = 'visible';
        if (rect.bottom <= edgeZone) state = 'up';
        else if (rect.top >= viewportHeight - edgeZone) state = 'down';

        if (hasMainReveal) classForState(element, state, 'main');
        if (hasPremiumReveal) classForState(element, state, 'vp');
      });
    };
    const scheduleDirectionalRevealUpdate = () => {
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
        const element = entry.target;
        if (entry.isIntersecting) {
          element.dataset.revealSeen = 'true';
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

  
  // Play Prince's YouTube cover using the official YouTube IFrame Player API.
  // The player stays visible (200px minimum viewport), and native controls remain available.
  const coverVideoId = '3NHpKon_Uq8';
  const coverDock = document.getElementById('youtubeMusicDock');
  const coverToggle = document.getElementById('ytPlayPause');
  const coverButtonIcon = document.getElementById('ytButtonIcon');
  const coverButtonLabel = document.getElementById('ytButtonLabel');
  const coverStatus = document.getElementById('ytPlayerStatus');
  const coverVolume = document.getElementById('ytVolume');
  const barToggle = document.getElementById('ytBarPlayPause');
  const barToggleIcon = document.getElementById('ytBarIcon');
  const barStatus = document.getElementById('ytBarStatus');
  const barProgress = document.getElementById('ytProgress');
  const barCurrentTime = document.getElementById('ytCurrentTime');
  const barDuration = document.getElementById('ytDuration');
  const barVolume = document.getElementById('ytVolumeBar');
  const coverLoadButton = document.getElementById('ytLoadCover');
  const minimizeButton = document.getElementById('ytMinimize');
  const minimizedToggle = document.getElementById('ytMinimizedToggle');

  let coverPlayer = null;
  let coverReady = false;
  let coverPlaying = false;
  let coverWantsPlayback = false;
  let coverVisible = false;
  let coverPauseReason = null;
  let resumeCoverWhenVisible = false;
  let playerVisibilityObserver = null;

  function setCoverUI(playing, message) {
    coverPlaying=playing;
    if(coverDock) coverDock.classList.toggle('is-playing',playing);
    if(coverToggle) coverToggle.setAttribute('aria-pressed',String(playing));
    if(coverButtonIcon) coverButtonIcon.textContent=playing?'Ⅱ':'▶';
    if(coverButtonLabel) coverButtonLabel.textContent=playing?'Pause my cover':'Play my cover';
    if(barToggle){barToggle.setAttribute('aria-pressed',String(playing));barToggle.setAttribute('aria-label',playing?'Pause Say You Won’t Let Go':'Play Say You Won’t Let Go');}
    if(barToggleIcon) barToggleIcon.textContent=playing?'Ⅱ':'▶';
    if(barStatus&&message) barStatus.textContent=message;
    if(coverStatus&&message) coverStatus.textContent=message;
  }
  function formatTime(seconds){if(!Number.isFinite(seconds)||seconds<0)return '--:--';return Math.floor(seconds/60)+':'+Math.floor(seconds%60).toString().padStart(2,'0');}
  function restoreDockForPlayback(){if(coverDock&&coverDock.classList.contains('is-minimized'))coverDock.classList.remove('is-minimized');if(minimizedToggle)minimizedToggle.setAttribute('aria-expanded','true');coverVisible=true;}
  function requestCoverPlayback(){
    restoreDockForPlayback();coverWantsPlayback=true;
    if(!coverReady||!coverPlayer){
      if(coverStatus)coverStatus.textContent='Loading the YouTube player…';
      if(barStatus)barStatus.textContent='Loading the violin cover…';
      if(coverLoadButton){coverLoadButton.disabled=true;const copy=coverLoadButton.querySelector('.yt-load-copy');if(copy)copy.textContent='Loading your cover…';}
      loadCoverPlayerAPI();return;
    }
    safePlayCover();
  }
  function pauseCoverPlayback(){coverWantsPlayback=false;if(coverPlayer&&coverReady)coverPlayer.pauseVideo();setCoverUI(false,'Paused · press Play to continue');}

  function safePlayCover() {
    if (!coverReady || !coverPlayer || !coverWantsPlayback) return;
    if (coverDock && coverDock.classList.contains('is-minimized')) return;
    if (!coverVisible) {
      if (coverStatus) coverStatus.textContent = 'Player ready · press Play when it is in view';
      return;
    }
    try {
      coverPlayer.playVideo();
      if (coverStatus) coverStatus.textContent = 'Starting your violin cover…';
    } catch (error) {
      setCoverUI(false, 'Press Play to start your cover.');
    }
  }

  function createCoverPlayer() {
    if (!window.YT || !window.YT.Player || coverPlayer) return;
    if (coverLoadButton) coverLoadButton.hidden = true;
    const mount = document.getElementById('violinYouTubePlayer');
    if (mount) mount.hidden = false;
    coverPlayer = new window.YT.Player('violinYouTubePlayer', {
      width: '360',
      height: '203',
      videoId: coverVideoId,
      playerVars: {
        autoplay: 0,
        controls: 1,
        loop: 1,
        playlist: coverVideoId,
        playsinline: 1,
        rel: 0,
        enablejsapi: 1,
        origin: window.location.origin
      },
      events: {
        onReady: event => {
          coverReady = true;
          try {
            event.target.getIframe().setAttribute('title', "Say You Won't Let Go — Violin Prince violin cover");
            const initialVolume = Number(barVolume ? barVolume.value : (coverVolume ? coverVolume.value : 42));
          event.target.setVolume(initialVolume);
          if (coverVolume) coverVolume.value = String(initialVolume);
          if (barVolume) barVolume.value = String(initialVolume);
          if (barProgress) barProgress.disabled = false;
          } catch (error) {}
          if (coverStatus) coverStatus.textContent = 'Ready · press Play to listen';
          safePlayCover();
        },
        onStateChange: event => {
          const states = window.YT.PlayerState;
          if (event.data === states.PLAYING) {
            resumeCoverWhenVisible = false;
            setCoverUI(true, "Playing · Say You Won't Let Go");
          } else if (event.data === states.PAUSED) {
            setCoverUI(false, coverPauseReason === 'visibility'
              ? 'Paused while this tab is away'
              : 'Paused · press Play to continue');
            if (coverPauseReason !== 'visibility') coverWantsPlayback = false;
            coverPauseReason = null;
          } else if (event.data === states.ENDED && coverWantsPlayback && coverVisible) {
            // Loop parameter is enabled too; this is a fallback if the player reports ENDED.
            try {
              event.target.seekTo(0, true);
              event.target.playVideo();
            } catch (error) {}
          } else if (event.data === states.CUED) {
            if (!coverPlaying && coverStatus) coverStatus.textContent = 'Ready · press Play to listen';
          }
        },
        onAutoplayBlocked: () => {
          coverWantsPlayback = false;
          setCoverUI(false, 'Autoplay blocked · press Play to listen');
        },
        onError: () => {
          coverWantsPlayback = false;
          setCoverUI(false, 'Could not load the cover · use Open on YouTube');
        }
      }
    });
  }

  function loadCoverPlayerAPI() {
    if (window.YT && window.YT.Player) {
      createCoverPlayer();
      return;
    }
    const previousReadyCallback = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      if (typeof previousReadyCallback === 'function') previousReadyCallback();
      createCoverPlayer();
    };
    if (!document.querySelector('script[data-violin-prince-youtube-api]')) {
      const apiScript = document.createElement('script');
      apiScript.src = 'https://www.youtube.com/iframe_api';
      apiScript.async = true;
      apiScript.dataset.violinPrinceYoutubeApi = 'true';
      apiScript.onerror = () => { if(coverLoadButton){coverLoadButton.disabled=false;const copy=coverLoadButton.querySelector('.yt-load-copy');if(copy)copy.textContent='Could not load · try again';}setCoverUI(false,'YouTube could not load · check your connection');};
      document.head.appendChild(apiScript);
    }
  }

  if(coverToggle)coverToggle.addEventListener('click',()=>coverPlaying?pauseCoverPlayback():requestCoverPlayback());
  if(barToggle)barToggle.addEventListener('click',()=>coverPlaying?pauseCoverPlayback():requestCoverPlayback());
  if(coverLoadButton)coverLoadButton.addEventListener('click',requestCoverPlayback);
  if(minimizeButton)minimizeButton.addEventListener('click',()=>{if(coverPlaying||coverWantsPlayback)pauseCoverPlayback();if(coverDock)coverDock.classList.add('is-minimized');if(minimizedToggle)minimizedToggle.setAttribute('aria-expanded','false');});
  if(minimizedToggle)minimizedToggle.addEventListener('click',()=>{if(coverDock)coverDock.classList.remove('is-minimized');minimizedToggle.setAttribute('aria-expanded','true');});

  function setCoverVolume(value){const volume=Math.max(0,Math.min(100,Number(value)||0));if(coverVolume)coverVolume.value=String(volume);if(barVolume)barVolume.value=String(volume);if(coverReady&&coverPlayer)coverPlayer.setVolume(volume);}
  if(coverVolume)coverVolume.addEventListener('input',()=>setCoverVolume(coverVolume.value));
  if(barVolume)barVolume.addEventListener('input',()=>setCoverVolume(barVolume.value));
  if(barProgress){
    barProgress.addEventListener('input',()=>{if(!coverReady||!coverPlayer)return;const duration=coverPlayer.getDuration();if(duration>0&&barCurrentTime)barCurrentTime.textContent=formatTime(duration*Number(barProgress.value)/1000);});
    barProgress.addEventListener('change',()=>{if(!coverReady||!coverPlayer)return;const duration=coverPlayer.getDuration();if(duration>0)coverPlayer.seekTo(duration*Number(barProgress.value)/1000,true);});
  }
  const barProgressTimer=window.setInterval(()=>{if(!coverReady||!coverPlayer)return;try{const duration=coverPlayer.getDuration(),current=coverPlayer.getCurrentTime();if(duration>0){if(barProgress&&document.activeElement!==barProgress)barProgress.value=String(Math.round(current/duration*1000));if(barCurrentTime)barCurrentTime.textContent=formatTime(current);if(barDuration)barDuration.textContent=formatTime(duration);}}catch(error){}},1000);

  // Only attempt automatic playback while more than half of the visible player is on screen.
  if ('IntersectionObserver' in window) {
    playerVisibilityObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        coverVisible = entry.isIntersecting && entry.intersectionRatio > 0.5;
        if (coverVisible && coverWantsPlayback && coverReady && !coverPlaying) {
          safePlayCover();
        } else if (!coverVisible && coverPlaying) {
          resumeCoverWhenVisible = true;
          coverPauseReason = 'visibility';
          if (coverPlayer) coverPlayer.pauseVideo();
        } else if (coverVisible && resumeCoverWhenVisible && coverWantsPlayback) {
          safePlayCover();
        }
      });
    }, { threshold: [0, 0.5, 0.75, 1] });
    // Observe the stable wrapper; the YouTube API replaces the inner mount node with an iframe.
    const playerVisibilityTarget = document.querySelector('.yt-player-shell');
    if (playerVisibilityTarget) playerVisibilityObserver.observe(playerVisibilityTarget);
  } else {
    coverVisible = true;
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden && coverPlaying && coverPlayer) {
      resumeCoverWhenVisible = true;
      coverPauseReason = 'visibility';
      coverPlayer.pauseVideo();
    } else if (!document.hidden && resumeCoverWhenVisible && coverWantsPlayback) {
      safePlayCover();
    }
  });

  window.addEventListener('pagehide', () => {
    coverWantsPlayback = false;
    if (playerVisibilityObserver) playerVisibilityObserver.disconnect();
    window.clearInterval(barProgressTimer);
    if (coverPlayer && coverReady) {
      try { coverPlayer.stopVideo(); } catch (error) {}
    }
  });

  // Keep the page light: load the YouTube API only after the visitor presses Play.

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