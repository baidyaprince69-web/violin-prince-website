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

  // Original, lightweight ambient motif generated with the Web Audio API.
  // Browsers may block first-visit autoplay; the visible Play control always remains available.
  const ambientPlayer = document.getElementById('ambientPlayer');
  const ambientToggle = document.getElementById('ambientToggle');
  const ambientLabel = document.getElementById('ambientLabel');
  const ambientStatus = document.getElementById('ambientStatus');
  const ambientSymbol = document.getElementById('ambientToggleSymbol');
  const ambientVolume = document.getElementById('ambientVolume');

  let audioContext = null;
  let musicBus = null;
  let masterGain = null;
  let compressor = null;
  let dryGain = null;
  let wetGain = null;
  let reverb = null;
  let schedulerId = null;
  let isMusicPlaying = false;
  let shouldPlayMusic = false;
  let resumeAfterVisibility = false;
  let stepIndex = 0;
  let nextStepTime = 0;
  let closeContextTimer = null;
  const bpm = 66;
  const stepDuration = 60 / bpm / 2;
  const stepsPerPhrase = 32;
  const phraseLength = stepDuration * stepsPerPhrase;

  function setAmbientStatus(playing, message) {
    if (ambientPlayer) ambientPlayer.classList.toggle('is-playing', playing);
    if (ambientToggle) {
      ambientToggle.setAttribute('aria-pressed', String(playing));
      ambientToggle.setAttribute('aria-label', playing
        ? 'Pause background music'
        : 'Play soft piano and violin ambience');
    }
    if (ambientLabel) ambientLabel.textContent = playing ? 'Ambience is playing' : 'Play the ambience';
    if (ambientStatus) ambientStatus.textContent = message;
    if (ambientSymbol) ambientSymbol.textContent = playing ? 'Ⅱ' : '♫';
  }

  function midiFrequency(midi) {
    return 440 * Math.pow(2, (midi - 69) / 12);
  }

  function createReverbImpulse(context) {
    const seconds = 2.1;
    const length = Math.floor(context.sampleRate * seconds);
    const buffer = context.createBuffer(2, length, context.sampleRate);
    for (let channel = 0; channel < 2; channel += 1) {
      const data = buffer.getChannelData(channel);
      for (let i = 0; i < length; i += 1) {
        const decay = Math.pow(1 - i / length, 3.1);
        data[i] = (Math.random() * 2 - 1) * decay * 0.32;
      }
    }
    return buffer;
  }

  function createAudioEngine() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error('Web Audio is not supported in this browser.');
    audioContext = new AudioContextClass();
    musicBus = audioContext.createGain();
    dryGain = audioContext.createGain();
    wetGain = audioContext.createGain();
    reverb = audioContext.createConvolver();
    masterGain = audioContext.createGain();
    compressor = audioContext.createDynamicsCompressor();

    dryGain.gain.value = 0.88;
    wetGain.gain.value = 0.22;
    reverb.buffer = createReverbImpulse(audioContext);
    masterGain.gain.value = 0.0001;
    compressor.threshold.value = -20;
    compressor.knee.value = 18;
    compressor.ratio.value = 2.4;
    compressor.attack.value = 0.012;
    compressor.release.value = 0.22;

    musicBus.connect(dryGain);
    dryGain.connect(masterGain);
    musicBus.connect(reverb);
    reverb.connect(wetGain);
    wetGain.connect(masterGain);
    masterGain.connect(compressor);
    compressor.connect(audioContext.destination);
  }

  function applyMasterVolume(duration) {
    if (!audioContext || !masterGain) return;
    const now = audioContext.currentTime;
    const sliderValue = ambientVolume ? Number(ambientVolume.value) / 100 : 0.42;
    const target = Math.max(0.0001, sliderValue * 0.78);
    masterGain.gain.cancelScheduledValues(now);
    masterGain.gain.setValueAtTime(Math.max(0.0001, masterGain.gain.value), now);
    masterGain.gain.linearRampToValueAtTime(isMusicPlaying ? target : 0.0001, now + (duration || 0.18));
  }

  function pianoNote(midi, start, strength, length) {
    if (!audioContext || !musicBus) return;
    const context = audioContext;
    const fundamental = midiFrequency(midi);
    const envelope = context.createGain();
    const filter = context.createBiquadFilter();
    const now = Math.max(start, context.currentTime + 0.006);
    const duration = length || 1.55;
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(2700, now);
    filter.Q.value = 0.5;
    envelope.gain.setValueAtTime(0.0001, now);
    envelope.gain.linearRampToValueAtTime(strength, now + 0.014);
    envelope.gain.exponentialRampToValueAtTime(0.0001, now + duration);
    filter.connect(envelope);
    envelope.connect(musicBus);

    const harmonics = [
      { ratio: 1, gain: 1 },
      { ratio: 2, gain: 0.23 },
      { ratio: 3, gain: 0.07 }
    ];
    harmonics.forEach(partial => {
      const oscillator = context.createOscillator();
      const partialGain = context.createGain();
      oscillator.type = 'sine';
      oscillator.frequency.setValueAtTime(fundamental * partial.ratio, now);
      oscillator.detune.value = partial.ratio === 1 ? -1 : 1;
      partialGain.gain.value = partial.gain;
      oscillator.connect(partialGain);
      partialGain.connect(filter);
      oscillator.start(now);
      oscillator.stop(now + duration + 0.04);
    });
  }

  function violinNote(midi, start, duration, strength) {
    if (!audioContext || !musicBus) return;
    const context = audioContext;
    const now = Math.max(start, context.currentTime + 0.006);
    const noteLength = duration || 1.0;
    const oscillator = context.createOscillator();
    const filter = context.createBiquadFilter();
    const envelope = context.createGain();
    const vibrato = context.createOscillator();
    const vibratoDepth = context.createGain();

    oscillator.type = 'sawtooth';
    oscillator.frequency.setValueAtTime(midiFrequency(midi), now);
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(1550, now);
    filter.Q.value = 0.7;

    vibrato.type = 'sine';
    vibrato.frequency.value = 5.1;
    vibratoDepth.gain.value = 3.1;
    vibrato.connect(vibratoDepth);
    vibratoDepth.connect(oscillator.detune);

    envelope.gain.setValueAtTime(0.0001, now);
    envelope.gain.linearRampToValueAtTime(strength, now + 0.19);
    envelope.gain.setValueAtTime(strength * 0.78, now + Math.max(0.24, noteLength - 0.17));
    envelope.gain.exponentialRampToValueAtTime(0.0001, now + noteLength + 0.24);

    oscillator.connect(filter);
    filter.connect(envelope);
    envelope.connect(musicBus);
    oscillator.start(now);
    vibrato.start(now);
    oscillator.stop(now + noteLength + 0.28);
    vibrato.stop(now + noteLength + 0.28);
  }

  const chordProgression = [
    [60, 64, 67, 71], // Cmaj7
    [57, 60, 64, 67], // Am7
    [53, 57, 60, 64], // Fmaj7
    [55, 57, 62, 67]  // Gsus2
  ];
  const arpeggioPattern = [0, 2, 1, 2, 3, 2, 1, 2];
  const violinSteps = [
    { step: 0, note: 72 }, { step: 3, note: 76 },
    { step: 8, note: 79 }, { step: 11, note: 76 },
    { step: 16, note: 74 }, { step: 19, note: 72 },
    { step: 24, note: 67 }, { step: 27, note: 72 }
  ];

  function scheduleStep(index, start) {
    const step = index % stepsPerPhrase;
    const bar = Math.floor(step / 8);
    const stepInBar = step % 8;
    const chord = chordProgression[bar];
    const noteIndex = arpeggioPattern[stepInBar];
    const pianoStrength = (stepInBar === 0 || stepInBar === 4) ? 0.23 : 0.17;

    pianoNote(chord[noteIndex], start, pianoStrength, stepInBar === 0 ? 1.7 : 1.35);
    if (stepInBar === 0) {
      pianoNote(chord[0] - 12, start, 0.105, 2.0);
    }
    const violin = violinSteps.find(item => item.step === step);
    if (violin) violinNote(violin.note, start, 1.13, 0.105);
  }

  function scheduleAhead() {
    if (!audioContext || !isMusicPlaying) return;
    const horizon = audioContext.currentTime + 0.28;
    while (nextStepTime < horizon) {
      scheduleStep(stepIndex, nextStepTime);
      stepIndex += 1;
      nextStepTime += stepDuration;
    }
  }

  function beginScheduler() {
    if (schedulerId) window.clearInterval(schedulerId);
    stepIndex = 0;
    nextStepTime = audioContext.currentTime + 0.18;
    scheduleAhead();
    schedulerId = window.setInterval(scheduleAhead, 90);
  }

  async function startAmbientMusic(userInitiated) {
    try {
      if (closeContextTimer) {
        window.clearTimeout(closeContextTimer);
        closeContextTimer = null;
      }
      if (!audioContext || audioContext.state === 'closed') createAudioEngine();
      await audioContext.resume();
      if (audioContext.state !== 'running') throw new Error('Audio playback has not been activated.');
      isMusicPlaying = true;
      shouldPlayMusic = true;
      resumeAfterVisibility = false;
      beginScheduler();
      applyMasterVolume(1.35);
      setAmbientStatus(true, 'Softly playing · continues as you scroll');
    } catch (error) {
      isMusicPlaying = false;
      if (userInitiated) {
        setAmbientStatus(false, 'Audio could not start · try checking browser sound settings');
      } else {
        setAmbientStatus(false, 'Tap to begin · soft piano + violin');
      }
    }
  }

  function stopAmbientMusic(options) {
    const keepIntent = Boolean(options && options.keepIntent);
    if (!keepIntent) {
      shouldPlayMusic = false;
      resumeAfterVisibility = false;
    }
    isMusicPlaying = false;
    if (schedulerId) {
      window.clearInterval(schedulerId);
      schedulerId = null;
    }
    applyMasterVolume(0.45);
    setAmbientStatus(false, keepIntent ? 'Pausing while this tab is away' : 'Paused · your soundtrack is waiting');
    if (closeContextTimer) window.clearTimeout(closeContextTimer);
    closeContextTimer = window.setTimeout(() => {
      if (!isMusicPlaying && audioContext) {
        const oldContext = audioContext;
        audioContext = null;
        musicBus = null;
        masterGain = null;
        dryGain = null;
        wetGain = null;
        reverb = null;
        compressor = null;
        oldContext.close().catch(() => {});
      }
    }, 620);
  }

  if (ambientToggle) {
    ambientToggle.addEventListener('click', () => {
      if (isMusicPlaying) stopAmbientMusic();
      else startAmbientMusic(true);
    });
  }
  if (ambientVolume) {
    ambientVolume.addEventListener('input', () => {
      if (isMusicPlaying) applyMasterVolume(0.08);
    });
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden && isMusicPlaying) {
      resumeAfterVisibility = shouldPlayMusic;
      stopAmbientMusic({ keepIntent: true });
    } else if (!document.hidden && resumeAfterVisibility && shouldPlayMusic) {
      startAmbientMusic(false);
    }
  });

  window.addEventListener('pagehide', () => {
    if (schedulerId) window.clearInterval(schedulerId);
    schedulerId = null;
    isMusicPlaying = false;
    shouldPlayMusic = false;
    if (audioContext && audioContext.state !== 'closed') audioContext.close().catch(() => {});
  });

  // Attempt autoplay only where the browser permits it. Otherwise show the Play control.
  window.setTimeout(() => startAmbientMusic(false), 280);

})();