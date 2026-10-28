/* Violin Prince — homepage interactions
   Progressive enhancement for mood-based discovery and the compact sticky header. */
(() => {
  const prefersReducedMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const header = document.querySelector('.site-header');
  if (header) {
    const updateHeader = () => header.classList.toggle('is-scrolled', window.scrollY > 12);
    updateHeader();
    window.addEventListener('scroll', updateHeader, { passive: true });
  }

  const recommendationPanel = document.getElementById('moodRecommendations');
  const moodCards = Array.from(document.querySelectorAll('.mood-card[data-mood]'));

  const moods = {
    'late-night': {
      title: 'Late-night feels',
      intro: 'For the songs that sound a little different when the world gets quiet.',
      songs: [
        { title: 'Dandelions', category: 'ENGLISH · SOFT & DREAMY', video: 'https://www.youtube.com/watch?v=lTySNtT0rzs', page: 'dandelions/', thumbnail: 'https://i.ytimg.com/vi/lTySNtT0rzs/hqdefault.jpg', desc: 'A familiar melody, reimagined on violin.' },
        { title: "Say You Won't Let Go", category: 'ENGLISH · INTIMATE', video: 'https://www.youtube.com/watch?v=3NHpKon_Uq8', page: 'say-you-wont-let-go/', thumbnail: 'https://i.ytimg.com/vi/3NHpKon_Uq8/hqdefault.jpg', desc: 'A gentle, heartfelt violin interpretation.' }
      ],
      filters: [{ label: 'Explore all covers', value: 'all' }]
    },
    'nostalgia': {
      title: 'Nostalgia Mode',
      intro: 'For familiar melodies, old memories and songs that never quite leave.',
      songs: [
        { title: 'Kal Ho Naa Ho', category: 'BOLLYWOOD · TIMELESS', video: 'https://www.youtube.com/watch?v=FlA76nbkReM', page: 'kal-ho-na-ho/', thumbnail: 'https://i.ytimg.com/vi/FlA76nbkReM/hqdefault.jpg', desc: 'A beloved film melody on violin.' },
        { title: 'Hai Apna Dil To Awara', category: 'BOLLYWOOD · CLASSIC', video: 'https://www.youtube.com/watch?v=StnvyGduJ0s', page: 'hai-apna-dil-to-awara/', thumbnail: 'https://i.ytimg.com/vi/StnvyGduJ0s/hqdefault.jpg', desc: 'An old favourite with an easy, flowing feel.' }
      ],
      filters: [{ label: 'Explore all covers', value: 'all' }]
    },
    'bengali-soul': {
      title: 'Bengali Soul',
      intro: 'Bengali favourites and poetic melodies, played with a violin’s voice.',
      songs: [
        { title: 'Bojhena Shey Bojhena', category: 'BENGALI · MODERN CLASSIC', video: 'https://www.youtube.com/watch?v=nKei8ODtFRU', thumbnail: 'https://i.ytimg.com/vi/nKei8ODtFRU/hqdefault.jpg', desc: 'A Bengali favourite, reimagined on violin.' },
        { title: 'Preme Pora Baron', category: 'BENGALI · FEEL-GOOD', video: 'https://www.youtube.com/watch?v=UK7JYzoKKd4', thumbnail: 'https://i.ytimg.com/vi/UK7JYzoKKd4/hqdefault.jpg', desc: 'A melody for the Bengali playlist.' },
        { title: 'Majhe Majhe Tobo', category: 'RABINDRA SANGEET · POETIC', video: 'https://www.youtube.com/watch?v=vAinuVKLKGE', thumbnail: 'https://i.ytimg.com/vi/vAinuVKLKGE/hqdefault.jpg', desc: 'Tagore’s poetry carried by strings.' }
      ],
      filters: [
        { label: 'Browse Bengali covers', value: 'bengali' },
        { label: 'Browse Rabindra Sangeet', value: 'rabindra' }
      ]
    },
    'main-character': {
      title: 'Main Character Energy',
      intro: 'Big feelings, memorable melodies and a soundtrack-worthy violin moment.',
      songs: [
        { title: 'Pasoori', category: 'MAIN CHARACTER · 01', video: 'https://www.youtube.com/watch?v=sj6YxnzylZk', thumbnail: 'https://i.ytimg.com/vi/sj6YxnzylZk/hqdefault.jpg', desc: 'Start with Pasoori.' },
        { title: 'Jai Ho', category: 'MAIN CHARACTER · 02', video: 'https://www.youtube.com/watch?v=1iX1sEudW9M', thumbnail: 'https://i.ytimg.com/vi/1iX1sEudW9M/hqdefault.jpg', desc: 'Then turn the energy up with Jai Ho.' }
      ],
      filters: [{ label: 'Explore all covers', value: 'all' }]
    }
  };

  function makeLink(label, href, className, external) {
    const link = document.createElement('a');
    link.className = className;
    link.textContent = label;
    link.href = href;
    if (external) {
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    }
    return link;
  }

  function renderMood(moodKey, selectedCard) {
    if (!recommendationPanel || !moods[moodKey]) return;
    const mood = moods[moodKey];
    recommendationPanel.replaceChildren();
    recommendationPanel.hidden = false;

    const head = document.createElement('div');
    head.className = 'mood-results-head';
    const copy = document.createElement('div');
    const kicker = document.createElement('p');
    kicker.className = 'eyebrow';
    kicker.textContent = 'YOUR NEXT LISTENS';
    const heading = document.createElement('h3');
    heading.textContent = mood.title;
    const intro = document.createElement('p');
    intro.className = 'mood-results-intro';
    intro.textContent = mood.intro;
    copy.append(kicker, heading, intro);
    const close = document.createElement('button');
    close.className = 'mood-results-close';
    close.type = 'button';
    close.textContent = 'Close';
    close.setAttribute('aria-label', 'Close mood recommendations');
    close.addEventListener('click', () => {
      recommendationPanel.hidden = true;
      moodCards.forEach(card => card.removeAttribute('aria-current'));
      if (selectedCard) selectedCard.focus();
    });
    head.append(copy, close);
    recommendationPanel.append(head);

    const grid = document.createElement('div');
    grid.className = 'mood-results-grid';
    mood.songs.forEach((song, index) => {
      const article = document.createElement('article');
      article.className = 'mood-result-card';
      const artLink = makeLink('', song.video, 'mood-result-art', true);
      const img = document.createElement('img');
      img.src = song.thumbnail;
      img.alt = song.title + ' violin cover thumbnail';
      img.loading = 'lazy';
      img.decoding = 'async';
      img.width = 480;
      img.height = 360;
      const number = document.createElement('span');
      number.className = 'mood-result-number';
      number.textContent = String(index + 1).padStart(2, '0');
      artLink.append(img, number);
      const body = document.createElement('div');
      body.className = 'mood-result-copy';
      const category = document.createElement('span');
      category.className = 'card-category';
      category.textContent = song.category;
      const title = document.createElement('h4');
      title.textContent = song.title;
      const desc = document.createElement('p');
      desc.textContent = song.desc;
      const actions = document.createElement('div');
      actions.className = 'mood-result-links';
      if (song.page) actions.append(makeLink('Song page ↗', song.page, 'mood-result-page', false));
      actions.append(makeLink('Watch on YouTube ↗', song.video, 'mood-result-watch', true));
      body.append(category, title, desc, actions);
      article.append(artLink, body);
      grid.append(article);
    });
    recommendationPanel.append(grid);

    const footer = document.createElement('div');
    footer.className = 'mood-results-footer';
    mood.filters.forEach(filter => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'mood-browse-filter';
      button.dataset.filterValue = filter.value;
      button.textContent = filter.label + ' ↗';
      footer.append(button);
    });
    recommendationPanel.append(footer);

    moodCards.forEach(card => {
      if (card === selectedCard) card.setAttribute('aria-current', 'true');
      else card.removeAttribute('aria-current');
    });

    recommendationPanel.scrollIntoView({
      behavior: prefersReducedMotion ? 'auto' : 'smooth',
      block: 'nearest'
    });
  }

  // Capture-phase handler prevents the legacy request-form mapping from overriding
  // the new actual music-discovery interaction.
  document.addEventListener('click', event => {
    const card = event.target.closest && event.target.closest('.mood-card[data-mood]');
    if (!card) return;
    event.preventDefault();
    event.stopPropagation();
    renderMood(card.dataset.mood, card);
  }, true);

  document.addEventListener('click', event => {
    const button = event.target.closest && event.target.closest('.mood-browse-filter');
    if (!button) return;
    const filterValue = button.dataset.filterValue || 'all';
    const filter = document.querySelector('.filter-chip[data-filter="' + filterValue + '"]');
    if (filter) filter.click();
    const music = document.getElementById('music');
    if (music) music.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'start' });
  });

  // If a visitor changes their viewport or motion preference, content remains usable.
  if (recommendationPanel && recommendationPanel.hidden) {
    recommendationPanel.setAttribute('aria-label', 'Mood-based song recommendations');
  }

  // Add a light reveal to the new featured area and major lower sections.
  const revealTargets = document.querySelectorAll(
    '.featured-art, .featured-copy, .mood-section .section-heading, ' +
    '.mood-section > .section-intro, .about-section, .request-section .request-copy, ' +
    '.request-section .request-form, .connect-section, .support-card'
  );
  if (!prefersReducedMotion && 'IntersectionObserver' in window) {
    document.documentElement.classList.add('vp-motion-ready');
    const revealObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('vp-visible');
        revealObserver.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -28px 0px' });
    revealTargets.forEach(target => {
      target.classList.add('vp-reveal');
      revealObserver.observe(target);
    });
  }

  // Pointer-positioned card light is desktop-only and changes CSS variables, not layout.
  const finePointer = window.matchMedia &&
    window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  if (finePointer) {
    document.querySelectorAll('.music-card, .featured-art').forEach(surface => {
      surface.addEventListener('pointermove', event => {
        if (event.pointerType && event.pointerType !== 'mouse') return;
        const rect = surface.getBoundingClientRect();
        surface.style.setProperty('--pointer-x', ((event.clientX - rect.left) / rect.width * 100) + '%');
        surface.style.setProperty('--pointer-y', ((event.clientY - rect.top) / rect.height * 100) + '%');
      }, { passive: true });
      surface.addEventListener('pointerleave', () => {
        surface.style.removeProperty('--pointer-x');
        surface.style.removeProperty('--pointer-y');
      }, { passive: true });
    });
  }

  if (window.matchMedia && typeof window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener === 'function') {
    window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', event => {
      if (!event.matches) return;
      document.documentElement.classList.remove('vp-motion-ready');
      document.querySelectorAll('.vp-reveal').forEach(element => element.classList.add('vp-visible'));
    });
  }

})();
