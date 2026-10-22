// Actual app shell and drop-in component, fake API replies and a locally stubbed runtime.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const BASE = process.env.PAYMENTS_CHECK_URL || 'http://127.0.0.1:18173';
const API = 'erpnext.erp_integrations.pramaan.payment_account.';
const output = path.join(__dirname, 'screenshots', 'payments-account');
const stub = `window.StripeConnect={init(options){window.accountAppearance=options.appearance;options.fetchClientSecret();return {logout:async()=>{window.accountLoggedOut=true},create(name){const el=document.createElement('div');el.dataset.component=name;el.style.cssText='padding:18px;border:1px solid #e5e7eb;border-radius:12px;background:#fff;color:#171717;font:14px system-ui';const names={'notification-banner':'Loading account notifications…','account-onboarding':'Business details','account-management':'Business profile','payments':'Recent payments','payouts':'Payout schedule','balances':'Available balance'};el.textContent=names[name];if(name==='account-onboarding'){const p=document.createElement('p');p.textContent='Add the information needed to finish setting up your account.';el.append(p);const button=document.createElement('button');button.textContent='Continue';button.style.cssText='background:'+options.appearance.variables.colorPrimary+';color:white;border:0;border-radius:'+options.appearance.variables.borderRadius+';padding:10px 16px';el.append(button)}el.setOnNotificationsChange=callback=>callback({total:0,actionRequired:0});el.setOnLoadError=()=>{};el.setOnExit=()=>{};return el}}}};`;
let launchedBrowser;
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true}); launchedBrowser=browser;
 let state='not_connected', mode='test', mutations=0, sessions=0;
 const blocked=[], logs=[];
 const context=await browser.newContext();
 await context.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.href==='https://connect-js.stripe.com/v1.0/connect.js')return route.fulfill({contentType:'application/javascript',body:stub});
  if(url.origin!==BASE){blocked.push(url.host);return route.abort()}
  if(url.pathname.includes('/api/method/'+API)){
   const method=url.pathname.split('.').at(-1);
   let args={};try{args=route.request().postDataJSON()||{}}catch{}
   let message;
   if(method==='status')message={state,chargesEnabled:state==='ready',payoutsEnabled:state==='ready',requirements:state==='incomplete'?['Add a bank account for payouts','Complete your company details']:[]};
   if(method==='session'){sessions++;message={clientSecret:'fixture_secret_only',publishableKey:'pk_'+mode+'_fixture'}}
   if(method==='connect'){if(args.confirmation){mutations++;state='incomplete';message={mode:'embedded'}}else message={confirmation:'fixture-confirmation'}}
   return route.fulfill({headers:{'Content-Type':'application/json','Cache-Control':'no-store'},body:JSON.stringify({message})});
  }
  return route.continue();
 });
 const login=await context.request.post(BASE+'/api/method/login',{form:{usr:'Administrator',pwd:process.env.PAYMENTS_CHECK_PASSWORD||'fixture-local-only'}});
 assert.equal(login.status(),200);
 const page=await context.newPage();page.on('console',msg=>logs.push(msg.text()));page.on('pageerror',error=>logs.push(error.message));
 for(const [width,height,label] of [[1440,1100,'desktop'],[390,1100,'mobile']]){
  await page.setViewportSize({width,height});
  for(const next of ['not_connected','incomplete','ready']){
   state=next;mode='test';
   await page.goto(BASE+'/app/payments-account');
   await page.locator('.payment-account').waitFor();
   await page.locator('.pa-badge').filter({hasText:{not_connected:'Not connected',incomplete:'Setup incomplete',ready:'Ready'}[next]}).waitFor();
   if(next!=='not_connected')await page.locator('[data-component="'+(next==='ready'?'balances':'account-onboarding')+'"]').waitFor();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'horizontal overflow');
   if(next==='ready')for(const component of ['payments','payouts','balances','account-management','notification-banner'])assert.equal(await page.locator('[data-component="'+component+'"]').count(),1);
   if(next==='not_connected')assert.equal(await page.locator('.pa-components [data-component]').count(),0);
   if(next!=='not_connected')assert.match(await page.locator('.pa-test').innerText(),/Test mode/);
   if(next==='incomplete')assert(!(await page.locator('.pa-components').innerText()).includes('Your account details are up to date'));
   await page.screenshot({path:path.join(output,next+'-'+label+'.png'),fullPage:true});
  }
 }
 state='not_connected';await page.goto(BASE+'/app/payments-account');await page.getByRole('button',{name:'Connect payments account',exact:true}).click();
 await page.getByRole('button',{name:'Confirm and continue'}).waitFor();assert.equal(mutations,0);
 await page.getByRole('button',{name:'Confirm and continue'}).click();await page.locator('[data-component="account-onboarding"]').waitFor();assert.equal(mutations,1);
 assert.equal(await page.evaluate(()=>JSON.stringify(localStorage).includes('fixture_secret_only') || JSON.stringify(sessionStorage).includes('fixture_secret_only')),false);
 assert(!logs.join(' ').includes('fixture_secret_only'),'secret logged');
 const appearance=await page.evaluate(()=>window.accountAppearance.variables);assert(appearance.fontFamily&&appearance.borderRadius&&appearance.colorPrimary&&appearance.colorBackground);
 state='ready';mode='live';await page.goto(BASE+'/app/payments-account');await page.locator('[data-component="balances"]').waitFor();assert(await page.locator('.pa-test').isHidden(),'live mode must not show test notice');
 state='not_connected';await page.getByRole('button',{name:'Refresh status',exact:true}).click();await page.getByRole('button',{name:'Connect payments account',exact:true}).waitFor();
 assert.equal(await page.locator('.pa-components [data-component]').count(),0,'disconnected account must clear old components');
 state='ready';await page.getByRole('button',{name:'Refresh status',exact:true}).click();await page.locator('[data-component="balances"]').waitFor();
 await page.evaluate(()=>window.PaymentsAccountPanel.signOutAll());assert.equal(await page.evaluate(()=>window.accountLoggedOut),true);
 assert.equal(blocked.length,0,'unexpected outside hosts');
 console.log(JSON.stringify({passed:true,screenshots:6,states:3,sessions,connectRequiresConfirmation:true,balancesMounted:true,liveNoticeHidden:true,outsideHostsBlocked:true,secretLogs:false}));
 await browser.close();
})().catch(async error=>{console.error(error.message);await launchedBrowser?.close();process.exitCode=1});
