/* ══════════════════════════════════════════
   LexConnect – main.js
   ══════════════════════════════════════════ */

'use strict';

/* ── Auto-dismiss flash alerts after 4 s ──────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.alert-auto').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity .5s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 500);
    }, 4000);
  });
});

/* ══════════════════════════════════════════
   MOCK PAYMENT
   ══════════════════════════════════════════ */

function payFees(apptId, btnEl) {
  if (!confirm('Proceed with payment of consultation fees?')) return;

  btnEl.disabled = true;
  btnEl.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Processing…';

  fetch(`/client/pay/${apptId}`, {
    method: 'POST',
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        // Show success toast
        showToast('💳 Payment Successful! Your consultation fee has been paid.', 'success');
        // Update badge in the row
        const badge = document.querySelector(`#pay-status-${apptId}`);
        if (badge) {
          badge.className = 'status-badge badge-paid';
          badge.textContent = 'Paid';
        }
        btnEl.remove();
      } else {
        showToast('Payment failed. Please try again.', 'danger');
        btnEl.disabled = false;
        btnEl.innerHTML = '💳 Pay Fees';
      }
    })
    .catch(() => {
      showToast('Network error. Please try again.', 'danger');
      btnEl.disabled = false;
      btnEl.innerHTML = '💳 Pay Fees';
    });
}

/* ══════════════════════════════════════════
   CHAT POLLING
   ══════════════════════════════════════════ */

let lastTimestamp = '1970-01-01 00:00:00';
let pollInterval  = null;
let chatApptId    = null;
let currentUserId = null;

function initChat(apptId, userId, existingLastTs) {
  chatApptId    = apptId;
  currentUserId = userId;
  if (existingLastTs) lastTimestamp = existingLastTs;

  // Scroll to bottom on load
  scrollChat();

  // Start polling every 3 seconds
  pollInterval = setInterval(pollChat, 3000);
}

function pollChat() {
  fetch(`/chat/poll/${chatApptId}?since=${encodeURIComponent(lastTimestamp)}`)
    .then(r => r.json())
    .then(data => {
      if (data.messages && data.messages.length > 0) {
        data.messages.forEach(m => {
          appendMessage(m.sender_id, m.sender_name, m.message_text, m.timestamp);
          lastTimestamp = m.timestamp;
        });
        scrollChat();
      }
    })
    .catch(() => { /* silent – keep polling */ });
}

function sendChatMessage() {
  const input = document.getElementById('chat-input');
  const text  = input.value.trim();
  if (!text) return;

  const sendBtn = document.getElementById('chat-send-btn');
  sendBtn.disabled = true;
  input.disabled   = true;

  fetch(`/chat/send/${chatApptId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text })
  })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        input.value = '';
        // Optimistic UI – add our own bubble immediately
        appendMessage(currentUserId, 'You', text, data.timestamp, true);
        lastTimestamp = data.timestamp;
        scrollChat();
      }
    })
    .finally(() => {
      sendBtn.disabled = false;
      input.disabled   = false;
      input.focus();
    });
}

function appendMessage(senderId, senderName, text, ts, isSelf) {
  const isMine = isSelf || (String(senderId) === String(currentUserId));
  const box = document.getElementById('chat-messages');
  if (!box) return;

  const div = document.createElement('div');
  div.className = `msg-bubble ${isMine ? 'mine' : 'theirs'}`;

  const timeStr = ts ? ts.slice(11, 16) : '';  // HH:MM

  div.innerHTML = `
    <div class="msg-inner">${escapeHtml(text)}</div>
    <div class="msg-meta">${isMine ? '' : `<strong>${escapeHtml(senderName)}</strong> · `}${timeStr}</div>
  `;
  box.appendChild(div);
}

function scrollChat() {
  const box = document.getElementById('chat-messages');
  if (box) box.scrollTop = box.scrollHeight;
}

/* ── Enter key in chat input ─────────────── */
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('chat-input');
  if (input) {
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
      }
    });
  }
});

/* ══════════════════════════════════════════
   TOAST HELPER
   ══════════════════════════════════════════ */

function showToast(message, type = 'success') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText = 'position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;display:flex;flex-direction:column;gap:.5rem;';
    document.body.appendChild(container);
  }

  const colours = { success: '#1a7a4a', danger: '#c0392b', info: '#0f2557', warning: '#856404' };
  const toast = document.createElement('div');
  toast.style.cssText = `
    background: ${colours[type] || colours.info};
    color: #fff;
    padding: .85rem 1.4rem;
    border-radius: 12px;
    box-shadow: 0 6px 24px rgba(0,0,0,.2);
    font-size: .9rem;
    font-weight: 500;
    max-width: 320px;
    animation: slideUp .3s ease;
  `;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.transition = 'opacity .4s';
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 400);
  }, 4000);
}

/* Inject animation */
const style = document.createElement('style');
style.textContent = `@keyframes slideUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}`;
document.head.appendChild(style);

/* ══════════════════════════════════════════
   HTML ESCAPE HELPER
   ══════════════════════════════════════════ */

function escapeHtml(str) {
  const d = document.createElement('div');
  d.appendChild(document.createTextNode(str));
  return d.innerHTML;
}
