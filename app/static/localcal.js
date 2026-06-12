// Reagrupa tarjetas de partido por DÍA LOCAL del dispositivo y muestra la hora local.
// Cada tarjeta debe tener: class "match-card", data-kickoff (ISO con Z),
// data-predicted ("1"/"0"), data-locked ("1"/"0") y, opcional, un elemento .kickoff-time.
// opts: { listId, dias[7], meses[12], pend1, pendN, sectionClass?, bodyClass?, scrollToday? }
window.regroupByLocalDay = function (opts) {
    const list = document.getElementById(opts.listId);
    if (!list) return;
    const cards = [...list.querySelectorAll('.match-card')];
    if (!cards.length) return;

    const DIAS = opts.dias, MESES = opts.meses;
    const T1 = opts.pend1, TN = opts.pendN;
    const pad = n => String(n).padStart(2, '0');
    const keyOf = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const todayKey = keyOf(new Date());

    const groups = new Map();
    for (const c of cards) {
        const d = new Date(c.dataset.kickoff);   // 'Z' → hora local
        const k = keyOf(d);
        if (!groups.has(k)) groups.set(k, { d, cards: [] });
        groups.get(k).cards.push(c);
        const t = c.querySelector('.kickoff-time');
        if (t) t.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    list.innerHTML = '';
    let todayEl = null;
    for (const k of [...groups.keys()].sort()) {
        const g = groups.get(k);
        const isToday = k === todayKey;
        const pending = g.cards.filter(c => c.dataset.predicted === '0' && c.dataset.locked === '0').length;
        const label = `${DIAS[g.d.getDay()]} ${g.d.getDate()} ${MESES[g.d.getMonth()]}`;

        const sec = document.createElement('div');
        sec.className = opts.sectionClass || 'mb-7';
        if (isToday) sec.id = 'today-anchor';

        const head = document.createElement('div');
        head.className = 'flex items-center gap-3 mb-3';
        head.innerHTML = `
            <span class="h-px flex-1 bg-gradient-to-r from-transparent to-white/15"></span>
            <div class="flex items-center gap-2">
                ${isToday ? '<span class="w-2 h-2 rounded-full bg-lime-400 animate-livepulse"></span>' : ''}
                <h2 class="font-display text-sm font-semibold uppercase tracking-[0.2em] ${isToday ? 'text-lime-400' : 'text-white/60'}">${label}</h2>
                ${pending > 0 ? `<span class="text-[10px] font-display uppercase tracking-wider text-amber-400 bg-amber-400/10 px-2 py-0.5 rounded-full">${pending} ${pending > 1 ? TN : T1}</span>` : ''}
            </div>
            <span class="h-px flex-1 bg-gradient-to-l from-transparent to-white/15"></span>`;
        sec.appendChild(head);

        const body = document.createElement('div');
        body.className = opts.bodyClass || 'space-y-2';
        g.cards.forEach(c => body.appendChild(c));
        sec.appendChild(body);
        list.appendChild(sec);
        if (isToday) todayEl = sec;
    }

    if (opts.scrollToday !== false && todayEl &&
        todayEl.getBoundingClientRect().top > window.innerHeight * 0.6) {
        todayEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
};
