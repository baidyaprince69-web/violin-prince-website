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
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    const song = String(data.get('songTitle') || '').trim();
    const artist = String(data.get('artistName') || '').trim();
    const kind = String(data.get('songCategory') || 'Not sure');
    const message = String(data.get('songMessage') || '').trim();
    const body = [
      'Hello Violin Prince,',
      '',
      'I would love to suggest a song for a future violin cover:',
      'Song: ' + song,
      'Original artist: ' + (artist || 'Not specified'),
      'Category: ' + kind,
      message ? 'Why this song matters to me: ' + message : '',
      '',
      'Thank you!'
    ].filter((line, index, all) => line !== '' || (index > 0 && all[index - 1] !== '')).join('\n');
    const subject = 'Song request for Violin Prince: ' + song;
    const mailto = 'mailto:baidyaprince69@gmail.com?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body);
    status.textContent = 'Opening an email addressed to baidyaprince69@gmail.com. Please review the request and press Send in your email app.';
    window.location.href = mailto;
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

  let coverPlayer = null;
  let coverReady = false;
  let coverPlaying = false;
  let coverWantsPlayback = true;
  let coverVisible = false;
  let coverPauseReason = null;
  let resumeCoverWhenVisible = false;
  let playerVisibilityObserver = null;

  function setCoverUI(playing, message) {
    coverPlaying = playing;
    if (coverDock) coverDock.classList.toggle('is-playing', playing);
    if (coverToggle) coverToggle.setAttribute('aria-pressed', String(playing));
    if (coverButtonIcon) coverButtonIcon.textContent = playing ? 'Ⅱ' : '▶';
    if (coverButtonLabel) coverButtonLabel.textContent = playing ? 'Pause my cover' : 'Play my cover';
    if (coverStatus && message) coverStatus.textContent = message;
  }

  function safePlayCover() {
    if (!coverReady || !coverPlayer || !coverWantsPlayback) return;
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
            event.target.setVolume(Number(coverVolume ? coverVolume.value : 42));
          } catch (error) {}
          if (coverStatus) coverStatus.textContent = 'Your cover is ready · trying to start music';
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
      apiScript.onerror = () => setCoverUI(false, 'YouTube player could not load · check your connection');
      document.head.appendChild(apiScript);
    }
  }

  if (coverToggle) {
    coverToggle.addEventListener('click', () => {
      if (!coverReady || !coverPlayer) {
        coverWantsPlayback = true;
        if (coverStatus) coverStatus.textContent = 'Loading YouTube player…';
        loadCoverPlayerAPI();
        return;
      }
      if (coverPlaying) {
        coverWantsPlayback = false;
        coverPlayer.pauseVideo();
        setCoverUI(false, 'Paused · press Play to continue');
      } else {
        coverWantsPlayback = true;
        safePlayCover();
      }
    });
  }

  if (coverVolume) {
    coverVolume.addEventListener('input', () => {
      if (coverReady && coverPlayer) coverPlayer.setVolume(Number(coverVolume.value));
    });
  }

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
    if (coverPlayer && coverReady) {
      try { coverPlayer.stopVideo(); } catch (error) {}
    }
  });

  // The API is loaded on page open; autoplay is attempted only once the player is visible.
  loadCoverPlayerAPI();

})();