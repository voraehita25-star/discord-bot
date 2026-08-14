/**
 * Command palette — one keystroke to every action in the app.
 *
 * The dashboard already had Ctrl+1..6, Ctrl+R, Ctrl+T and `?`. That is a good
 * set and it has the problem every good set has: it only helps people who have
 * already learned it, and everything NOT in it (start the bot, open the data
 * folder, switch to compact density, turn the petals off) is reachable only by
 * navigating to the screen that owns the control and finding it there. Settings
 * alone is eight stacked cards deep.
 *
 * So Ctrl+K opens a searchable list of every one of those actions, showing the
 * existing shortcut beside the ones that have one — which makes the palette the
 * place people LEARN the chords rather than a second, competing way to do
 * things. Nothing here is a new capability; every entry calls the same function
 * its button already calls.
 *
 * Destructive actions are deliberately absent. "Clear All History" and "Clear
 * Logs" both wipe data behind a confirm dialog, and a fuzzy list where Enter
 * fires the top hit is the exact wrong place to put them — one keystroke too
 * many and a mistyped query runs the thing. They stay on their own screens,
 * where reaching them is a decision.
 */
/**
 * Score one command against a query.
 *
 * Subsequence matching, not substring: "opd" should find "Open Data Folder",
 * which is the whole reason to type into a palette instead of scrolling it.
 * Ranking then has to put the obvious answer first, so four bonuses stack:
 *
 *   - a hit on a WORD START is worth far more than one mid-word, which is what
 *     makes initials ("od") beat an accidental subsequence through another
 *     label;
 *   - CONTIGUOUS hits are worth more than scattered ones, so typing a real
 *     prefix ("data") outranks a coincidence;
 *   - COVERAGE — how much of the label the query accounts for — favours the
 *     command whose name is mostly what you typed;
 *   - an EARLY first hit breaks whatever is still level.
 *
 * Coverage earns its place: without it "logs" ranked `Open Logs Folder` above
 * `Go to Logs`. Both match "logs" as a whole word at a word start, so the two
 * scored identically on the first two bonuses and the earlier hit (index 5 vs
 * 6) decided it — the longer, less relevant label won by one point, on the
 * accident of having a shorter first word. Coverage is the thing that actually
 * separates them: "logs" is 40% of `Go to Logs` and 25% of `Open Logs Folder`.
 *
 * Earliness is therefore kept small and capped, so it settles ties instead of
 * creating them.
 *
 * Keyword-only hits score below every label hit on purpose: they exist so
 * "dark" finds Toggle Theme, not so they can outrank a command whose visible
 * name the user actually typed.
 *
 * Returns null when the command does not match at all.
 */
export function scoreCommand(command, query) {
    const q = query.trim().toLowerCase();
    if (!q)
        return { command, positions: [], score: 0 };
    const label = command.label.toLowerCase();
    const positions = [];
    let score = 0;
    let qi = 0;
    let lastHit = -2;
    for (let i = 0; i < label.length && qi < q.length; i++) {
        if (label[i] !== q[qi])
            continue;
        positions.push(i);
        // Word start: index 0, or preceded by a space/dash/slash.
        const prev = i > 0 ? label[i - 1] : ' ';
        if (i === 0 || prev === ' ' || prev === '-' || prev === '/')
            score += 12;
        if (i === lastHit + 1)
            score += 8;
        lastHit = i;
        qi++;
    }
    if (qi === q.length) {
        // How much of the label the query accounts for.
        score += Math.round(20 * (q.length / label.length));
        // Earliest hit, as a tiebreaker only — floored at 0 so a match late in
        // a long label can never be dragged under the keyword floor.
        score += Math.max(0, 3 - Math.floor((positions[0] ?? 0) / 4));
        return { command, positions, score: score + 40 };
    }
    // Fall back to the hidden search terms, which carry no highlight because
    // they are not on screen to highlight.
    if (command.keywords && command.keywords.toLowerCase().includes(q)) {
        return { command, positions: [], score: 1 };
    }
    return null;
}
/**
 * Rank the commands for a query.
 *
 * An EMPTY query keeps the authored order, because that order is grouped and
 * the grouping is the whole point of the resting state — it is a menu, and a
 * menu that reshuffles is not one. As soon as anything is typed the groups stop
 * mattering and the list goes flat and ranked, so the answer is always row one.
 *
 * `sort` is called on a fresh array of already-matched entries, and ties fall
 * back to the authored index, so the ranking is fully deterministic.
 */
export function filterCommands(commands, query) {
    const matches = [];
    commands.forEach((command, order) => {
        const m = scoreCommand(command, query);
        if (m)
            matches.push({ ...m, order });
    });
    if (!query.trim())
        return matches;
    return matches
        .sort((a, b) => (b.score - a.score) || (a.order - b.order))
        .map(({ command, positions, score }) => ({ command, positions, score }));
}
/**
 * Render a label with the matched characters wrapped in <mark>.
 *
 * Built from text nodes and elements rather than an HTML string. The query is
 * user input and this is the one place it reaches the DOM, so the markup is
 * made injection-proof by construction instead of by remembering to escape.
 */
export function buildLabel(label, positions) {
    const frag = document.createDocumentFragment();
    const hit = new Set(positions);
    let run = '';
    let runIsHit = false;
    const flush = () => {
        if (!run)
            return;
        if (runIsHit) {
            const mark = document.createElement('mark');
            mark.className = 'cmdk-hit';
            mark.textContent = run;
            frag.appendChild(mark);
        }
        else {
            frag.appendChild(document.createTextNode(run));
        }
        run = '';
    };
    for (let i = 0; i < label.length; i++) {
        const isHit = hit.has(i);
        if (isHit !== runIsHit) {
            flush();
            runIsHit = isHit;
        }
        run += label[i];
    }
    flush();
    return frag;
}
export class CommandPalette {
    el;
    host;
    /**
     * A PROVIDER, not a list. Three commands describe their own effect —
     * "Switch to Light Theme", "Use Compact Density", "Hide Sakura Petals" —
     * so their labels depend on state that changes while the app runs. Asking
     * for the set at open time is what keeps a row from offering to turn on
     * something that is already on.
     */
    provide;
    commands = [];
    matches = [];
    activeIndex = 0;
    constructor(el, host, provide) {
        this.el = el;
        this.host = host;
        this.provide = provide;
        this.bind();
    }
    get isOpen() {
        return this.el.modal.classList.contains('active');
    }
    open() {
        if (this.isOpen)
            return;
        this.commands = this.provide();
        this.el.input.value = '';
        this.render('');
        // openModal focuses the first focusable, which IS the input — it is the
        // first control in the dialog — so there is no second focus() to fight.
        this.host.openModal(this.el.modal);
    }
    close() {
        if (!this.isOpen)
            return;
        this.host.closeModal(this.el.modal);
    }
    bind() {
        this.el.input.addEventListener('input', () => this.render(this.el.input.value));
        this.el.input.addEventListener('keydown', (e) => {
            switch (e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    this.move(1);
                    return;
                case 'ArrowUp':
                    e.preventDefault();
                    this.move(-1);
                    return;
                case 'Home':
                    if (this.matches.length) {
                        e.preventDefault();
                        this.setActive(0);
                    }
                    return;
                case 'End':
                    if (this.matches.length) {
                        e.preventDefault();
                        this.setActive(this.matches.length - 1);
                    }
                    return;
                case 'Enter':
                    e.preventDefault();
                    this.runActive();
                    return;
                default:
            }
        });
        // Click-to-run. Delegated, so re-rendering the list never orphans a
        // handler and the rows stay plain elements.
        this.el.list.addEventListener('click', (e) => {
            const row = e.target.closest('.cmdk-item');
            if (!row)
                return;
            const idx = Number(row.dataset.index);
            if (Number.isInteger(idx)) {
                this.setActive(idx);
                this.runActive();
            }
        });
        // Pointer follows the same selection the keyboard drives, so Enter can
        // never run something other than the row under the highlight.
        this.el.list.addEventListener('mousemove', (e) => {
            const row = e.target.closest('.cmdk-item');
            if (!row)
                return;
            const idx = Number(row.dataset.index);
            if (Number.isInteger(idx) && idx !== this.activeIndex)
                this.setActive(idx);
        });
        this.el.modal.querySelectorAll('[data-close-cmdk]').forEach((node) => {
            node.addEventListener('click', () => this.close());
        });
    }
    move(delta) {
        if (!this.matches.length)
            return;
        // Wrap: a palette is a short list and running off either end to nothing
        // is worse than coming round again.
        const n = this.matches.length;
        this.setActive((this.activeIndex + delta + n) % n);
    }
    setActive(index) {
        this.activeIndex = index;
        const rows = this.el.list.querySelectorAll('.cmdk-item');
        rows.forEach((row, i) => {
            const on = i === index;
            row.classList.toggle('active', on);
            row.setAttribute('aria-selected', String(on));
            if (on) {
                this.el.input.setAttribute('aria-activedescendant', row.id);
                row.scrollIntoView({ block: 'nearest' });
            }
        });
        if (!rows.length)
            this.el.input.removeAttribute('aria-activedescendant');
    }
    runActive() {
        const match = this.matches[this.activeIndex];
        if (!match)
            return;
        // Close FIRST: closeModal restores focus to whatever opened the palette,
        // and several commands move focus themselves (switchPage, the shortcuts
        // modal). Running first would let the restore yank focus back off the
        // thing the command just focused.
        this.close();
        match.command.run();
    }
    /** Rebuild the list for a query. */
    render(query) {
        this.matches = filterCommands(this.commands, query);
        this.activeIndex = 0;
        this.el.list.textContent = '';
        const grouped = !query.trim();
        let lastGroup = '';
        let container = this.el.list;
        this.matches.forEach((match, i) => {
            if (grouped && match.command.group !== lastGroup) {
                lastGroup = match.command.group;
                // role="group" keeps the headings legal inside role="listbox" —
                // a listbox may only contain options and groups, and a bare
                // heading div would make the whole list invalid to a screen
                // reader rather than merely undecorated.
                const group = document.createElement('div');
                group.className = 'cmdk-group';
                group.setAttribute('role', 'group');
                group.setAttribute('aria-label', lastGroup);
                const heading = document.createElement('div');
                heading.className = 'cmdk-group-label';
                heading.setAttribute('aria-hidden', 'true');
                heading.textContent = lastGroup;
                group.appendChild(heading);
                this.el.list.appendChild(group);
                container = group;
            }
            else if (!grouped) {
                container = this.el.list;
            }
            container.appendChild(this.buildRow(match, i));
        });
        const none = this.matches.length === 0;
        this.el.empty.classList.toggle('hidden', !none);
        this.el.list.classList.toggle('hidden', none);
        this.setActive(0);
    }
    buildRow(match, index) {
        const row = document.createElement('div');
        row.className = 'cmdk-item';
        row.id = `cmdk-option-${index}`;
        row.dataset.index = String(index);
        row.setAttribute('role', 'option');
        row.setAttribute('aria-selected', 'false');
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'ic');
        svg.setAttribute('aria-hidden', 'true');
        const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
        use.setAttribute('href', `#i-${match.command.icon}`);
        svg.appendChild(use);
        const label = document.createElement('span');
        label.className = 'cmdk-label';
        label.appendChild(buildLabel(match.command.label, match.positions));
        row.append(svg, label);
        if (match.command.hint) {
            const kbd = document.createElement('kbd');
            kbd.className = 'cmdk-hint';
            kbd.textContent = match.command.hint;
            row.appendChild(kbd);
        }
        return row;
    }
}
//# sourceMappingURL=command-palette.js.map