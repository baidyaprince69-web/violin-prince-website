/* Collection search, live counts and category shortcuts.
   Existing playback, sorting, mood recommendations and request-form logic remain untouched. */
(() => {
  const music = document.getElementById('music');
  const grid = document.getElementById('musicGrid');
  if (!music || !grid) return;

  const cards = Array.from(grid.querySelectorAll('.music-card'));
  const filters = Array.from(music.querySelectorAll('.filter-chip'));
  const search = document.getElementById('collectionSearch');
  const clear = document.getElementById('collectionSearchClear');
  const resultCount = document.getElementById('collectionResultCount');
  const emptyState = document.getElementById('emptyState');
  const reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Counts are read from the catalogue itself, so they stay accurate as new cards are added.
  document.querySelectorAll('[data-collection-count]').forEach((element) => {
    const category = element.dataset.collectionCount;
    const count = cards.filter((card) => card.dataset.category === category).length;
    element.textContent = String(count).padStart(2, '0') + (count === 1 ? ' cover' : ' covers');
  });
  document.querySelectorAll('[data-collection-total]').forEach((element) => {
    element.textContent = String(cards.length);
  });

  const getActiveFilter = () => {
    const active = filters.find((button) => button.classList.contains('active'));
    return active ? active.dataset.filter : 'all';
  };

  const applySearchAndFilter = () => {
    const selectedCategory = getActiveFilter();
    const query = search ? search.value.trim().toLocaleLowerCase() : '';
    let visibleCount = 0;

    cards.forEach((card) => {
      const categoryMatches = selectedCategory === 'all' || card.dataset.category === selectedCategory;
      const searchableText = [
        card.querySelector('h3')?.textContent || '',
        card.querySelector('.card-category')?.textContent || '',
        card.querySelector('.card-copy p')?.textContent || ''
      ].join(' ').toLocaleLowerCase();
      const visible = categoryMatches && (!query || searchableText.includes(query));
      card.hidden = !visible;
      if (visible) visibleCount += 1;
    });

    if (emptyState) emptyState.hidden = visibleCount !== 0;
    if (resultCount) {
      const scope = selectedCategory === 'all'
        ? 'all categories'
        : (filters.find((button) => button.dataset.filter === selectedCategory)?.textContent.trim() || selectedCategory);
      resultCount.textContent = query
        ? 'Showing ' + visibleCount + ' of ' + cards.length + ' performances · ' + scope + ' · Search: “' + search.value.trim() + '”'
        : 'Showing ' + visibleCount + ' of ' + cards.length + ' performances · ' + scope;
    }
    if (clear) clear.hidden = !query;
  };

  // The original category script runs first; this then combines its active category with search.
  filters.forEach((button) => button.addEventListener('click', applySearchAndFilter));
  if (search) search.addEventListener('input', applySearchAndFilter);
  if (clear && search) {
    clear.addEventListener('click', () => {
      search.value = '';
      applySearchAndFilter();
      search.focus();
    });
  }

  // Every category tile reuses the main filter instead of creating a second filter system.
  document.querySelectorAll('[data-collection-filter]').forEach((link) => {
    link.addEventListener('click', () => {
      const category = link.dataset.collectionFilter;
      const filterButton = filters.find((button) => button.dataset.filter === category);
      if (!filterButton) return;
      if (search) search.value = '';
      filterButton.click();
      applySearchAndFilter();
      if (music && typeof music.scrollIntoView === 'function') {
        music.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
      }
    });
  });

  applySearchAndFilter();
})();