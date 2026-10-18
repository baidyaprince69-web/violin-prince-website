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
})();