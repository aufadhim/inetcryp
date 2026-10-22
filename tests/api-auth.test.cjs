const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createAuthFetch} = require('../static/js/api-auth.js');
function storage() { const data = new Map(); return {getItem:k=>data.get(k), setItem:(k,v)=>data.set(k,v), removeItem:k=>data.delete(k)}; }
test('parallel startup checks and login are single flight', async () => {
  let prompts=0, checks=0, calls=0;
  const state=storage();
  const request=createAuthFetch({origin:'https://test.local', storage:state,
    fetch:async (url,init)=> {
      if(url==='/api/auth/check') { checks++; return new Response('', {status:init.headers['X-Access-Password']==='valid'?200:401}); }
      calls++; assert.equal(init.headers.get('X-Access-Password'),'valid'); return new Response('{}');
    },login:async check=> { prompts++; assert.equal(await check('wrong'),false); assert.equal(await check('valid'),true); return 'valid'; }});
  await Promise.all(Array.from({length:30},()=>request('/api/data')));
  assert.equal(prompts,1);assert.equal(calls,30);assert.equal(checks,3);
});
test('late unauthorized response cannot erase newer credentials', async () => {
  const state=storage();state.setItem('inetcryp_access_password','old');
  let prompts=0, release;
  const delayed=new Promise(resolve=>release=resolve);
  let oldRequests=0;
  const request=createAuthFetch({origin:'https://test.local',storage:state,
    fetch:async(url,init)=> {
      if(url==='/api/auth/check') return new Response('',{status:init.headers['X-Access-Password']==='old' && oldRequests?401:200});
      if(init.headers.get('X-Access-Password')==='old') { oldRequests++; if(oldRequests===2)await delayed; return new Response('',{status:401}); }
      return new Response('{}');
    },login:async()=>{prompts++;return 'new';}});
  const a=request('/api/a'), b=request('/api/b');
  await a;release();await b;
  assert.equal(prompts,1);assert.equal(state.getItem('inetcryp_access_password'),'new');
});
test('server failure does not claim authentication success or clear saved credential', async () => {
  const state=storage();state.setItem('inetcryp_access_password','saved');
  const request=createAuthFetch({origin:'https://test.local',storage:state,fetch:async()=>new Response('',{status:503}),login:()=>{throw Error('must not prompt');}});
  await assert.rejects(request('/api/data'));
  assert.equal(state.getItem('inetcryp_access_password'),'saved');
});
test('credentials never sent to external API URLs', async()=>{
  const request=createAuthFetch({origin:'https://test.local',storage:storage(),login:()=>{throw Error('must not login');},fetch:async(url,init)=>{assert.equal(init.headers,undefined);return new Response('');}});
  await request('https://elsewhere.local/api/data');
});
