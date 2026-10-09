(() => {
  // A single, full-width editorial hero that rotates between featured stories.
  document.querySelectorAll('[data-hero-carousel]').forEach((carousel) => {
    const slides = [...carousel.querySelectorAll('[data-hero-slide]')];
    const count = carousel.querySelector('.hero-count');
    const dots = [...carousel.querySelectorAll('[data-hero-go]')];
    const pause = carousel.querySelector('[data-hero-pause]');
    const previous = carousel.querySelector('[data-hero-prev]');
    const next = carousel.querySelector('[data-hero-next]');
    const viewport = carousel.querySelector('.hero-slides');
    if (slides.length < 2) return;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let current = 0;
    let timer;
    let active = false;
    let paused = reducedMotion.matches;
    let hovered = false;
    let focused = false;
    let pointerStart;
    let suppressClick = false;
    const clear = () => { window.clearTimeout(timer); timer = undefined; };
    const show = (index) => {
      current = (index + slides.length) % slides.length;
      slides.forEach((slide, i) => {
        const selected = i === current;
        slide.classList.toggle('is-active', selected);
        slide.setAttribute('aria-hidden', String(!selected));
        slide.inert = !selected;
        dots[i]?.toggleAttribute('aria-current', selected);
      });
      if (count) count.textContent = `${String(current + 1).padStart(2, '0')} / ${String(slides.length).padStart(2, '0')}`;
    };
    const schedule = () => {
      clear();
      if (!active || paused || hovered || focused || document.hidden) return;
      timer = window.setTimeout(() => { show(current + 1); schedule(); }, 6500);
    };
    previous?.addEventListener('click', () => { show(current - 1); schedule(); });
    next?.addEventListener('click', () => { show(current + 1); schedule(); });
    dots.forEach((dot) => dot.addEventListener('click', () => { show(Number(dot.dataset.heroGo)); schedule(); }));
    // Let touch users swipe and desktop users drag the editorial banner.
    viewport?.addEventListener('pointerdown', (event) => {
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      pointerStart = { id: event.pointerId, x: event.clientX, y: event.clientY, dragged: false };
      try { viewport.setPointerCapture(event.pointerId); } catch (_) { /* Synthetic and older pointer events may not support capture. */ }
    });
    viewport?.addEventListener('pointermove', (event) => {
      if (!pointerStart || pointerStart.id !== event.pointerId) return;
      const dx = event.clientX - pointerStart.x;
      const dy = event.clientY - pointerStart.y;
      if (Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy) * 1.15) pointerStart.dragged = true;
      viewport.classList.toggle('is-dragging', pointerStart.dragged);
    });
    const endPointer = (event) => {
      if (!pointerStart || pointerStart.id !== event.pointerId) return;
      const gesture = pointerStart;
      pointerStart = undefined;
      viewport?.classList.remove('is-dragging');
      const dx = event.clientX - gesture.x;
      const dy = event.clientY - gesture.y;
      if (!gesture.dragged || Math.abs(dx) < 48 || Math.abs(dx) <= Math.abs(dy) * 1.15) return;
      suppressClick = true;
      show(current + (dx < 0 ? 1 : -1));
      schedule();
      window.setTimeout(() => { suppressClick = false; }, 0);
    };
    viewport?.addEventListener('pointerup', endPointer);
    viewport?.addEventListener('pointercancel', (event) => {
      if (pointerStart?.id === event.pointerId) pointerStart = undefined;
      viewport.classList.remove('is-dragging');
    });
    viewport?.addEventListener('click', (event) => {
      if (!suppressClick) return;
      event.preventDefault();
      event.stopPropagation();
      suppressClick = false;
    }, true);
    if (viewport && !window.PointerEvent) {
      let mouseStart;
      carousel.addEventListener('mouseenter', () => { hovered = true; clear(); });
      carousel.addEventListener('mouseleave', () => { hovered = false; schedule(); });
      viewport.addEventListener('mousedown', (event) => {
        if (event.button !== 0) return;
        mouseStart = { x: event.clientX, y: event.clientY };
      });
      document.addEventListener('mousemove', (event) => {
        if (!mouseStart) return;
        const dx = event.clientX - mouseStart.x;
        const dy = event.clientY - mouseStart.y;
        viewport.classList.toggle('is-dragging', Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy) * 1.15);
      });
      document.addEventListener('mouseup', (event) => {
        if (!mouseStart) return;
        const dx = event.clientX - mouseStart.x;
        const dy = event.clientY - mouseStart.y;
        mouseStart = undefined;
        viewport.classList.remove('is-dragging');
        if (Math.abs(dx) < 48 || Math.abs(dx) <= Math.abs(dy) * 1.15) return;
        suppressClick = true;
        show(current + (dx < 0 ? 1 : -1));
        schedule();
        window.setTimeout(() => { suppressClick = false; }, 0);
      });
      let touchStart;
      viewport.addEventListener('touchstart', (event) => {
        const touch = event.changedTouches[0];
        if (touch) touchStart = { x: touch.clientX, y: touch.clientY };
      }, { passive: true });
      viewport.addEventListener('touchmove', (event) => {
        const touch = event.changedTouches[0];
        if (!touch || !touchStart) return;
        const dx = touch.clientX - touchStart.x;
        const dy = touch.clientY - touchStart.y;
        viewport.classList.toggle('is-dragging', Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy) * 1.15);
      }, { passive: true });
      viewport.addEventListener('touchend', (event) => {
        const touch = event.changedTouches[0];
        if (!touch || !touchStart) return;
        const dx = touch.clientX - touchStart.x;
        const dy = touch.clientY - touchStart.y;
        touchStart = undefined;
        viewport.classList.remove('is-dragging');
        if (Math.abs(dx) < 48 || Math.abs(dx) <= Math.abs(dy) * 1.15) return;
        suppressClick = true;
        show(current + (dx < 0 ? 1 : -1));
        schedule();
        window.setTimeout(() => { suppressClick = false; }, 700);
      }, { passive: true });
      viewport.addEventListener('touchcancel', () => {
        touchStart = undefined;
        viewport.classList.remove('is-dragging');
      }, { passive: true });
    }
    pause?.addEventListener('click', () => {
      paused = !paused;
      pause.textContent = paused ? 'Play' : 'Pause';
      pause.setAttribute('aria-label', `${paused ? 'Play' : 'Pause'} featured story rotation`);
      schedule();
    });
    carousel.addEventListener('pointerenter', () => { hovered = true; clear(); });
    carousel.addEventListener('pointerleave', () => { hovered = false; schedule(); });
    carousel.addEventListener('focusin', () => { focused = true; clear(); });
    carousel.addEventListener('focusout', (event) => { if (!carousel.contains(event.relatedTarget)) { focused = false; schedule(); } });
    document.addEventListener('visibilitychange', schedule);
    reducedMotion.addEventListener?.('change', (event) => {
      if (event.matches) { paused = true; if (pause) { pause.textContent = 'Play'; pause.setAttribute('aria-label', 'Play featured story rotation'); } }
      schedule();
    });
    show(0);
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(([entry]) => { active = entry.isIntersecting; schedule(); }, { threshold: 0.2 }).observe(carousel);
    } else { active = true; schedule(); }
  });

  // Story carousels are shared by the public site and publisher studio.
  document.querySelectorAll('[data-carousel]').forEach((carousel) => {
    const track = carousel.querySelector('.carousel-track');
    const cards = [...(track?.querySelectorAll('.card') || [])];
    const count = carousel.querySelector('.carousel-count');
    const pause = carousel.querySelector('[data-pause]');
    const previous = carousel.querySelector('[data-prev]');
    const next = carousel.querySelector('[data-next]');
    if (!track || cards.length < 2) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let timer;
    let active = false;
    let paused = reducedMotion.matches;
    let hovered = false;
    let focused = false;
    let index = 0;

    const stepSize = () => cards.length > 1 ? cards[1].offsetLeft - cards[0].offsetLeft : cards[0].offsetWidth;
    const update = () => {
      const step = stepSize() || cards[0].offsetWidth || 1;
      index = Math.max(0, Math.min(cards.length - 1, Math.round(track.scrollLeft / step)));
      if (count) count.textContent = `${String(index + 1).padStart(2, '0')} / ${String(cards.length).padStart(2, '0')}`;
    };
    const clear = () => { window.clearTimeout(timer); timer = undefined; };
    const schedule = () => {
      clear();
      if (!active || paused || hovered || focused || document.hidden) return;
      timer = window.setTimeout(() => {
        const target = index >= cards.length - 1 ? 0 : index + 1;
        track.scrollTo({ left: target * stepSize(), behavior: reducedMotion.matches ? 'auto' : 'smooth' });
        schedule();
      }, 5200);
    };
    const move = (direction) => {
      update();
      const target = (index + direction + cards.length) % cards.length;
      track.scrollTo({ left: target * stepSize(), behavior: reducedMotion.matches ? 'auto' : 'smooth' });
      schedule();
    };

    previous?.addEventListener('click', () => move(-1));
    next?.addEventListener('click', () => move(1));
    pause?.addEventListener('click', () => {
      paused = !paused;
      pause.textContent = paused ? 'Play' : 'Pause';
      pause.setAttribute('aria-label', `${paused ? 'Start' : 'Pause'} automatic story scrolling`);
      schedule();
    });
    track.addEventListener('scroll', () => { update(); schedule(); }, { passive: true });
    carousel.addEventListener('pointerenter', () => { hovered = true; clear(); });
    carousel.addEventListener('pointerleave', () => { hovered = false; schedule(); });
    carousel.addEventListener('focusin', () => { focused = true; clear(); });
    carousel.addEventListener('focusout', (event) => {
      if (!carousel.contains(event.relatedTarget)) { focused = false; schedule(); }
    });
    document.addEventListener('visibilitychange', schedule);
    reducedMotion.addEventListener?.('change', (event) => {
      if (event.matches) { paused = true; if (pause) { pause.textContent = 'Play'; pause.setAttribute('aria-label', 'Start automatic story scrolling'); } }
      schedule();
    });
    update();
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(([entry]) => { active = entry.isIntersecting; schedule(); }, { threshold: 0.2 }).observe(carousel);
    } else { active = true; schedule(); }
  });

  const selectAll = document.querySelector('[data-select-all]');
  const bulkForm = document.getElementById('bulk-ids')?.form;
  if (selectAll) {
    selectAll.addEventListener('change', () => {
      document.querySelectorAll('.story-select').forEach((item) => { item.checked = selectAll.checked; });
    });
  }
  if (bulkForm) {
    bulkForm.addEventListener('submit', (event) => {
      const selected = [...document.querySelectorAll('.story-select:checked')].map((item) => item.value);
      const hidden = document.getElementById('bulk-ids');
      const action = document.getElementById('bulk-action')?.value;
      if (!selected.length || !action) {
        event.preventDefault();
        window.alert('Select at least one story and choose an action.');
        return;
      }
      if (action === 'trash' && !window.confirm(`Move ${selected.length} stories to trash? They can be restored later.`)) {
        event.preventDefault();
        return;
      }
      hidden.value = selected.join(',');
    });
  }

  const textarea = document.getElementById('story-body');
  const preview = document.getElementById('story-preview');
  const toggle = document.getElementById('preview-toggle');
  if (!textarea || !preview || !toggle) return;

  const escapeHTML = (value) => value.replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);

  const render = (source) => {
    const blocks = [];
    let paragraph = [];
    let list = [];
    const flushParagraph = () => {
      if (paragraph.length) blocks.push(`<p>${paragraph.map(escapeHTML).join(' ')}</p>`);
      paragraph = [];
    };
    const flushList = () => {
      if (list.length) blocks.push(`<ul>${list.map((item) => `<li>${escapeHTML(item)}</li>`).join('')}</ul>`);
      list = [];
    };
    source.split(/\r?\n/).forEach((line) => {
      const text = line.trim();
      if (!text) { flushParagraph(); flushList(); return; }
      if (text.startsWith('- ')) { flushParagraph(); list.push(text.slice(2)); return; }
      flushParagraph(); flushList();
      if (text.startsWith('## ')) blocks.push(`<h3>${escapeHTML(text.slice(3))}</h3>`);
      else if (text.startsWith('# ')) blocks.push(`<h2>${escapeHTML(text.slice(2))}</h2>`);
      else if (text.startsWith('> ')) blocks.push(`<blockquote>${escapeHTML(text.slice(2))}</blockquote>`);
      else paragraph.push(text);
    });
    flushParagraph(); flushList();
    return blocks.join('') || '<p class="empty-state">Your story preview will appear here.</p>';
  };

  document.querySelectorAll('[data-insert]').forEach((button) => {
    button.addEventListener('click', () => {
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const marker = button.dataset.insert;
      const selected = textarea.value.slice(start, end) || 'Write here';
      textarea.setRangeText(`${marker}${selected}`, start, end, 'select');
      textarea.focus();
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });
  });

  toggle.addEventListener('click', () => {
    const opening = preview.hidden;
    preview.hidden = !opening;
    textarea.closest('label').hidden = opening;
    toggle.setAttribute('aria-expanded', String(opening));
    toggle.textContent = opening ? 'Edit story' : 'Preview';
    if (opening) preview.innerHTML = render(textarea.value);
    else textarea.focus();
  });
})();
