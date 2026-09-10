/* Scoped chat events. Pure reducers are also exercised by the Node regressions. */
(function (root) {
    const noUpdate = () => root.dash_clientside.no_update;
    const matches = (event, cursor) => !!event && !!cursor &&
        event.selection_id === cursor.selection_id && event.thread_id === cursor.thread_id;

    function acceptJob(event, cursor) {
        const n = noUpdate();
        if (!matches(event, cursor)) return [n, n, n, n, n];
        return [event.transcript || n, !event.done, !!event.done,
                event.status || '', event.elapsed || ''];
    }

    function acceptLoad(event, cursor) {
        const n = noUpdate();
        if (!matches(event, cursor)) return [n, n, n];
        return [event.transcript, !!event.running, !event.running];
    }

    function acceptRender(event, cursor) {
        const n = noUpdate();
        if (!matches(event, cursor)) return [n, n];
        return [event.children, []];
    }

    // Event publication uses set_props so Dash does not build a circular
    // store -> request -> response -> store dependency graph. The pure reducers
    // above remain the single place that decides whether an event is current.
    function publishJob(event, cursor) {
        const values = acceptJob(event, cursor);
        const targets = [['chat-store', 'data'], ['is-thinking', 'data'],
            ['job-poll', 'disabled'], ['thinking-agent', 'children'], ['thinking-elapsed', 'children']];
        values.forEach((value, index) => {
            if (value !== noUpdate()) root.dash_clientside.set_props(targets[index][0], {[targets[index][1]]: value});
        });
        return matches(event, cursor) ? event.selection_id : noUpdate();
    }

    function publishLoad(event, cursor) {
        const values = acceptLoad(event, cursor);
        const targets = [['chat-store', 'data'], ['is-thinking', 'data'], ['job-poll', 'disabled']];
        values.forEach((value, index) => {
            if (value !== noUpdate()) root.dash_clientside.set_props(targets[index][0], {[targets[index][1]]: value});
        });
        return matches(event, cursor) ? event.selection_id : noUpdate();
    }

    function select(chat, clicks, newClicks, activeId, previous) {
        const n = noUpdate();
        const triggered = root.dash_clientside.callback_context.triggered || [];
        const trigger = triggered[0] || {};
        const prop = trigger.prop_id || '';
        const component = prop.slice(0, prop.lastIndexOf('.'));
        let threadId = (chat || {}).thread_id || null;
        let loading = false;
        if (!threadId && activeId && !(previous || {}).selection_id) {
            threadId = activeId;
            loading = true;
        } else if (component.startsWith('{')) {
            if (!trigger.value) return [n, n, n, n, n];
            threadId = JSON.parse(component).id;
            loading = true;
        } else if (component === 'new-chat-btn') {
            if (!newClicks) return [n, n, n, n, n];
            threadId = null;
        }
        const cursor = {thread_id: threadId, selection_id: root.crypto.randomUUID(),
            loading, job_id: loading ? null : (chat || {})._job_id || null};
        return [cursor, !loading, !threadId, loading ? true : (threadId ? n : false), threadId];
    }

    const api = {select, acceptJob, acceptLoad, acceptRender, publishJob, publishLoad, matches};
    if (typeof module !== 'undefined') module.exports = api;
    root.dash_clientside = Object.assign({}, root.dash_clientside, {chatLifecycle: api});
})(typeof window === 'undefined' ? globalThis : window);
