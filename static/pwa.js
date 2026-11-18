/* PWA 前端：註冊 Service Worker、安裝按鈕（含 iOS 提示）、離線提示列。 */
(() => {
  'use strict';

  // 1) Service Worker
  // Gradio 會在頁面 load 之後才動態插入本腳本，所以不能只監聽 load 事件
  if ('serviceWorker' in navigator) {
    const register = () => navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
    if (document.readyState === 'complete') register();
    else window.addEventListener('load', register);
  }

  const standalone =
    window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (_) { /* 隱私模式等情況略過 */ } },
  };

  const el = (tag, attrs, text) => {
    const n = document.createElement(tag);
    Object.assign(n, attrs || {});
    if (text) n.textContent = text;
    return n;
  };

  function boot() {
    // 2) 安裝按鈕（Chrome / Edge / Android）
    let deferred = null;
    const btn = el('button', { id: 'pwa-install', type: 'button', hidden: true }, '📲 安裝 App');
    document.body.appendChild(btn);
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferred = e;
      if (!standalone) btn.hidden = false;
    });
    btn.addEventListener('click', async () => {
      if (!deferred) return;
      btn.hidden = true;
      deferred.prompt();
      try { await deferred.userChoice; } catch (_) { /* ignore */ }
      deferred = null;
    });
    window.addEventListener('appinstalled', () => { btn.hidden = true; });

    // 3) iOS Safari 沒有 beforeinstallprompt，只提示一次
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    if (ios && !standalone && !store.get('pwa-ios-hint')) {
      const tip = el('div', { id: 'pwa-ios-tip', role: 'status' });
      tip.append(
        el('span', {}, '安裝到主畫面：點 Safari 的「分享」→「加入主畫面」'),
        Object.assign(el('button', { type: 'button', ariaLabel: '關閉' }, '✕'), {
          onclick: () => { tip.remove(); store.set('pwa-ios-hint', '1'); },
        }),
      );
      document.body.appendChild(tip);
    }

    // 4) 離線提示列
    const bar = el('div', { id: 'pwa-offline', role: 'alert', hidden: true }, '⚠ 目前離線，無法檢索與提問');
    document.body.appendChild(bar);
    const sync = () => { bar.hidden = navigator.onLine; };
    window.addEventListener('online', sync);
    window.addEventListener('offline', sync);
    sync();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
