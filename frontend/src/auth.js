/** Google OAuth login flow */
export function login() { window.location.href = '/auth/login'; }
export async function checkAuthStatus(sessionId) {
    const resp = await fetch(`/auth/status?session_id=${sessionId}`);
    return resp.json();
}
export async function logout(sessionId) {
    await fetch('/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sessionId }) });
}
