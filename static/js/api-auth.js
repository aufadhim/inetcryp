/* One validated login flight for every concurrent dashboard request. */
(function (root) {
  function createAuthFetch({fetch, storage, login, origin}) {
    const key = 'inetcryp_access_password';
    let credential = storage.getItem(key) || '', flight = null, ready = false;
    async function authenticate() {
      if (ready) return;
      if (!flight) flight = (async () => {
        const check = async value => {
          const response = await fetch('/api/auth/check', {headers: {'X-Access-Password': value}, cache: 'no-store'});
          if (response.status === 401) return false;
          if (!response.ok) throw new Error('Layanan login sedang tidak tersedia.');
          return true;
        };
        if (!(await check(credential))) {
          storage.removeItem(key);
          credential = await login(check);
          storage.setItem(key, credential);
        }
        ready = true;
      })().finally(() => { flight = null; });
      return flight;
    }
    return async (input, init = {}) => {
      const url = new URL(typeof input === 'string' ? input : input.url, origin);
      if (url.origin !== origin || !url.pathname.startsWith('/api/')) return fetch(input, init);
      await authenticate();
      const send = () => {
        const headers = new Headers(init.headers || (input && input.headers) || {});
        headers.set('X-Access-Password', credential);
        return fetch(input, {...init, headers});
      };
      const sent = credential;
      let response = await send();
      if (response.status === 401) {
        // A late response must not invalidate a newer, successful login.
        if (sent === credential) ready = false;
        await authenticate();
        response = await send();
      }
      return response;
    };
  }
  if (typeof module !== 'undefined') module.exports = {createAuthFetch};
  if (!root.document) return;
  function login(check) {
    return new Promise(resolve => {
      const dialog = document.createElement('dialog');
      dialog.style.cssText = 'background:#111827;color:white;border:1px solid #22d3ee;border-radius:16px;padding:24px;max-width:90vw';
      dialog.innerHTML = '<form><h2>Masuk INETCRYP</h2><p>Satu login untuk seluruh dashboard.</p><input type="password" autocomplete="current-password" aria-label="Password dashboard" required style="color:black;padding:10px;width:100%;box-sizing:border-box"><p role="status"></p><button type="submit" style="padding:10px;color:black">Masuk</button></form>';
      dialog.addEventListener('cancel', event => event.preventDefault());
      document.body.appendChild(dialog);
      dialog.showModal();
      const form = dialog.querySelector('form'), input = dialog.querySelector('input');
      const status = dialog.querySelector('[role=status]'), button = dialog.querySelector('button');
      form.addEventListener('submit', async event => {
        event.preventDefault(); button.disabled = true;
        status.textContent = 'Memeriksa…';
        try {
          if (await check(input.value)) { const value = input.value; dialog.close(); dialog.remove(); resolve(value); }
          else { status.textContent = 'Password ditolak server. Periksa kembali, lalu coba lagi.'; input.focus(); }
        } catch (_) { status.textContent = 'Server/koneksi bermasalah. Coba lagi; password belum dinyatakan salah.'; }
        finally { button.disabled = false; }
      });
      input.focus();
    });
  }
  root.fetch = createAuthFetch({fetch:root.fetch.bind(root), storage:root.sessionStorage, login, origin:root.location.origin});
})(typeof window === 'undefined' ? globalThis : window);
