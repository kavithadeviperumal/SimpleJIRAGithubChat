const input    = document.getElementById('query-input');
const sendBtn  = document.getElementById('send-btn');
const messages = document.getElementById('messages');

let lastMember  = null;
let firstMessage = true;

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) sendQuery();
});

function fillQuery(chip) {
  input.value = chip.textContent;
  input.focus();
}

function appendMessage(text, type) {
  if (firstMessage) {
    const empty = document.getElementById('empty-state');
    if (empty) empty.remove();
    firstMessage = false;
  }

  const wrapper = document.createElement('div');
  wrapper.className = `message ${type}`;

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;

  wrapper.appendChild(bubble);
  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
  return bubble;
}

async function sendQuery() {
  const query = input.value.trim();
  if (!query) return;

  input.value = '';
  sendBtn.disabled = true;

  appendMessage(query, 'user');
  const thinking = appendMessage('Fetching activity from JIRA and GitHub…', 'thinking');

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, last_member: lastMember }),
    });

    const data = await res.json();
    thinking.closest('.message').remove();

    if (!res.ok) {
      appendMessage(data.error || 'An error occurred.', 'error');
    } else {
      if (data.member) lastMember = data.member;
      appendMessage(data.response, 'bot');
    }
  } catch (err) {
    thinking.closest('.message').remove();
    appendMessage('Network error — is the server running?', 'error');
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}
