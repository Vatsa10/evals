(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const icon = (name, classes = '') => `<svg class="icon ${classes}" aria-hidden="true"><use href="./assets/icons.svg#${name}"></use></svg>`;
  const escapeHTML = (text) => text.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let storedMotion = 'on';
  try { storedMotion = localStorage.getItem('evals-motion') || 'on'; } catch { /* Storage is optional. */ }
  const motionAllowed = () => !reducedMotion.matches && storedMotion !== 'off';

  const motionButton = $('#motion-toggle');
  function syncMotion() {
    const off = !motionAllowed();
    document.documentElement.dataset.motion = off ? 'off' : 'on';
    motionButton.setAttribute('aria-pressed', String(off));
    motionButton.disabled = reducedMotion.matches;
    motionButton.innerHTML = icon(off ? 'play' : 'pause') + `<span>${reducedMotion.matches ? 'Reduced motion' : off ? 'Enable motion' : 'Pause motion'}</span>`;
    if (off) $('#evaluation-demo').style.transform = '';
  }
  syncMotion();
  reducedMotion.addEventListener('change', syncMotion);
  motionButton.addEventListener('click', () => {
    storedMotion = storedMotion === 'off' ? 'on' : 'off';
    try { localStorage.setItem('evals-motion', storedMotion); } catch { /* The control still works without storage. */ }
    syncMotion();
  });
  document.addEventListener('visibilitychange', () => {
    document.documentElement.dataset.pageActive = String(!document.hidden);
  });

  // Content is visible without JavaScript. Only observed elements opt into reveals.
  if ('IntersectionObserver' in window) {
    const reveals = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          reveals.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -24px 0px' });
    $$('.reveal').forEach(element => { element.classList.add('will-reveal'); reveals.observe(element); });
    const visibility = new IntersectionObserver(entries => entries.forEach(entry => {
      entry.target.classList.toggle('is-offscreen', !entry.isIntersecting);
    }));
    visibility.observe($('.hero-visual'));
    visibility.observe($('.workflow-stage'));
  }

  const mobileMenu = $('#mobile-nav');
  const menuButton = $('.menu-toggle');
  function closeMenu() {
    mobileMenu.hidden = true;
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.setAttribute('aria-label', 'Open navigation');
    menuButton.innerHTML = icon('list');
  }
  menuButton.addEventListener('click', () => {
    const open = menuButton.getAttribute('aria-expanded') !== 'true';
    mobileMenu.hidden = !open;
    menuButton.setAttribute('aria-expanded', String(open));
    menuButton.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
    menuButton.innerHTML = icon(open ? 'x' : 'list');
  });
  $$('a', mobileMenu).forEach(link => link.addEventListener('click', closeMenu));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !mobileMenu.hidden) { closeMenu(); menuButton.focus(); }
  });
  document.addEventListener('pointerdown', event => {
    if (!mobileMenu.hidden && !$('.site-header').contains(event.target)) closeMenu();
  });
  const mobileViewport = window.matchMedia('(max-width: 720px)');
  function syncNavigationLayout() {
    closeMenu();
    $('.guide-tabs').setAttribute('aria-orientation', mobileViewport.matches ? 'horizontal' : 'vertical');
  }
  mobileViewport.addEventListener('change', syncNavigationLayout);
  syncNavigationLayout();

  // Tilt only responds to fine pointers. The readable run stays almost frontal.
  const visual = $('.hero-visual');
  const evaluationWindow = $('#evaluation-demo');
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  let tiltFrame;
  visual.addEventListener('pointermove', event => {
    if (!motionAllowed() || !finePointer.matches) return;
    cancelAnimationFrame(tiltFrame);
    tiltFrame = requestAnimationFrame(() => {
      const bounds = visual.getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width - 0.5;
      const y = (event.clientY - bounds.top) / bounds.height - 0.5;
      evaluationWindow.style.transform = `rotateX(${-y * 3}deg) rotateY(${x * 4}deg)`;
    });
  });
  visual.addEventListener('pointerleave', () => { cancelAnimationFrame(tiltFrame); evaluationWindow.style.transform = ''; });

  const demoButtons = $$('[data-demo-version]');
  let demoVersion = 'after';
  let demoGeneration = 0;
  const caseRows = $$('.case-row');
  function setCase(row, state) {
    row.dataset.state = state;
    $('.case-status', row).textContent = ({ passed: 'Passed', failed: 'Failed', queued: 'Queued', running: 'Running' })[state];
    $('.case-icon', row).innerHTML = icon(state === 'failed' ? 'x' : state === 'running' ? 'circle-notch' : state === 'queued' ? 'minus' : 'check');
  }
  function renderDemo() {
    demoGeneration++;
    caseRows.forEach((row, index) => setCase(row, index === 1 && demoVersion === 'before' ? 'failed' : 'passed'));
    $('#demo-score').innerHTML = `${demoVersion === 'before' ? 2 : 3}<span>/ 3</span>`;
    $('#demo-caption').textContent = 'cases passed';
    $('#run-state').innerHTML = '<span class="status-light"></span>Run complete';
    $('#replay-demo').disabled = false;
    demoButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.demoVersion === demoVersion)));
  }
  demoButtons.forEach(button => button.addEventListener('click', () => { demoVersion = button.dataset.demoVersion; renderDemo(); }));
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  $('#replay-demo').addEventListener('click', async () => {
    if (!motionAllowed()) { renderDemo(); return; }
    const generation = ++demoGeneration;
    $('#replay-demo').disabled = true;
    $('#demo-score').innerHTML = '0<span>/ 3</span>';
    $('#run-state').innerHTML = '<span class="status-light"></span>Evaluating';
    caseRows.forEach(row => setCase(row, 'queued'));
    let passed = 0;
    for (let index = 0; index < caseRows.length; index++) {
      if (generation !== demoGeneration) return;
      setCase(caseRows[index], 'running');
      await wait(430);
      if (generation !== demoGeneration) return;
      const failed = index === 1 && demoVersion === 'before';
      setCase(caseRows[index], failed ? 'failed' : 'passed');
      if (!failed) passed++;
      $('#demo-score').innerHTML = `${passed}<span>/ 3</span>`;
      await wait(120);
    }
    if (generation === demoGeneration) {
      $('#run-state').innerHTML = '<span class="status-light"></span>Run complete';
      $('#replay-demo').disabled = false;
    }
  });

  const wayData = {
    agent: {
      filename: 'your-terminal', label: 'Get the plugin', guide: 'codex',
      html: `<div class="agent-command"><span class="prompt-symbol">›</span><p>Use <span class="inline-skill">$evals</span> to add meaningful<br>evaluations to this application.</p></div><div class="agent-response"><span class="mini-brand" aria-hidden="true">e.</span><div><p>Let’s make the behavior measurable.</p><ul><li>${icon('check')}Inspect your application</li><li>${icon('check')}Create a suite and adapter</li><li>${icon('check')}Run, inspect, and verify</li></ul></div></div>`
    },
    setup: {
      filename: 'your-application / evaluations', label: 'Set up your feedback loop', guide: 'monitoring',
      html: `<div class="setup-preview-steps"><div>${icon('plugs-connected')}Connect the real application</div><div>${icon('tree-structure')}Capture tools, traces, and conversations</div><div>${icon('pulse')}Run checks. Keep a local history.</div></div><div class="setup-preview-summary"><span>SUITES + TRACES + ONLINE GRADERS</span><strong>One feedback loop</strong></div><p class="way-inline-note">Your coding agent writes the integration.<br>The engine keeps your checks repeatable.</p>`
    },
    sdk: {
      filename: 'your-app.py', label: 'Explore the Python SDK', guide: 'python',
      html: `<pre class="way-code"><span class="syntax-dim">from</span> evals <span class="syntax-dim">import</span> trace, observe\n\n<span class="syntax-dim">@observe</span>(kind=<span>"tool"</span>)\n<span class="syntax-dim">def</span> lookup_order(order_id):\n    <span class="syntax-dim">return</span> orders.get(order_id)\n\n<span class="syntax-dim">with</span> trace(<span>"support"</span>) <span class="syntax-dim">as</span> request:\n    answer = agent.reply(message)\n    request.update(output=answer)</pre>`
    }
  };

  function animateChange(element, pointerInitiated) {
    if (!motionAllowed() || !pointerInitiated) return;
    element.getAnimations().forEach(animation => animation.cancel());
    element.animate([{ opacity: 0, transform: 'translateY(5px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 240, easing: 'cubic-bezier(.22,1,.36,1)' });
  }
  function selectWay(name, pointerInitiated = false) {
    const data = wayData[name];
    if (!data) return;
    $$('[data-way]').forEach(button => {
      const selected = button.dataset.way === name;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    $('#way-panel').setAttribute('aria-labelledby', `way-${name}`);
    $('#way-filename').textContent = data.filename;
    $('#way-content').innerHTML = data.html;
    $('#way-link').innerHTML = `<span>${data.label}</span>${icon('arrow-right')}`;
    $('#way-link').dataset.selectGuide = data.guide;
    animateChange($('#way-content'), pointerInitiated);
  }
  $$('[data-way]').forEach(button => button.addEventListener('click', event => selectWay(button.dataset.way, event.detail > 0)));

  const guides = {
    codex: {
      kicker: 'THE CODING-AGENT ROUTE', title: 'Meet your new evaluation skill.', badge: 'CODEX',
      steps: [
        ['Install from the marketplace', 'Run these in your terminal with Codex CLI installed.', 'codex plugin marketplace add Vatsa10/evals\ncodex plugin add evals@evals'],
        ['Start a fresh session in your app', 'Restart Codex so it can discover the installed Evals skill.', 'codex'],
        ['Give it a real task', 'Your agent writes the adapter, creates the suite, and runs it.', 'Use $evals to inspect this application, add meaningful\nevaluations, run them, and explain the failures.']
      ],
      note: 'Verified in live Codex sessions.', link: 'https://github.com/Vatsa10/evals/blob/main/docs/live-verification.md', linkText: 'See the evidence ↗'
    },
    claude: {
      kicker: 'THE CODING-AGENT ROUTE', title: 'Your agent. Now with evaluations.', badge: 'CLAUDE CODE',
      steps: [
        ['Add the Evals plugin', 'Enter these commands inside Claude Code.', '/plugin marketplace add Vatsa10/evals\n/plugin install evals@evals'],
        ['Start a new session', 'Open Claude Code in the application you want to evaluate.', 'claude'],
        ['Ask for meaningful checks', 'Invoke the installed skill and describe your expected behavior.', '/evals:evals Inspect this app, create evaluations for its\nreal behavior, run them, and explain any failures.']
      ],
      note: 'Uses the bundled engine. Python 3.11+ required.', link: 'https://github.com/Vatsa10/evals#1-use-with-claude-code-or-codex', linkText: 'Plugin setup ↗'
    },
    python: {
      kicker: 'THE MANUAL ROUTE', title: 'Your code. Your definition of good.', badge: 'PYTHON SDK',
      steps: [
        ['Install the framework', 'Install into your project’s Python 3.11+ environment.', 'python -m pip install "git+https://github.com/Vatsa10/evals.git"'],
        ['Create and run your first suite', 'This creates demo fixtures. Replace the adapter and cases with your app.', 'evals init evaluations\nevals validate evaluations/suite.json\nevals run evaluations/suite.json --trials 3 --output .evals/baseline.json'],
        ['Inspect the evidence', 'Read the saved report or browse your local run history.', 'evals report .evals/baseline.json\nevals history --kind runs']
      ],
      note: 'Bring your own application, providers, and custom graders.', link: 'https://github.com/Vatsa10/evals/blob/main/skills/evals/references/framework.md', linkText: 'Read the contracts ↗'
    },
    monitoring: {
      kicker: 'THE CONTINUOUS FEEDBACK LOOP', title: 'Keep an eye on every iteration.', badge: 'MONITORING',
      steps: [
        ['Connect your app first', 'Ask your coding agent to create a real suite and online grading policy.', 'Use Evals to connect this app, create a live evaluation\nsuite and online policy, and verify a complete request.'],
        ['Save a baseline and keep checking', 'The monitor runs in the foreground until stopped.', 'evals run evaluations/suite.json --output .evals/baseline.json\nevals monitor evaluations/suite.json --interval 60 --baseline .evals/baseline.json'],
        ['Inspect your local monitoring data', 'Use the JSON API for trace ingestion and run history.', 'evals history --kind alerts\nevals serve --policy evaluations/online-policy.json --port 8765']
      ],
      note: 'Local SQLite history and JSON API. No hosted dashboard.', link: 'https://github.com/Vatsa10/evals/blob/main/skills/evals/references/monitoring.md', linkText: 'Monitoring guide ↗'
    }
  };

  function selectGuide(name, pointerInitiated = false) {
    const guide = guides[name];
    if (!guide) return;
    $$('[data-guide]').forEach(button => {
      const selected = button.dataset.guide === name;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    $('#guide-panel').setAttribute('aria-labelledby', `tab-${name}`);
    $('.guide-kicker').textContent = guide.kicker;
    $('.guide-title-row h3').textContent = guide.title;
    $('.guide-badge').textContent = guide.badge;
    $('#guide-steps').innerHTML = guide.steps.map(([title, description, command], index) => `<article class="guide-step"><div class="guide-step-heading"><span class="guide-step-number">${index + 1}</span><h4>${title}</h4></div><p>${description}</p><div class="code-block ${index === 2 && ['codex', 'claude'].includes(name) ? 'prompt-block' : ''}"><pre><code>${escapeHTML(command)}</code></pre><button class="copy-button icon-button" type="button" aria-label="Copy ${escapeHTML(title.toLowerCase())}">${icon('copy')}</button></div></article>`).join('');
    $('#guide-footnote').innerHTML = `${icon('check-circle')}<span>${guide.note} <a href="${guide.link}" target="_blank" rel="noopener noreferrer">${guide.linkText}</a></span>`;
    animateChange($('#guide-steps'), pointerInitiated);
  }
  $$('[data-guide]').forEach(button => button.addEventListener('click', event => selectGuide(button.dataset.guide, event.detail > 0)));
  document.addEventListener('click', event => {
    const link = event.target.closest('[data-select-guide]');
    if (link) selectGuide(link.dataset.selectGuide, event.detail > 0);
  });

  // Both tab groups support arrows, Home, and End with a single tab stop.
  $$('.way-tabs, .guide-tabs').forEach(group => {
    group.addEventListener('keydown', event => {
      const tabs = $$('[role="tab"]', group);
      const current = tabs.indexOf(document.activeElement);
      if (current < 0) return;
      let next;
      if (['ArrowDown', 'ArrowRight'].includes(event.key)) next = (current + 1) % tabs.length;
      if (['ArrowUp', 'ArrowLeft'].includes(event.key)) next = (current - 1 + tabs.length) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next === undefined) return;
      event.preventDefault();
      tabs[next].focus();
      tabs[next].click();
    });
  });

  let toastTimeout;
  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    const field = document.createElement('textarea');
    field.value = text;
    field.setAttribute('readonly', '');
    field.style.cssText = 'position:fixed;opacity:0;pointer-events:none;inset:0;width:1px;height:1px';
    document.body.append(field);
    field.select();
    const copied = document.execCommand('copy');
    field.remove();
    if (!copied) throw new Error('Clipboard unavailable');
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest('.copy-button');
    if (!button) return;
    const command = $('code', button.closest('.code-block')).textContent;
    try {
      await copyText(command);
      button.innerHTML = icon('check');
      button.classList.add('is-copied');
      $('#toast span').textContent = 'Copied to clipboard';
      clearTimeout(toastTimeout);
      $('#toast').classList.add('is-visible');
      toastTimeout = setTimeout(() => $('#toast').classList.remove('is-visible'), 2200);
      setTimeout(() => { button.innerHTML = icon('copy'); button.classList.remove('is-copied'); }, 1800);
      button.focus({ preventScroll: true });
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents($('code', button.closest('.code-block')));
      selection.removeAllRanges(); selection.addRange(range);
      $('#toast span').textContent = 'Select and copy the highlighted command';
      $('#toast').classList.add('is-visible');
      clearTimeout(toastTimeout);
      toastTimeout = setTimeout(() => $('#toast').classList.remove('is-visible'), 3500);
    }
  });
})();
