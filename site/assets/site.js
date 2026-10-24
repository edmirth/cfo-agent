// «Slik fungerer det»: the five stories take turns, as in the design. Each one
// shows for SECONDS with a bar filling above it; a click jumps to that story.
// It pauses while the pointer or keyboard focus is on the list, and does not
// move at all for visitors who have asked for reduced motion.
(() => {
  const SECONDS = 7;
  const ACTIVE = '#0F0E0D';
  const IDLE = '#ADABA5';

  const list = document.querySelector('[data-story]');
  if (!list) return;
  const stories = [...list.querySelectorAll('[data-story-i]')];
  const panels = [...document.querySelectorAll('[data-panel]')];
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let active = 0;
  let t = 0;
  let paused = false;

  function show() {
    stories.forEach((b, i) => {
      const on = i === active;
      b.setAttribute('aria-pressed', String(on));
      b.querySelector('.story-num').style.color = on ? ACTIVE : IDLE;
      b.querySelector('.story-title').style.color = on ? ACTIVE : IDLE;
      // The design gives the description an inline display:block, which
      // outranks the hidden attribute, so it is switched here instead.
      b.querySelector('.story-desc').style.display = on ? 'block' : 'none';
    });
    panels.forEach((p, i) => { p.hidden = i !== active; });
  }

  function bars() {
    stories.forEach((b, i) => {
      const width = i !== active ? 0 : still ? 1 : t;
      b.querySelector('.story-bar').style.width = (width * 100).toFixed(1) + '%';
    });
  }

  stories.forEach((b, i) => b.addEventListener('click', () => {
    active = i;
    t = 0;
    show();
    bars();
  }));
  list.addEventListener('pointerenter', () => { paused = true; });
  list.addEventListener('pointerleave', () => { paused = false; });
  list.addEventListener('focusin', () => { paused = true; });
  list.addEventListener('focusout', () => { paused = false; });

  show();
  bars();
  if (still) return;
  setInterval(() => {
    if (paused || document.hidden) return;
    t += 0.1 / SECONDS;
    if (t >= 1) {
      active = (active + 1) % stories.length;
      t = 0;
      show();
    }
    bars();
  }, 100);
})();
