/* Violin Prince platform audio pilot.
   SoundCloud plays run through the official visible SoundCloud Widget.
   YouTube playback is deliberately left to the native YouTube Play control. */
(function () {
  'use strict';

  var room = document.getElementById('soundcloud-listening-room');
  var iframe = document.getElementById('vp-soundcloud-widget');
  var playButton = document.getElementById('floating-play-button');
  var playIcon = document.getElementById('floating-play-icon');
  var bar = document.getElementById('floating-music-bar');
  var status = document.getElementById('floating-player-status');
  var progress = document.getElementById('floating-progress');
  var currentTimeLabel = document.getElementById('floating-current-time');
  var durationLabel = document.getElementById('floating-duration');

  if (!room || !iframe || !playButton || !bar) return;

  var trackUrl = room.getAttribute('data-track-url') || '';
  var trackTitle = room.getAttribute('data-track-title') || '';
  var apiPromise = null;
  var widget = null;
  var initPromise = null;
  var widgetReady = false;
  var trackReady = false;
  var isPlaying = false;
  var modeSelected = false;
  var durationMs = 0;
  var activeTrack = null;

  function setStatus(message) {
    if (status) status.textContent = message;
  }

  function setIcon(mode) {
    var icons = {
      play: "<svg viewBox='0 0 20 20' aria-hidden='true' focusable='false'><path d='M6 3.8v12.4c0 .6.7 1 1.2.7l9-6.2a.9.9 0 0 0 0-1.4l-9-6.2c-.5-.3-1.2.1-1.2.7Z' fill='currentColor'></path></svg>",
      pause: "<svg viewBox='0 0 20 20' aria-hidden='true' focusable='false'><rect x='5' y='5' width='10' height='10' rx='1.2' fill='currentColor'></rect></svg>"
    };
    if (playIcon) playIcon.innerHTML = icons[mode] || icons.play;
    playButton.setAttribute('aria-label', (mode === 'pause' ? 'Pause ' : 'Play ') + trackTitle + ' on SoundCloud');
  }

  function formatTime(milliseconds) {
    var seconds = Math.max(0, Math.floor((Number(milliseconds) || 0) / 1000));
    var minutes = Math.floor(seconds / 60);
    var remainder = seconds % 60;
    return minutes + ':' + (remainder < 10 ? '0' : '') + remainder;
  }

  function updateProgress(positionMs) {
    if (!progress || !durationMs || !isFinite(durationMs)) return;
    var position = Math.max(0, Math.min(durationMs, Number(positionMs) || 0));
    var value = Math.max(0, Math.min(1000, Math.round(position / durationMs * 1000)));
    progress.value = String(value);
    progress.style.setProperty('--bar-progress', (value / 10) + '%');
    if (currentTimeLabel) currentTimeLabel.textContent = formatTime(position);
    if (durationLabel) durationLabel.textContent = formatTime(durationMs);
    progress.disabled = false;
  }

  function ensureApi() {
    if (window.SC && window.SC.Widget) return Promise.resolve();
    if (apiPromise) return apiPromise;

    apiPromise = new Promise(function (resolve, reject) {
      var existing = document.querySelector('script[data-vp-soundcloud-api]');
      var script = existing || document.createElement('script');

      function ready() {
        if (window.SC && window.SC.Widget) resolve();
        else reject(new Error('SoundCloud Widget API did not initialize.'));
      }

      if (existing) {
        if (existing.dataset.vpLoaded === 'true') {
          ready();
          return;
        }
        script.addEventListener('load', function () {
          script.dataset.vpLoaded = 'true';
          ready();
        }, { once: true });
        script.addEventListener('error', function () {
          if (script.parentNode) script.parentNode.removeChild(script);
          reject(new Error('SoundCloud Widget API failed to load.'));
        }, { once: true });
        return;
      }

      script.src = 'https://w.soundcloud.com/player/api.js';
      script.async = true;
      script.dataset.vpSoundcloudApi = 'true';
      script.onload = function () {
        script.dataset.vpLoaded = 'true';
        ready();
      };
      script.onerror = function () {
        if (script.parentNode) script.parentNode.removeChild(script);
        reject(new Error('SoundCloud Widget API failed to load.'));
      };
      document.head.appendChild(script);
    });

    return apiPromise;
  }

  function bindWidgetEvents() {
    var events = window.SC.Widget.Events;

    widget.bind(events.READY, function () {
      widgetReady = true;
      setStatus('VERIFYING THE SHARED SOUNDCLOUD TRACK…');
      widget.getCurrentSound(function (sound) {
        if (!sound || !sound.title) {
          trackReady = false;
          modeSelected = false;
          playButton.disabled = true;
          setIcon('play');
          setStatus('SOUNDCLOUD LINK COULD NOT BE RESOLVED · USE YOUTUBE');
          return;
        }

        activeTrack = sound;
        trackReady = true;
        durationMs = Number(sound.duration) || 0;
        widget.getDuration(function (duration) {
          if (Number(duration) > 0) durationMs = Number(duration);
          updateProgress(0);
        });
        playButton.disabled = false;
        setIcon('play');
        setStatus('SOUNDCLOUD READY · ' + sound.title);
      });
    });

    widget.bind(events.PLAY, function () {
      modeSelected = true;
      isPlaying = true;
      bar.classList.add('is-playing');
      setIcon('pause');
      setStatus('SOUNDCLOUD · NOW PLAYING');
      var youtube = window.ViolinPrinceYouTube;
      if (youtube && typeof youtube.pauseIfPlaying === 'function') youtube.pauseIfPlaying();
    });

    widget.bind(events.PAUSE, function () {
      isPlaying = false;
      bar.classList.remove('is-playing');
      setIcon('play');
      if (modeSelected) setStatus('SOUNDCLOUD · PAUSED');
    });

    widget.bind(events.FINISH, function () {
      isPlaying = false;
      bar.classList.remove('is-playing');
      setIcon('play');
      updateProgress(durationMs);
      setStatus('SOUNDCLOUD · TRACK FINISHED');
    });

    widget.bind(events.PLAY_PROGRESS, function (event) {
      if (event && Number(event.currentPosition) >= 0) updateProgress(Number(event.currentPosition));
    });

    widget.bind(events.ERROR, function () {
      trackReady = false;
      isPlaying = false;
      modeSelected = false;
      playButton.disabled = true;
      bar.classList.remove('is-playing');
      setIcon('play');
      setStatus('SOUNDCLOUD UNAVAILABLE · USE YOUTUBE VIDEO');
    });
  }

  function initialize() {
    if (widget) return Promise.resolve();
    if (initPromise) return initPromise;

    room.hidden = false;
    room.classList.add('is-open');
    modeSelected = true;
    setStatus('CONNECTING TO SOUNDCLOUD…');
    playButton.disabled = true;
    initPromise = ensureApi().then(function () {
      widget = window.SC.Widget(iframe);
      bindWidgetEvents();

      if (!trackUrl) throw new Error('No SoundCloud track URL was provided.');
      var params = [
        'url=' + encodeURIComponent(trackUrl),
        'color=%23e7a84f',
        'auto_play=false',
        'hide_related=false',
        'show_comments=false',
        'show_user=true',
        'show_playcount=true',
        'show_reposts=false',
        'visual=false'
      ];
      iframe.src = 'https://w.soundcloud.com/player/?' + params.join('&');
    }).catch(function () {
      initPromise = null;
      widget = null;
      apiPromise = null;
      playButton.disabled = false;
      setStatus('SOUNDCLOUD COULD NOT LOAD · TRY AGAIN OR OPEN THE PROFILE');
    });

    return initPromise;
  }

  function toggle() {
    modeSelected = true;
    if (!widget) {
      initialize();
      return;
    }
    if (!trackReady) {
      setStatus(widgetReady ? 'WAITING FOR THE SOUNDCLOUD TRACK…' : 'SOUNDCLOUD IS STILL LOADING…');
      return;
    }
    if (isPlaying) widget.pause();
    else widget.play();
  }

  function pauseIfPlaying() {
    modeSelected = false;
    if (widget && isPlaying) widget.pause();
  }

  playButton.disabled = false;
  setIcon('play');
  playButton.addEventListener('click', toggle);

  window.ViolinPrinceSoundCloud = {
    toggle: toggle,
    isPlaying: function () { return isPlaying; },
    isActive: function () { return modeSelected; },
    pauseIfPlaying: pauseIfPlaying,
    seekTo: function (milliseconds) {
      if (widget && trackReady) widget.seekTo(Math.max(0, Number(milliseconds) || 0));
    },
    getDurationMs: function () { return durationMs; }
  };

  window.addEventListener('pagehide', pauseIfPlaying);
})();