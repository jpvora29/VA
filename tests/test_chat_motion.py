"""Exercise the served scroll/status callbacks and their progress dependencies."""
import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def callback_for(component, prop):
    tree = ast.parse(Path("ui/callbacks.py").read_text(encoding="utf-8"))
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        if not isinstance(call.func, ast.Name) or call.func.id not in {"callback", "clientside_callback"}:
            continue
        for arg in call.args:
            if (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                    and arg.func.id == "Output" and len(arg.args) >= 2
                    and all(isinstance(a, ast.Constant) for a in arg.args[:2])
                    and [ast.literal_eval(a) for a in arg.args[:2]] == [component, prop]):
                return call
    raise AssertionError(f"Callback not registered: {component}.{prop}")


def run_js(script):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_running_polls_do_not_invalidate_the_transcript():
    render = callback_for("chat-render", "data")
    inputs = [ast.literal_eval(arg.args[0]) for arg in render.args
              if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "Input"]
    run_js("""
        const assert = require('node:assert/strict');
        const inputs = new Set(INPUTS);
        const invalidations = [];
        globalThis.dash_clientside = {no_update: Symbol(), set_props(id) {
            if (inputs.has(id)) invalidations.push(id);
        }};
        const api = require('./assets/chat_lifecycle.js');
        const cursor = {thread_id: 'A', selection_id: 'a1'};
        for (let i = 0; i < 20; i++) {
            api.publishJob({...cursor, done: false, status: 'Calculating', elapsed: i+'s'}, cursor);
        }
        assert.deepEqual(invalidations, [], 'Timer ticks must not rebuild messages/charts');
        api.publishJob({...cursor, done: true, transcript: {messages: ['answer']}}, cursor);
        assert.deepEqual(invalidations, ['chat-store'], 'Completion must still render the answer');
    """.replace("INPUTS", json.dumps(inputs)))


def test_committed_answer_preserves_reading_position_but_new_question_follows():
    body = ast.literal_eval(callback_for("chat-box", "data-scroll-anchor").args[0])
    run_js("""
        const assert = require('node:assert/strict');
        const listeners = {};
        let questionCount = 1;
        const el = {scrollTop: 600, scrollHeight: 1000, clientHeight: 400,
            addEventListener(name, fn) {listeners[name] = fn;},
            querySelectorAll() {return {length: questionCount};}};
        globalThis.document = {getElementById() {return el;}};
        globalThis.window = {dash_clientside: {no_update: Symbol(),
            callback_context: {triggered: [{prop_id: 'chat-box.children'}]}}};
        globalThis.requestAnimationFrame = fn => fn();
        const scroll = BODY;
        const cursor = {thread_id: 'A'};
        scroll([], [], false, cursor);
        el.scrollTop = 200;
        listeners.scroll();
        // Re-render / completed answer / streaming update are not permission to scroll.
        el.scrollHeight = 1600;
        for (let i = 0; i < 10; i++) scroll([], [], false, cursor);
        assert.equal(el.scrollTop, 200, 'The reader must stay where they scrolled');
        questionCount++;
        scroll([], [], false, cursor);
        assert.equal(el.scrollTop, 1600, 'Submitting a new question follows that question');
        el.scrollTop = 1200;
        listeners.scroll();
        el.scrollHeight = 1800;
        scroll([], [], false, cursor);
        assert.equal(el.scrollTop, 1800, 'Readers at the bottom follow the new answer');
        el.scrollTop = 200;
        listeners.scroll();
        scroll([], [], false, {thread_id: 'B'});
        assert.equal(el.scrollTop, 1800, 'Opening a conversation shows its latest messages');
        el.scrollTop = 200;
        scroll([], [], true, {thread_id: 'C'});
        assert.equal(el.scrollTop, 200, 'Editing never forces scrolling');
    """.replace("BODY", body))


def test_status_visibility_does_not_remove_its_layout_slot():
    body = ast.literal_eval(callback_for("thinking-bar", "style").args[0])
    run_js("""
        const assert = require('node:assert/strict');
        const toggle = BODY;
        const idle = toggle(false), running = toggle(true);
        assert.equal(idle[0].display, running[0].display, 'Status must not resize the transcript');
        assert.equal(idle[0].visibility, 'hidden');
        assert.equal(running[0].visibility, 'visible');
        assert.equal(idle[1].display, 'inline-flex');
        assert.equal(running[2].display, 'inline-flex');
    """.replace("BODY", body))
