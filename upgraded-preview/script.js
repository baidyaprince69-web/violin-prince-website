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

  // Bidirectional scroll reveals: animate both entrance and exit, and replay on every re-entry.
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduceMotion && 'IntersectionObserver' in window) {
    const revealTargets = [
      ...cards,
      ...document.querySelectorAll(
        '.about-section, .section-heading, .section-intro, .filter-row, ' +
        '.mood-card, .request-copy, .request-form, .connect-section, .site-footer'
      )
    ];
    let lastScrollY = window.scrollY;
    revealTargets.forEach((element, index) => {
      if (!element.classList.contains('music-card')) element.classList.add('scroll-reveal');
      if (element.classList.contains('mood-card')) element.style.transitionDelay = (index % 4) * 70 + 'ms';
    });
    document.body.classList.add('motion-ready');

    // Inset observer bounds so the reverse transition starts while items are still visible.
    const revealObserver = new IntersectionObserver(entries => {
      const currentScrollY = window.scrollY;
      const scrollDirection = currentScrollY >= lastScrollY ? 'down' : 'up';
      lastScrollY = currentScrollY;

      entries.forEach(entry => {
        const element = entry.target;
        if (entry.isIntersecting) {
          element.dataset.revealSeen = 'true';
          element.classList.remove('exit-up', 'exit-down');
          element.classList.add('is-visible');
        } else if (element.dataset.revealSeen === 'true') {
          element.classList.remove('is-visible');
          element.classList.toggle('exit-up', scrollDirection === 'down');
          element.classList.toggle('exit-down', scrollDirection === 'up');
        }
      });
    }, { threshold: 0, rootMargin: '-72px 0px -72px 0px' });

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
    if (String(data.get('_honey') || '').trim()) return;
    data.delete('_honey');
    data.set('_subject', 'Song request for Violin Prince: ' + song);
    data.set('_template', 'table');
    if (submitButton) { submitButton.disabled = true; submitButton.textContent = 'Sending your request…'; }
    status.className = 'form-status';
    status.textContent = 'Sending your song request…';
    try {
      const response = await fetch(form.dataset.endpoint, {method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(Object.fromEntries(data.entries()))});
      let result = {};
      try { result = await response.json(); } catch (error) {}
      const serviceMessage = String(result.message || '');
      const serviceSaysActivate = /activat|verif|confirm/i.test(serviceMessage);
      if (!response.ok || result.success === false || result.success === 'false' || serviceSaysActivate) throw new Error((serviceMessage || 'The form service did not accept the request.') + ' (HTTP ' + response.status + ')');
      form.reset();
      status.className = 'form-status is-success';
      status.textContent = 'Thank you! Your song request has been sent to Violin Prince.';
    } catch (error) {
      console.error('Song request submission failed:',error);
      status.className = 'form-status is-error';
      status.textContent = 'Your request could not be sent right now. Please try again. The form may need first-time email activation from the site owner.';
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

})();