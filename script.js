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