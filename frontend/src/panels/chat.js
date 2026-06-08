/** Chat drawer controller. */
const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';

export function initChat() {
    const toggle = document.getElementById('chat-toggle');
    const drawer = document.getElementById('chat-drawer');
    const input = document.getElementById('chat-input');
    const send = document.getElementById('chat-send');

    toggle?.addEventListener('click', () => {
        drawer.classList.toggle('open');
    });

    const sendMsg = async () => {
        const text = input.value.trim();
        if (!text) return;
        appendMsg('user', text);
        input.value = '';
        try {
            const resp = await fetch(`${API}/flood/chat`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            });
            const data = await resp.json();
            appendMsg('assistant', data.response || 'No response');
        } catch (e) {
            appendMsg('assistant', 'Backend unavailable — start the server.');
        }
    };

    send?.addEventListener('click', sendMsg);
    input?.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMsg(); });
}

function appendMsg(role, text) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `chat-msg ${role}`;
    div.textContent = text;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}
