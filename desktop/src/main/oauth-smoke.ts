import { createServer } from 'node:http';

export interface OAuthSmokeFixture { url: string; completed(): boolean; cookieReturned(): boolean; openerPreserved(): boolean; requests(): string[]; close(): Promise<void> }

export async function startOAuthSmokeFixture(): Promise<OAuthSmokeFixture> {
  let complete = false; let cookie = false; let opener = false; const requests: string[] = [];
  const server = createServer((request, response) => {
    const url = new URL(request.url || '/', 'http://127.0.0.1'); requests.push(url.pathname); response.setHeader('content-type', 'text/html; charset=utf-8'); response.setHeader('cache-control', 'no-store');
    if (url.pathname === '/complete') { complete = true; if (url.searchParams.has('opener')) opener = url.searchParams.get('opener') === 'true'; response.end('ok'); return; }
    if (url.pathname === '/oauth') { response.setHeader('set-cookie', 'warden_oauth_fixture=present; Path=/; HttpOnly; SameSite=Lax'); response.end('<!doctype html><title>OAuth fixture</title><p>Completing secure popup redirect…</p><script>setTimeout(()=>location.replace("/callback?code=fixture-secret-code"),100)</script>'); return; }
    if (url.pathname === '/callback') { cookie = String(request.headers.cookie || '').includes('warden_oauth_fixture=present'); response.end('<!doctype html><title>OAuth callback</title><script>const preserved=Boolean(window.opener);if(window.opener){window.opener.postMessage({type:"warden-oauth-complete"},location.origin)}fetch("/complete?opener="+preserved).finally(()=>window.close())</script>'); return; }
    response.end('<!doctype html><title>OAuth opener</title><p id="state">Opening OAuth popup…</p><script>addEventListener("message",event=>{if(event.origin===location.origin&&event.data?.type==="warden-oauth-complete"){document.querySelector("#state").textContent="OAuth complete";fetch("/complete")}});window.open("/oauth","warden-oauth-smoke","popup,width=620,height=700")</script>');
  });
  await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', () => resolve()); });
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('OAuth fixture failed to bind.');
  return { url: `http://127.0.0.1:${address.port}/`, completed: () => complete, cookieReturned: () => cookie, openerPreserved: () => opener, requests: () => [...requests], close: () => new Promise<void>((resolve, reject) => { server.closeAllConnections(); server.close((error) => error ? reject(error) : resolve()); }) };
}
