(function () {
  'use strict';
  if (!document.body || document.getElementById('vpShareTrigger')) return;

  var fab = document.createElement('button');
  fab.type = 'button';
  fab.id = 'vpShareTrigger';
  fab.className = 'vp-share-fab';
  fab.setAttribute('aria-label', 'Share this page');
  fab.setAttribute('aria-controls', 'vpShareMenu');
  fab.setAttribute('aria-expanded', 'false');
  fab.innerHTML = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 15V3m0 0L7.5 7.5M12 3l4.5 4.5M5 12.5v5.8A2.7 2.7 0 0 0 7.7 21h8.6a2.7 2.7 0 0 0 2.7-2.7v-5.8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg><span>Share</span>';

  var menu = document.createElement('section');
  menu.id = 'vpShareMenu';
  menu.className = 'vp-share-menu';
  menu.setAttribute('role', 'dialog');
  menu.setAttribute('aria-modal', 'false');
  menu.setAttribute('aria-labelledby', 'vpShareHeading');
  menu.hidden = true;
  menu.innerHTML = '<div class="vp-share-menu-head"><div><strong id="vpShareHeading">Share this page</strong><small>Pass the music along.</small></div><button class="vp-share-close" type="button" aria-label="Close share options">×</button></div><div class="vp-share-menu-actions"><button type="button" data-vp-native-share>↗ Share with device</button><button class="vp-share-copy" type="button" data-vp-copy-link>▢ Copy page link</button><a data-vp-destination="whatsapp" target="_blank" rel="noopener noreferrer">◉ WhatsApp</a><a data-vp-destination="facebook" target="_blank" rel="noopener noreferrer">f Facebook</a><a data-vp-destination="telegram" target="_blank" rel="noopener noreferrer">➤ Telegram</a><a data-vp-destination="email">✉ Email</a></div><p class="vp-share-status" id="vpShareStatus" role="status" aria-live="polite"></p>';

  document.body.appendChild(menu);
  document.body.appendChild(fab);

  var status = document.getElementById('vpShareStatus');
  var nativeButton = menu.querySelector('[data-vp-native-share]');
  var copyButton = menu.querySelector('[data-vp-copy-link]');
  var closeButton = menu.querySelector('.vp-share-close');

  if (typeof navigator.share !== 'function') nativeButton.hidden = true;

  /*
   * Keep only the Share control clear of each page's existing fixed music UI.
   * Player positions differ between the homepage and individual cover pages, so
   * measure their real rendered rectangles instead of guessing a single offset.
   */
  var playerSelector = '.music-bar, .floating-player, .floating-music-bar, .hark-player-dock, .youtube-music-dock, #floating-music-bar, #floatingPlayer, #harkPlayerDock';
  var playerMutationObserver = null;
  var playerResizeObserver = null;

  function positionShareButton() {
    if (!fab.isConnected) return;

    /* Temporarily use the responsive CSS baseline to measure collision from. */
    fab.style.removeProperty('bottom');
    var computedBase = parseFloat(window.getComputedStyle(fab).bottom);
    var baseBottom = Number.isFinite(computedBase)
      ? computedBase
      : (window.matchMedia('(max-width: 680px)').matches ? 88 : 98);
    var fabRect = fab.getBoundingClientRect();
    var mobile = window.matchMedia('(max-width: 680px)').matches;
    var clearance = 12;
    var finalBottom = baseBottom;

    document.querySelectorAll(playerSelector).forEach(function (player) {
      if (player === fab || player === menu || !player.isConnected) return;
      var style = window.getComputedStyle(player);
      if (style.position !== 'fixed' || style.display === 'none' ||
          style.visibility === 'hidden' || player.hidden) return;

      var rect = player.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;

      /* Keep the minimized music-note button on its own row on phone screens. */
      var isMinimizedMusicNote = mobile &&
        player.matches('.youtube-music-dock.is-minimized');

      var nearHorizontally =
        fabRect.left < rect.right + clearance &&
        fabRect.right > rect.left - clearance;
      var nearVertically =
        fabRect.bottom >= rect.top - clearance &&
        fabRect.top <= rect.bottom + clearance;

      if (isMinimizedMusicNote || (nearHorizontally && nearVertically)) {
        finalBottom = Math.max(
          finalBottom,
          window.innerHeight - rect.top + clearance
        );
      }
    });

    finalBottom = Math.ceil(finalBottom);
    fab.style.bottom = finalBottom + 'px';

    /* Keep the open menu attached to the Share control and inside the viewport. */
    var fabHeight = fab.getBoundingClientRect().height;
    var menuBottom = Math.ceil(finalBottom + fabHeight + 10);
    menu.style.bottom = menuBottom + 'px';
    menu.style.maxHeight = Math.max(
      120,
      Math.min(430, window.innerHeight - menuBottom - 12)
    ) + 'px';
  }

  function observeMusicPlayers() {
    var players = document.querySelectorAll(playerSelector);
    players.forEach(function (player) {
      if (playerMutationObserver) {
        try {
          playerMutationObserver.observe(player, {
            attributes: true,
            attributeFilter: ['class', 'style', 'hidden']
          });
        } catch (error) {}
      }
      if (playerResizeObserver) {
        try { playerResizeObserver.observe(player); } catch (error) {}
      }
    });
  }

  if (typeof MutationObserver === 'function') {
    playerMutationObserver = new MutationObserver(function () {
      positionShareButton();
      observeMusicPlayers();
    });
  }
  if (typeof ResizeObserver === 'function') {
    playerResizeObserver = new ResizeObserver(positionShareButton);
  }

  function getShareData() {
    var canonical = document.querySelector('link[rel="canonical"]');
    var ogTitle = document.querySelector('meta[property="og:title"]');
    var title = (ogTitle && ogTitle.content) || document.title || 'Violin Prince';
    var url = (canonical && canonical.href) || window.location.href;
    return {
      title: title,
      text: 'Discover this violin cover and more music from Violin Prince.',
      url: url
    };
  }

  function refreshShareDestinations() {
    var data = getShareData();
    var encodedUrl = encodeURIComponent(data.url);
    var encodedTitle = encodeURIComponent(data.title);
    var destinations = {
      whatsapp: 'https://wa.me/?text=' + encodeURIComponent(data.title + ' — ' + data.url),
      facebook: 'https://www.facebook.com/sharer/sharer.php?u=' + encodedUrl,
      telegram: 'https://t.me/share/url?url=' + encodedUrl + '&text=' + encodedTitle,
      email: 'mailto:?subject=' + encodedTitle + '&body=' + encodeURIComponent(data.text + '\n\n' + data.url)
    };
    menu.querySelectorAll('[data-vp-destination]').forEach(function (link) {
      var key = link.getAttribute('data-vp-destination');
      link.href = destinations[key] || '#';
    });
  }

  function setOpen(open) {
    menu.hidden = !open;
    fab.setAttribute('aria-expanded', String(open));
    if (open) {
      refreshShareDestinations();
      if (status) status.textContent = '';
    }
  }

  function openMenu() { setOpen(true); }
  function toggleMenu() { setOpen(menu.hidden); }
  function announce(message) { if (status) status.textContent = message; }

  async function copyPageLink() {
    var data = getShareData();
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(data.url);
      } else {
        throw new Error('Clipboard API unavailable');
      }
      announce('Link copied. Send it to someone who loves music.');
    } catch (error) {
      var field = document.createElement('textarea');
      field.value = data.url;
      field.setAttribute('readonly', '');
      field.style.position = 'fixed';
      field.style.left = '-9999px';
      field.style.top = '0';
      document.body.appendChild(field);
      field.select();
      var copied = false;
      try { copied = document.execCommand('copy'); } catch (copyError) { copied = false; }
      field.remove();
      announce(copied ? 'Link copied. Send it to someone who loves music.' : 'Copy the page address from your browser bar to share.');
    }
  }

  fab.addEventListener('click', toggleMenu);
  closeButton.addEventListener('click', function () { setOpen(false); fab.focus(); });
  copyButton.addEventListener('click', copyPageLink);
  nativeButton.addEventListener('click', async function () {
    var data = getShareData();
    if (typeof navigator.share !== 'function') {
      await copyPageLink();
      return;
    }
    try {
      await navigator.share(data);
      announce('Thanks for sharing Violin Prince.');
      setTimeout(function () { announce(''); }, 1800);
    } catch (error) {
      if (error && error.name !== 'AbortError') announce('Sharing was not available here. Try Copy page link instead.');
    }
  });

  document.querySelectorAll('[data-vp-open-share]').forEach(function (button) {
    button.addEventListener('click', openMenu);
  });

  document.addEventListener('click', function (event) {
    var openShareTrigger = event.target && event.target.closest ? event.target.closest('[data-vp-open-share]') : null;
    if (!menu.hidden && !menu.contains(event.target) && event.target !== fab && !fab.contains(event.target) && !openShareTrigger) {
      setOpen(false);
    }
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !menu.hidden) {
      setOpen(false);
      fab.focus();
    }
  });

  observeMusicPlayers();
  positionShareButton();
  window.addEventListener('resize', positionShareButton, { passive: true });
  window.addEventListener('orientationchange', positionShareButton, { passive: true });
})();