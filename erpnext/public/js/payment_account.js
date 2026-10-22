/* Drop-in payments account card. Interface: new PaymentsAccountPanel(root, {api, theme}). */
(() => {
  if (window.PaymentsAccountPanel) return;
  const sessions = new Set();
  let runtime;
  function loadRuntime() {
    if (window.StripeConnect?.init) return Promise.resolve(window.StripeConnect);
    if (!runtime) runtime = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://connect-js.stripe.com/v1.0/connect.js';
      script.async = true;
      script.onload = () => window.StripeConnect?.init ? resolve(window.StripeConnect) : reject(new Error('runtime'));
      script.onerror = () => { script.remove(); runtime = null; reject(new Error('runtime')); };
      document.head.append(script);
    });
    return runtime;
  }
  const css = `
  .payment-account{--pa-bg:var(--erp-glass-strong,var(--card-bg,#fff));--pa-fg:var(--erp-fg,var(--text-color,#171717));--pa-muted:var(--erp-fg-3,var(--text-muted,#666));--pa-line:var(--erp-line,var(--border-color,#e5e7eb));--pa-primary:var(--erp-thread-solid,var(--primary,#171717));font-family:var(--erp-sans,inherit);color:var(--pa-fg);max-width:1120px;margin:24px auto;padding:0 12px 32px}
  .payment-account *{box-sizing:border-box}.payment-account .pa-card{background:var(--pa-bg);border:1px solid var(--pa-line);border-radius:var(--erp-r-card,16px);padding:28px;margin-bottom:18px;box-shadow:var(--erp-card-shadow,0 1px 2px #00000005)}
  .payment-account .pa-top{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}.payment-account .pa-eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--pa-muted);margin:0 0 10px}.payment-account h2{font-size:26px;line-height:1.25;font-weight:600;margin:0 0 12px;letter-spacing:-.03em}.payment-account h3{font-size:17px;font-weight:600;margin:0 0 14px}.payment-account p{font-size:14px;line-height:1.65;margin:0 0 16px;max-width:650px;color:var(--pa-muted)}
  .payment-account .pa-badge{display:inline-block;border:1px solid var(--pa-line);border-radius:999px;padding:5px 10px;font-size:12px;white-space:nowrap}.payment-account .pa-ready{background:#edf8f0;color:#176636}.payment-account .pa-incomplete{background:#fff6df;color:#805f16}.payment-account .pa-not_connected{background:var(--erp-surface-sunk,#f5f5f5)}
  .payment-account .pa-checks{display:flex;gap:20px;flex-wrap:wrap;margin:22px 0;font-size:13px}.payment-account .pa-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.payment-account button{cursor:pointer;font:inherit;font-size:13px;font-weight:500;padding:10px 16px;border-radius:var(--erp-r-ctl,10px);border:1px solid var(--pa-line);background:var(--pa-bg);color:var(--pa-fg);min-height:40px}.payment-account button:focus-visible,.payment-account input:focus-visible{outline:2px solid var(--pa-primary);outline-offset:3px}.payment-account button:disabled{opacity:.55;cursor:wait}.payment-account .pa-primary-button{background:var(--pa-primary);border-color:var(--pa-primary);color:#fff}.payment-account .pa-test{margin-bottom:16px;padding:10px 14px;background:#fff6df;color:#805f16;border:1px solid #f0dfb0;border-radius:10px;font-size:13px}.payment-account .pa-error{border-left:3px solid #b42318;padding:12px 16px;margin-bottom:18px;background:var(--pa-bg);color:#9b1c1c;font-size:14px}.payment-account ul{padding-left:20px;margin:10px 0 20px;color:var(--pa-muted);font-size:14px;line-height:1.9}
  .payment-account .pa-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.payment-account .pa-grid .pa-card{padding:20px;min-width:0;margin:0}.payment-account .pa-components{margin-top:24px}.payment-account label{font-size:13px;display:block;margin:16px 0 7px}.payment-account input{font:inherit;border:1px solid var(--pa-line);border-radius:10px;padding:10px 12px;width:100%;max-width:260px;color:var(--pa-fg);background:var(--pa-bg)}.payment-account .pa-confirm{margin-top:20px;padding:18px;background:var(--erp-surface-sunk,#f6f6f6);border-radius:12px}.payment-account .pa-small{font-size:12px;margin-top:16px;margin-bottom:0}.payment-account [hidden]{display:none!important}
  @media(max-width:760px){.payment-account{margin:16px auto;padding:0 4px 24px}.payment-account .pa-card{padding:20px}.payment-account h2{font-size:23px}.payment-account .pa-grid{grid-template-columns:1fr}.payment-account .pa-actions button{flex:1}.payment-account .pa-checks{gap:10px;flex-direction:column}}
  `;
  class PaymentsAccountPanel {
    static async signOutAll() {
      await Promise.allSettled([...sessions].map(instance => instance.logout()));
      sessions.clear();
      document.querySelectorAll('.payment-account .pa-components').forEach(node => node.replaceChildren());
    }
    constructor(root, {api, theme = {}}) {
      this.root = root; this.api = api; this.theme = theme; this.state = null; this.instance = null; this.approval = null; this.busy = false; this.disposed = false;
      if (!document.getElementById('payments-account-style')) {
        const style = document.createElement('style'); style.id = 'payments-account-style'; style.textContent = css; document.head.append(style);
      }
      this.root.classList.add('payment-account');
      // All markup is local and fixed; requirement labels and status text use textContent.
      this.root.innerHTML = `<div class="pa-test" hidden role="note">Test mode · No real payments are processed here.</div><div class="pa-error" hidden role="alert"></div>
        <section class="pa-card"><div class="pa-top"><div><div class="pa-eyebrow">Payment settings</div><h2>Payments account</h2></div><span class="pa-badge">Checking account</span></div>
        <p class="pa-description" aria-live="polite">Checking whether your account is ready to accept payments.</p><div class="pa-checks" hidden></div><ul class="pa-requirements" hidden></ul>
        <div class="pa-country" hidden><label>Business country <input autocomplete="country" maxlength="2" placeholder="e.g. GB" aria-label="Business country (two-letter code)"></label><p class="pa-small">Use the two-letter country code where your business is registered.</p></div>
        <div class="pa-actions"><button class="pa-connect pa-primary-button" hidden>Connect payments account</button><button class="pa-refresh">Refresh status</button></div>
        <div class="pa-confirm" hidden><p>Create or resume the payments account for this application?</p><div class="pa-actions"><button class="pa-approve pa-primary-button">Confirm and continue</button><button class="pa-back">Go back</button></div></div>
        <p class="pa-small">Your account receives your payments. Only administrators can change these settings.</p></section><div class="pa-components"></div>`;
      this.find('.pa-refresh').onclick = () => this.refresh();
      this.find('.pa-connect').onclick = () => this.start();
      this.find('.pa-approve').onclick = () => this.start(this.approval);
      this.find('.pa-back').onclick = () => { this.approval = null; this.find('.pa-confirm').hidden = true; };
      if (window.frappe?.app?.logout && !frappe.app.logout.paymentsAccountWrapped) {
        const logout = frappe.app.logout;
        const wrapped = async function(...args) { await PaymentsAccountPanel.signOutAll(); return logout.apply(this, args); };
        wrapped.paymentsAccountWrapped = true;
        frappe.app.logout = wrapped;
      }
      this.refresh();
    }
    find(selector) { return this.root.querySelector(selector); }
    error() { this.find('.pa-error').textContent = 'Your payments account could not be opened. Refresh the page and try again.'; this.find('.pa-error').hidden = false; }
    async run(fn) {
      if (this.busy || this.disposed) return;
      this.busy = true; this.root.querySelectorAll('button').forEach(button => button.disabled = true); this.find('.pa-error').hidden = true;
      try { await fn(); } catch { this.error(); }
      finally { this.busy = false; this.root.querySelectorAll('button').forEach(button => button.disabled = false); }
    }
    refresh() { return this.run(async () => { const status = await this.api('status'); if (this.disposed) return; this.state = status; this.render(); if (status.state !== 'not_connected') await this.mount(); }); }
    render() {
      const state = this.state.state;
      if (state === 'not_connected') {
        this.find('.pa-components').replaceChildren(); this.instance = null; this.find('.pa-test').hidden = true;
      }
      const labels = {not_connected: 'Not connected', incomplete: 'Setup incomplete', ready: 'Ready'};
      this.find('.pa-badge').textContent = labels[state] || 'Checking account';
      this.find('.pa-badge').className = 'pa-badge pa-' + (labels[state] ? state : 'incomplete');
      this.find('.pa-description').textContent = state === 'ready' ? 'Your account can accept payments and send payouts to your bank. Manage everything below.' : state === 'incomplete' ? 'Your account needs a little more information before it is fully ready. Continue setup below, then refresh its status.' : 'Connect your own account to accept invoice payments, payment links and bank transfers in one place.';
      const checks = this.find('.pa-checks'); checks.hidden = state === 'not_connected'; checks.replaceChildren();
      for (const [label, enabled] of [['Payments', this.state.chargesEnabled], ['Payouts', this.state.payoutsEnabled]]) {
        const item = document.createElement('span'); item.textContent = label + (enabled ? ' · Enabled' : ' · Not enabled yet'); checks.append(item);
      }
      const requirements = this.find('.pa-requirements'); requirements.replaceChildren();
      requirements.hidden = state !== 'incomplete' || !this.state.requirements?.length;
      for (const text of this.state.requirements || []) { const li = document.createElement('li'); li.textContent = text; requirements.append(li); }
      this.find('.pa-country').hidden = state !== 'not_connected'; this.find('.pa-connect').hidden = state !== 'not_connected';
    }
    start(confirmation) { return this.run(async () => {
      const result = await this.api('connect', {confirmation: confirmation || null, country: this.find('input').value.trim()});
      if (this.disposed) return;
      if (result.confirmation) { this.approval = result.confirmation; this.find('.pa-confirm').hidden = false; return; }
      this.approval = null; this.find('.pa-confirm').hidden = true;
      if (result.mode === 'hosted') { window.location.assign(result.onboardingUrl); return; }
      this.state = await this.api('status'); this.render(); await this.mount();
    }); }
    appearance() {
      const style = getComputedStyle(this.root);
      return {variables: {colorPrimary: style.getPropertyValue('--pa-primary').trim() || '#2b59d1',
        colorBackground: getComputedStyle(this.find('.pa-card')).backgroundColor,
        colorText: style.color, fontFamily: style.fontFamily, borderRadius: getComputedStyle(this.find('button')).borderRadius,
        ...this.theme}};
    }
    async mount() {
      const runtime = await loadRuntime();
      if (this.disposed) return;
      if (!this.instance) {
        const first = await this.api('session');
        if (this.disposed) return;
        let pending = first.clientSecret;
        const publicKey = first.publishableKey;
        // Mode is derived only from the validated public key, never from URL parameters.
        this.find('.pa-test').hidden = !publicKey.startsWith('pk_test_');
        this.instance = runtime.init({publishableKey: publicKey, appearance: this.appearance(), fetchClientSecret: async () => {
          if (this.disposed) throw new Error('closed');
          const secret = pending || (await this.api('session')).clientSecret; pending = undefined; return secret;
        }});
        sessions.add(this.instance);
      }
      const region = this.find('.pa-components'); region.replaceChildren();
      const add = (name, title, parent = region) => {
        const card = document.createElement('section'); card.className = 'pa-card';
        if (title) { const heading = document.createElement('h3'); heading.textContent = title; card.append(heading); }
        const component = this.instance.create(name); component.setOnLoadError?.(() => this.error());
        if (name === 'notification-banner') {
          card.hidden = true;
          component.setOnNotificationsChange(({total}) => { card.hidden = !(total > 0); });
        }
        if (name === 'account-onboarding') component.setOnExit?.(() => this.refresh());
        card.append(component); parent.append(card);
      };
      add('notification-banner');
      add(this.state.state === 'ready' ? 'account-management' : 'account-onboarding', this.state.state === 'ready' ? 'Account details' : 'Finish setting up your account');
      if (this.state.state === 'ready') {
        const grid = document.createElement('div'); grid.className = 'pa-grid'; region.append(grid);
        for (const [name, label] of [['payments','Payments'],['payouts','Payouts'],['balances','Balances']]) add(name, label, grid);
      }
    }
    dispose() { this.disposed = true; this.root.replaceChildren(); this.instance = null; }
  }
  window.PaymentsAccountPanel = PaymentsAccountPanel;
})();
