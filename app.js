(function() {
  'use strict';

  // ==================== CONFIG ====================
  // When served by server.py (or equivalent), use local /sanity and /proxy endpoints.
  // This works on localhost, wearableweb.manus.space, or any host running the server.
  // Falls back to allorigins for file:// context (e.g., raw Hypernova webview).
  var HAS_SERVER_PROXY = location.protocol !== 'file:';
  var PROXY_URL = HAS_SERVER_PROXY
    ? '/proxy?url='
    : 'https://api.allorigins.win/raw?url=';
  var AUDIO_URL_PATTERN = /https?:\/\/[^"'\s<>\\]+\.(mp3|m4a|wav|aac)(\?[^"'\s<>\\]*)?/gi;

  var MUSEUMS = {
    moma: {
      name: 'MoMA',
      fullName: 'Museum of Modern Art',
      color: '#ffffff',
      textColor: '#000000',
      baseOrigin: 'https://www.moma.org',
      logoSrc: 'logos/moma.svg',
      buildUrl: function(stop) {
        return 'https://www.moma.org/audio/playlist/1/' + stop;
      }
    },
    met: {
      name: 'The Met',
      fullName: 'The Metropolitan Museum of Art',
      color: '#e4002b',
      textColor: '#ffffff',
      baseOrigin: 'https://www.metmuseum.org',
      logoSrc: 'logos/met.svg',
      buildUrl: function(stop) {
        return 'https://www.metmuseum.org/audio-guide/' + stop;
      }
    },
    frick: {
      name: 'Frick',
      fullName: 'The Frick Collection',
      color: '#1a3a5c',
      textColor: '#d4af37',
      baseOrigin: 'https://www.frick.org',
      logoSrc: 'logos/frick.png',
      buildUrl: function(stop) {
        return 'https://collections.frick.org/search/' + stop;
      }
    }
  };

  // ==================== STATE ====================
  var state = {
    currentScreen: 'museum-select',
    screenHistory: [],
    selectedMuseum: null,
    stopNumber: '',
    currentUrl: null,
    isPlaying: false,
    audioLoaded: false
  };

  // ==================== DOM REFS ====================
  var screens = {};
  var audioEl = null;

  function collectScreens() {
    document.querySelectorAll('.screen').forEach(function(s) {
      if (s.id) screens[s.id] = s;
    });
    audioEl = document.getElementById('audio-element');
  }

  // ==================== NAVIGATION ====================
  function navigateTo(screenId, options) {
    options = options || {};
    var addToHistory = options.addToHistory !== false;

    if (addToHistory && state.currentScreen) {
      state.screenHistory.push(state.currentScreen);
    }

    Object.values(screens).forEach(function(s) { s.classList.add('hidden'); });
    if (screens[screenId]) {
      screens[screenId].classList.remove('hidden');
      state.currentScreen = screenId;
      onScreenEnter(screenId);
      focusFirst(screens[screenId]);
    }
  }

  function navigateBack() {
    if (state.currentScreen === 'audio-player') {
      // Clean up audio
      if (audioEl) {
        audioEl.pause();
        audioEl.removeAttribute('src');
        audioEl.load();
      }
      state.isPlaying = false;
      state.audioLoaded = false;
      // Clear iframe
      var iframe = document.getElementById('browser-iframe');
      if (iframe) { iframe.srcdoc = ''; iframe.classList.add('hidden'); }
      // Reset UI
      document.getElementById('player-loading').classList.remove('hidden');
      document.getElementById('player-error').classList.add('hidden');
      document.getElementById('player-ui').classList.add('hidden');
      updatePlayPauseButton();
      resetProgressBar();
    }

    if (state.screenHistory.length > 0) {
      navigateTo(state.screenHistory.pop(), { addToHistory: false });
    }
  }

  // ==================== FOCUS MANAGEMENT ====================
  function focusFirst(container) {
    var el = container.querySelector('.focusable:not([disabled]):not(.hidden)');
    if (el) el.focus();
  }

  function moveFocus(direction) {
    var container = screens[state.currentScreen];
    if (!container) return;

    var focusables = Array.from(
      container.querySelectorAll('.focusable:not([disabled]):not(.hidden)')
    );
    if (focusables.length === 0) return;

    var current = document.activeElement;
    var idx = focusables.indexOf(current);

    if (idx === -1) {
      focusFirst(container);
      return;
    }

    // Numpad 2D grid navigation
    if (state.currentScreen === 'stop-entry' && current.classList.contains('numpad-btn')) {
      var numpadBtns = Array.from(container.querySelectorAll('.numpad-btn'));
      var numIdx = numpadBtns.indexOf(current);
      var cols = 3;
      var nextIdx;

      switch (direction) {
        case 'up':
          nextIdx = numIdx - cols;
          if (nextIdx < 0) {
            var backBtn = container.querySelector('.back-btn');
            if (backBtn) backBtn.focus();
            return;
          }
          numpadBtns[nextIdx].focus();
          return;
        case 'down':
          nextIdx = numIdx + cols;
          if (nextIdx >= numpadBtns.length) return;
          numpadBtns[nextIdx].focus();
          return;
        case 'left':
          if (numIdx % cols === 0) return;
          numpadBtns[numIdx - 1].focus();
          return;
        case 'right':
          if (numIdx % cols === cols - 1) return;
          if (numIdx + 1 >= numpadBtns.length) return;
          numpadBtns[numIdx + 1].focus();
          return;
      }
    }

    // Default linear navigation
    var nextIdx;
    if (direction === 'up' || direction === 'left') {
      nextIdx = idx > 0 ? idx - 1 : focusables.length - 1;
    } else {
      nextIdx = idx < focusables.length - 1 ? idx + 1 : 0;
    }
    focusables[nextIdx].focus();
    focusables[nextIdx].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  // ==================== AUDIO EXTRACTION ====================

  function extractAudioUrls(html) {
    var urls = [];
    var matches = html.match(AUDIO_URL_PATTERN);
    if (matches) {
      matches.forEach(function(url) {
        var clean = url.replace(/\\u002F/g, '/').replace(/\\\//g, '/');
        if (urls.indexOf(clean) === -1) urls.push(clean);
      });
    }
    return urls;
  }

  function decodeHtmlEntities(str) {
    var el = document.createElement('textarea');
    el.innerHTML = str;
    return el.value;
  }

  function extractTitle(html) {
    var raw = null;
    // og:title
    var ogMatch = html.match(/<meta[^>]+property="og:title"[^>]+content="([^"]+)"/);
    if (ogMatch) raw = ogMatch[1];
    // <title>
    if (!raw) {
      var titleMatch = html.match(/<title[^>]*>([^<]+)<\/title>/i);
      if (titleMatch) raw = titleMatch[1];
    }
    // RSC data title
    if (!raw) {
      var rscMatch = html.match(/"title"\s*:\s*"(\d{3,}[^"]+)"/);
      if (rscMatch) raw = rscMatch[1];
    }
    return raw ? decodeHtmlEntities(raw) : null;
  }

  // ==================== AUDIO PLAYER ====================

  function formatTime(seconds) {
    if (!isFinite(seconds) || isNaN(seconds)) return '0:00';
    var mins = Math.floor(seconds / 60);
    var secs = Math.floor(seconds % 60);
    return mins + ':' + (secs < 10 ? '0' : '') + secs;
  }

  function updatePlayPauseButton() {
    var btn = document.getElementById('play-pause-btn');
    if (btn) btn.innerHTML = state.isPlaying ? '&#9646;&#9646;' : '&#9654;';
  }

  function resetProgressBar() {
    var bar = document.getElementById('progress-bar');
    if (bar) { bar.value = 0; bar.max = 100; }
    var cur = document.getElementById('time-current');
    var dur = document.getElementById('time-duration');
    if (cur) cur.textContent = '0:00';
    if (dur) dur.textContent = '0:00';
  }

  function setupAudioEvents() {
    if (!audioEl) return;

    audioEl.addEventListener('loadedmetadata', function() {
      document.getElementById('time-duration').textContent = formatTime(audioEl.duration);
      document.getElementById('progress-bar').max = audioEl.duration || 100;
    });

    audioEl.addEventListener('timeupdate', function() {
      if (!audioEl.duration) return;
      document.getElementById('time-current').textContent = formatTime(audioEl.currentTime);
      var bar = document.getElementById('progress-bar');
      if (bar && !bar.dataset.seeking) bar.value = audioEl.currentTime;
    });

    audioEl.addEventListener('canplay', function() {
      if (state.audioLoaded && !state.isPlaying) {
        audioEl.play().then(function() {
          state.isPlaying = true;
          updatePlayPauseButton();
        }).catch(function(e) {
          console.log('[AudioTour] Auto-play blocked:', e.message);
        });
      }
    });

    audioEl.addEventListener('ended', function() {
      state.isPlaying = false;
      updatePlayPauseButton();
    });

    audioEl.addEventListener('error', function(e) {
      console.error('[AudioTour] Audio error:', audioEl.error);
      showPlayerError('Audio playback failed. The file may be unavailable.');
    });

    var bar = document.getElementById('progress-bar');
    if (bar) {
      bar.addEventListener('input', function() {
        bar.dataset.seeking = 'true';
        document.getElementById('time-current').textContent = formatTime(parseFloat(bar.value));
      });
      bar.addEventListener('change', function() {
        audioEl.currentTime = parseFloat(bar.value);
        delete bar.dataset.seeking;
      });
    }
  }

  function togglePlayPause() {
    if (!audioEl || !state.audioLoaded) return;
    if (state.isPlaying) {
      audioEl.pause();
      state.isPlaying = false;
    } else {
      audioEl.play().catch(function() {});
      state.isPlaying = true;
    }
    updatePlayPauseButton();
  }

  // ==================== PLAYER UI STATES ====================

  function showPlayerLoading(text) {
    document.getElementById('player-loading').classList.remove('hidden');
    document.getElementById('player-error').classList.add('hidden');
    document.getElementById('player-ui').classList.add('hidden');
    document.getElementById('browser-iframe').classList.add('hidden');
    document.getElementById('loading-text').textContent = text;
  }

  function showNativePlayer(audioUrl, title, museumId) {
    document.getElementById('player-loading').classList.add('hidden');
    document.getElementById('player-error').classList.add('hidden');
    document.getElementById('player-ui').classList.remove('hidden');
    document.getElementById('browser-iframe').classList.add('hidden');

    var museum = MUSEUMS[museumId];
    var artwork = document.getElementById('player-artwork');
    artwork.innerHTML = '<img src="' + museum.logoSrc + '" alt="' + museum.name +
      '" style="width:100%;height:100%;object-fit:cover;border-radius:16px;">';

    document.getElementById('player-track-title').textContent =
      title || (museum.name + ' — Stop #' + state.stopNumber);

    state.audioLoaded = true;
    audioEl.src = audioUrl;
    audioEl.load();
    resetProgressBar();
    updatePlayPauseButton();

    var playBtn = document.getElementById('play-pause-btn');
    if (playBtn) playBtn.focus();
  }

  function showIframeFallback(html, baseOrigin) {
    document.getElementById('player-loading').classList.add('hidden');
    document.getElementById('player-error').classList.add('hidden');
    document.getElementById('player-ui').classList.add('hidden');

    var baseTag = '<base href="' + baseOrigin + '/">';
    if (html.indexOf('<head>') !== -1) {
      html = html.replace('<head>', '<head>' + baseTag);
    } else {
      html = '<head>' + baseTag + '</head>' + html;
    }

    var iframe = document.getElementById('browser-iframe');
    iframe.srcdoc = html;
    iframe.classList.remove('hidden');
  }

  function showPlayerError(message) {
    document.getElementById('player-loading').classList.add('hidden');
    document.getElementById('player-error').classList.remove('hidden');
    document.getElementById('player-ui').classList.add('hidden');
    document.getElementById('browser-iframe').classList.add('hidden');
    document.getElementById('error-message').textContent = message;
    if (state.currentUrl) {
      document.getElementById('error-url').textContent = state.currentUrl;
    }
    focusFirst(screens['audio-player']);
  }

  // ==================== MET SANITY API (FAST PATH) ====================
  var MET_SANITY_API = 'https://cctd4ker.apicdn.sanity.io/v2023-05-03/data/query/production';

  function fetchMetAudioDirect(stopNumber) {
    // On localhost, use local /sanity endpoint (server-side fetch, bypasses Cyberhaven).
    // Otherwise, try Sanity API via external proxy.
    var fetchUrl = HAS_SERVER_PROXY
      ? '/sanity?stop=' + encodeURIComponent(stopNumber)
      : PROXY_URL + encodeURIComponent(
          MET_SANITY_API + '?query=' + encodeURIComponent(
            '*[stopNumber=="' + stopNumber + '"][0]{title,"audioUrl":file.asset->url}'
          )
        );
    console.log('[AudioTour] Met Sanity via', HAS_SERVER_PROXY ? 'local server' : 'proxy');
    return fetch(fetchUrl)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.result && data.result.audioUrl) return data.result;
        return null;
      })
      .catch(function(e) {
        console.log('[AudioTour] Sanity fetch error:', e.message);
        return null;
      });
  }

  // ==================== MOMA PLAYWRIGHT (CLOUDFLARE BYPASS) ====================

  function fetchMomaAudio(stopNumber) {
    var fetchUrl = '/moma?stop=' + encodeURIComponent(stopNumber);
    console.log('[AudioTour] MoMA via Playwright server endpoint');
    return fetch(fetchUrl)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.result && data.result.audioUrl) return data.result;
        return null;
      })
      .catch(function(e) {
        console.log('[AudioTour] MoMA fetch error:', e.message);
        return null;
      });
  }

  // ==================== FRICK EMUSEUM ====================

  function fetchFrickAudio(stopNumber) {
    var fetchUrl = '/frick?stop=' + encodeURIComponent(stopNumber);
    console.log('[AudioTour] Frick via Playwright server endpoint');
    return fetch(fetchUrl)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.result && data.result.audioUrl) return data.result;
        return null;
      })
      .catch(function(e) {
        console.log('[AudioTour] Frick fetch error:', e.message);
        return null;
      });
  }

  // ==================== AUDIO CACHE (pre-fetched, instant lookup) ====================
  var AUDIO_CACHE = { met: null, moma: null, frick: null };

  function loadCache(museumId) {
    if (AUDIO_CACHE[museumId] !== null) return Promise.resolve(AUDIO_CACHE[museumId]);
    return fetch('cache/' + museumId + '.json')
      .then(function(r) {
        if (!r.ok) throw new Error('No cache');
        return r.json();
      })
      .then(function(data) {
        AUDIO_CACHE[museumId] = data;
        console.log('[AudioTour] Loaded cache for', museumId, ':', Object.keys(data).length, 'stops');
        return data;
      })
      .catch(function() {
        AUDIO_CACHE[museumId] = {};
        return {};
      });
  }

  function lookupCache(museumId, stopNumber) {
    var cache = AUDIO_CACHE[museumId];
    if (!cache) return null;
    return cache[stopNumber] || null;
  }

  // ==================== LOADING FLOW ====================

  function loadAudioForStop(museumId, stopNumber) {
    var museum = MUSEUMS[museumId];
    var pageUrl = museum.buildUrl(stopNumber);
    state.currentUrl = pageUrl;

    showPlayerLoading('Fetching audio for Stop #' + stopNumber + '...');

    // Step 1: Try cache first (instant)
    loadCache(museumId).then(function() {
      var cached = lookupCache(museumId, stopNumber);
      if (cached) {
        console.log('[AudioTour] Cache hit:', museumId, stopNumber);
        showNativePlayer(cached.url, cached.title, museumId);
        return;
      }

      console.log('[AudioTour] Cache miss:', museumId, stopNumber, '- trying live');

      // Step 2: Fall back to live server endpoints
      if (museumId === 'met' && HAS_SERVER_PROXY) {
        fetchMetAudioDirect(stopNumber).then(function(result) {
          if (result) {
            var title = result.title ? decodeHtmlEntities(result.title) : null;
            showNativePlayer(result.audioUrl, title, museumId);
          } else {
            showPlayerError('Could not find audio for The Met Stop #' + stopNumber);
          }
        });
        return;
      }

      if (museumId === 'moma' && HAS_SERVER_PROXY) {
        fetchMomaAudio(stopNumber).then(function(result) {
          if (result) {
            var title = result.title ? decodeHtmlEntities(result.title) : null;
            showNativePlayer(result.audioUrl, title, museumId);
          } else {
            showPlayerError('Could not find audio for MoMA Stop #' + stopNumber +
              '. The stop number may not exist.');
          }
        });
        return;
      }

      if (museumId === 'frick' && HAS_SERVER_PROXY) {
        fetchFrickAudio(stopNumber).then(function(result) {
          if (result) {
            var title = result.title ? decodeHtmlEntities(result.title) : null;
            showNativePlayer(result.audioUrl, title, museumId);
          } else {
            showPlayerError('Could not find audio for Frick Stop #' + stopNumber +
              '. The audio number may not exist.');
          }
        });
        return;
      }

      // Step 3: No server — show error with URL
      showPlayerError('Stop #' + stopNumber + ' not found in cache. ' +
        'Run build_cache.py to update.');
    });
  }

  function fetchViaProxy(museumId, stopNumber, pageUrl, museum) {
    var fetchUrl = PROXY_URL + encodeURIComponent(pageUrl);
    console.log('[AudioTour] Fetching:', fetchUrl);

    fetch(fetchUrl)
      .then(function(response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.text();
      })
      .then(function(html) {
        console.log('[AudioTour] Got HTML, length:', html.length);

        // Try to extract audio URLs
        var audioUrls = extractAudioUrls(html);
        var title = extractTitle(html);

        console.log('[AudioTour] Found audio URLs:', audioUrls);
        console.log('[AudioTour] Title:', title);

        if (audioUrls.length > 0) {
          // Got audio URL — show native player
          showNativePlayer(audioUrls[0], title, museumId);
        } else {
          // No audio URL found — try showing page in iframe
          console.log('[AudioTour] No audio URLs, falling back to iframe');
          showIframeFallback(html, museum.baseOrigin);
        }
      })
      .catch(function(err) {
        console.error('[AudioTour] Fetch failed:', err);
        showPlayerError('Could not load page: ' + err.message);
      });
  }

  // ==================== ACTIONS ====================
  function handleAction(action, element) {
    switch (action) {
      case 'back':
        navigateBack();
        break;
      case 'select-museum':
        var museumId = element.dataset.museum;
        if (MUSEUMS[museumId]) {
          state.selectedMuseum = museumId;
          state.stopNumber = '';
          navigateTo('stop-entry');
        }
        break;
      case 'num':
        if (state.stopNumber.length < 6) {
          state.stopNumber += element.dataset.digit;
          updateStopDisplay();
        }
        break;
      case 'num-clear':
        state.stopNumber = '';
        updateStopDisplay();
        break;
      case 'num-delete':
        if (state.stopNumber.length > 0) {
          state.stopNumber = state.stopNumber.slice(0, -1);
          updateStopDisplay();
        }
        break;
      case 'num-go':
        if (state.stopNumber.length > 0) {
          navigateTo('audio-player');
        } else {
          showToast('Enter a stop number first', 'error');
        }
        break;
      case 'play-pause':
        togglePlayPause();
        break;
      case 'copy-url':
        if (state.currentUrl) {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(state.currentUrl).then(function() {
              showToast('URL copied');
            }).catch(function() { showToast(state.currentUrl); });
          } else {
            showToast(state.currentUrl);
          }
        }
        break;
    }
  }

  function updateStopDisplay() {
    document.getElementById('stop-number-display').textContent = state.stopNumber || '---';
  }

  // ==================== SCREEN ENTER ====================
  function onScreenEnter(screenId) {
    if (screenId === 'stop-entry') {
      var museum = MUSEUMS[state.selectedMuseum];
      if (museum) document.getElementById('stop-entry-title').textContent = museum.name;
      updateStopDisplay();
    }
    if (screenId === 'audio-player') {
      var museum = MUSEUMS[state.selectedMuseum];
      document.getElementById('player-title').textContent = museum.name;
      document.getElementById('player-stop').textContent = 'Stop #' + state.stopNumber;
      loadAudioForStop(state.selectedMuseum, state.stopNumber);
    }
  }

  // ==================== TOAST ====================
  function showToast(message, type) {
    var toast = document.getElementById('toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'toast';
      toast.className = 'toast';
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.className = 'toast' + (type ? ' ' + type : '');
    toast.offsetHeight;
    toast.classList.add('visible');
    setTimeout(function() { toast.classList.remove('visible'); }, 2500);
  }

  // ==================== EVENT LISTENERS ====================
  function setupEvents() {
    document.addEventListener('click', function(e) {
      var actionEl = e.target.closest('[data-action]');
      if (actionEl) handleAction(actionEl.dataset.action, actionEl);
    });

    document.addEventListener('keydown', function(e) {
      if (state.currentScreen === 'audio-player' && e.key === 'Escape') {
        navigateBack(); e.preventDefault(); return;
      }

      // Progress bar: left/right seek
      if (document.activeElement && document.activeElement.id === 'progress-bar') {
        if (e.key === 'ArrowLeft') {
          audioEl.currentTime = Math.max(0, audioEl.currentTime - 5);
          e.preventDefault(); return;
        }
        if (e.key === 'ArrowRight') {
          audioEl.currentTime = Math.min(audioEl.duration || 0, audioEl.currentTime + 5);
          e.preventDefault(); return;
        }
      }

      switch (e.key) {
        case 'ArrowUp': moveFocus('up'); e.preventDefault(); break;
        case 'ArrowDown': moveFocus('down'); e.preventDefault(); break;
        case 'ArrowLeft': moveFocus('left'); e.preventDefault(); break;
        case 'ArrowRight': moveFocus('right'); e.preventDefault(); break;
        case 'Enter':
          if (document.activeElement && document.activeElement.classList.contains('focusable'))
            document.activeElement.click();
          e.preventDefault();
          break;
        case 'Escape': navigateBack(); e.preventDefault(); break;
        case '0': case '1': case '2': case '3': case '4':
        case '5': case '6': case '7': case '8': case '9':
          if (state.currentScreen === 'stop-entry' && state.stopNumber.length < 6) {
            state.stopNumber += e.key;
            updateStopDisplay();
            e.preventDefault();
          }
          break;
        case 'Backspace':
          if (state.currentScreen === 'stop-entry' && state.stopNumber.length > 0) {
            state.stopNumber = state.stopNumber.slice(0, -1);
            updateStopDisplay();
            e.preventDefault();
          }
          break;
      }
    });
  }

  // ==================== INIT ====================
  function init() {
    collectScreens();
    setupAudioEvents();
    setupEvents();
    navigateTo('museum-select', { addToHistory: false });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
