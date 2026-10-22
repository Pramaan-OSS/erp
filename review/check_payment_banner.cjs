// Render the real drop-in component with a fake runtime; no outside requests.
const {chromium} = require('playwright');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => route.abort());
    await page.setContent('<main id="account"></main>');
    await page.evaluate(() => {
      window.StripeConnect = {init: () => ({create(name) {
        const element = document.createElement('div');
        element.dataset.component = name;
        element.textContent = name;
        element.setOnNotificationsChange = callback => { window.notify = callback; };
        return element;
      }})};
    });
    await page.addScriptTag({path:path.join(__dirname,'../erpnext/public/js/payment_account.js')});
    for (const state of ['incomplete', 'ready']) {
      await page.evaluate(state => {
        window.panel?.dispose();
        window.panel = new PaymentsAccountPanel(document.querySelector('#account'), {
          api: async method => method === 'session'
            ? {clientSecret:'fixture_only',publishableKey:'pk_test_fixture'}
            : {state,chargesEnabled:state==='ready',payoutsEnabled:state==='ready',requirements:[]}
        });
      },state);
      const banner = page.locator('[data-component="notification-banner"]');
      await banner.waitFor({state:'attached'});
      assert(await banner.isHidden(), 'banner must start hidden before its callback');
      for (const width of [1200,390]) {
        await page.setViewportSize({width,height:900});
        await page.evaluate(() => window.notify({total:0,actionRequired:0}));
        assert(await banner.isHidden(), 'empty banner card must be hidden');
        await page.evaluate(() => window.notify({total:2,actionRequired:1}));
        assert(await banner.isVisible(), 'notifications must reveal the card');
        await page.evaluate(() => window.notify({total:0,actionRequired:0}));
        assert(await banner.isHidden(), 'cleared notifications must hide the card again');
      }
      assert.equal(await page.locator('[data-component="'+(state==='ready'?'payments':'account-onboarding')+'"]').isVisible(),true);
    }
    console.log('PASS: banner hidden before callback and at zero, visible with content, hidden after clearing; both states and screen sizes');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
