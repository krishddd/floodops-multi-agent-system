/** Member selector — toggle individual ensemble members. */
export function renderMemberSelector(container, members, onToggle) {
    if (!container) return;
    container.innerHTML = `<div class="panel-title" style="margin-top:12px">Members (${members.length})</div>
    <div style="display:flex;flex-wrap:wrap;gap:4px">${members.slice(0, 20).map(m =>
        `<button class="source-badge" data-id="${m.member_id}" style="cursor:pointer">#${m.member_id}</button>`
    ).join('')}</div>`;
    container.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => {
            btn.classList.toggle('active');
            if (onToggle) onToggle(parseInt(btn.dataset.id));
        });
    });
}
