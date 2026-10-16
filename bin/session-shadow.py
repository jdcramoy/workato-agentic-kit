#!/usr/bin/env python3
"""session-shadow — real-time cross-session visibility for Josh's harness.

Tails the ACTIVE Claude session transcript (~/.claude/projects/*/<uuid>.jsonl,
appended live every turn) and maintains knowledge/now/josh-now.{json,md} so
any parallel session/agent starts knowing what Josh is working on RIGHT NOW
without a handoff file. Mechanical only: zero LLM tokens. A real focus shift
(new ticket set or top focus files, min 60 min between posts) posts one
gossip-bus line; liveness heartbeats stay per-run.

launchd: com.josh.session-shadow, StartInterval 60. Read-only observer:
never posts to Slack, never acts.
"""
import json
import os
import re
import sys
import glob
import time
from datetime import datetime, timezone

PROJECTS_GLOB = os.path.expanduser('~/.claude/projects/*/*.jsonl')
NOW_DIR = os.path.expanduser('~/.claude/knowledge/now')
STATE_PATH = os.path.join(NOW_DIR, 'shadow-state.json')
BUS_OUT = os.path.expanduser('~/.claude/knowledge/dreams/bus/session-shadow.jsonl')
HEARTBEAT = os.path.expanduser('~/.claude/knowledge/garden-reports/heartbeat.jsonl')
STALE_SESSION_SECONDS = 600      # newest file must have been touched in 10 min
FOCUS_MIN_INTERVAL = 3600        # min seconds between focus bus posts
DEADMAN_SECONDS = 1200           # quiet 20 min + no closeout = record the drop
CLOSEOUT_WINDOW = 900            # mission-control event counts as closeout
CHECKPOINT_MIN_TURNS = 50        # checkpoint journal starts at this many turns
CHECKPOINT_BUCKET = 50           # at most one checkpoint row per turn bucket
# Ledger paths are env-overridable so tests never touch the real ledgers.
DROPS_PATH = os.environ.get(
    'SESSION_SHADOW_DROPS_PATH',
    os.path.expanduser(
        '~/.claude/knowledge/mission-control/dropped-sessions.jsonl'))
MC_EVENTS = os.environ.get(
    'SESSION_SHADOW_MC_EVENTS',
    os.path.expanduser('~/.claude/knowledge/mission-control/events.jsonl'))
CHECKPOINTS_PATH = os.environ.get(
    'SESSION_SHADOW_CHECKPOINTS_PATH',
    os.path.expanduser(
        '~/.claude/knowledge/mission-control/checkpoints.jsonl'))
TICKET_RE = re.compile(r'\b((?:BSYS|BTSUP|HROPS|PSM|MCP|AAI|CT)-\d+)\b')
JOB_RE = re.compile(r'\bj-[A-Za-z0-9]{6,}(-[A-Za-z0-9]{4,})?-CD\b|\bj-[A-Za-z0-9-]{8,}\b')


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def log_err(where, err):
    """Fail-open diagnostics: the tailer loop must never die on its side-missions."""
    try:
        sys.stderr.write(f"[session-shadow] {where}: {err!r}\n")
    except Exception:
        pass


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH))
        except json.JSONDecodeError:
            pass
    return {'offsets': {}, 'topic_sig': None, 'last_ts': 0}


def save_state(s):
    json.dump(s, open(STATE_PATH, 'w'), indent=1)


def active_sessions():
    """Session files touched recently, newest first, with mtime."""
    out = []
    for f in glob.glob(PROJECTS_GLOB):
        base = os.path.basename(f)
        # only real session transcripts: <uuid>.jsonl
        if not re.match(r'^[0-9a-f-]{36}\.jsonl$', base):
            continue
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        if time.time() - mt <= STALE_SESSION_SECONDS:
            out.append((mt, f))
    out.sort(reverse=True)
    return out


def text_of_content(content):
    """Extract text + tool signals from a transcript message content field."""
    text, tools, files = [], [], []
    if isinstance(content, str):
        text.append(content)
        return text, tools, files
    if isinstance(content, list):
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get('type') == 'text' and c.get('text'):
                text.append(c['text'])
            elif c.get('type') == 'tool_use':
                name = c.get('name', '')
                inp = c.get('input') or {}
                sig = name
                for k in ('file_path', 'url', 'query', 'issueIdOrKey'):
                    if inp.get(k):
                        sig += f" {str(inp[k])[:80]}"
                        if k == 'file_path':
                            files.append(str(inp[k]))
                if name == 'Bash' and inp.get('command'):
                    cmd = str(inp['command'])
                    sig += ' ' + cmd[:80]
                    for fp in re.findall(r'/Users/YOUR-USER/[^\s"\';&|]+', cmd):
                        files.append(fp)
                tools.append(sig)
    return text, tools, files


def scan_new_lines(path, offset):
    """Read new bytes; return (new_offset, user_texts, tool_sigs, files,
    last_event_ts)."""
    size = os.path.getsize(path)
    if size <= offset:
        return offset, [], [], [], None
    new_user, new_tools, files, last_ts = [], [], [], None
    with open(path, 'r', errors='replace') as f:
        f.seek(offset)
        raw = f.read()
    new_offset = offset + len(raw.encode('utf-8', errors='replace'))
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get('isSidechain'):
            continue  # subagent noise; the shadow watches the MAIN thread
        ts = ev.get('timestamp')
        if ts:
            last_ts = ts
        etype = ev.get('type')
        msg = ev.get('message') or {}
        content = msg.get('content') if isinstance(msg, dict) else None
        if etype == 'user':
            t, _, _ = text_of_content(content)
            # tool RESULTS also come back as type:user; keep only real text
            real = [x for x in t if not x.startswith('<system-reminder')]
            if real:
                new_user.append(' '.join(real)[:400])
        elif etype == 'assistant':
            _, tools, fs = text_of_content(content)
            new_tools.extend(tools)
            files.extend(fs)
    return new_offset, new_user, new_tools, files, last_ts


def topic_signature(user_texts, files):
    m = ' '.join(user_texts)
    tickets = sorted(set(TICKET_RE.findall(m)))
    focus_files = sorted(set(f for f in files if '/knowledge/' not in f))[:4]
    return tickets, focus_files


def write_now(session_id, last_user, tool_sigs, tickets, focus_files,
              last_activity_iso):
    os.makedirs(NOW_DIR, exist_ok=True)
    jobs = sorted(set(JOB_RE.findall(' '.join(tool_sigs) + ' ' + last_user)))[:5]
    jobs = [j[0] if isinstance(j, tuple) else j for j in jobs]
    payload = {
        'updated_at': now_iso(),
        'session_id': session_id,
        'last_activity': last_activity_iso,
        'last_user_message': last_user[:300],
        'tickets': tickets,
        'focus_files': focus_files,
        'recent_jobs': jobs,
        'recent_tools': [t[:120] for t in tool_sigs[-6:]],
    }
    json.dump(payload, open(os.path.join(NOW_DIR, 'josh-now.json'), 'w'),
              indent=1)
    md = ['# Josh now (auto-updated by session-shadow)', '',
          f"Updated: {payload['updated_at']} | session {session_id[:8]} | "
          f"last activity {last_activity_iso}", '']
    if last_user:
        md.append(f"Last said: \"{last_user[:280]}\"")
        md.append('')
    if tickets:
        md.append(f"Tickets in play: {', '.join(tickets)}")
    if focus_files:
        md.append('Files in play:')
        for f in focus_files:
            md.append(f"- {f}")
    if jobs:
        md.append(f"Job IDs seen: {', '.join(jobs)}")
    if tool_sigs:
        md.append('')
        md.append('Latest tool activity:')
        for t in tool_sigs[-3:]:
            md.append(f"- {t[:140]}")
    open(os.path.join(NOW_DIR, 'josh-now.md'), 'w').write('\n'.join(md) + '\n')
    return payload


def bus_post(kind, note, refs):
    os.makedirs(os.path.dirname(BUS_OUT), exist_ok=True)
    line = json.dumps({'ts': now_iso(), 'agent': 'session-shadow',
                       'kind': kind, 'note': note, 'refs': refs})
    open(BUS_OUT, 'a').write(line + '\n')


def heartbeat():
    os.makedirs(os.path.dirname(HEARTBEAT), exist_ok=True)
    open(HEARTBEAT, 'a').write(
        json.dumps({'ts': now_iso(), 'job': 'session-shadow'}) + '\n')


def recovery_payload(path, max_prompts=3, prompt_chars=200, out_chars=500):
    """Extract a drop-recovery payload from a transcript in one pass:
    (assistant_turns, last N user prompts, touched files, last assistant text)."""
    turns = 0
    prompts = []
    files = []
    last_out = ''
    with open(path, errors='replace') as fh:
        for line in fh:
            if ('"assistant"' not in line and '"user"' not in line
                    and '"tool_use"' not in line):
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get('isSidechain'):
                continue
            etype = ev.get('type')
            msg = ev.get('message') or {}
            content = msg.get('content') if isinstance(msg, dict) else None
            text, _, fs = text_of_content(content)
            if etype == 'assistant':
                turns += 1
                files.extend(fs)
                for x in text:
                    if x.strip():
                        last_out = x
            elif etype == 'user':
                real = [x for x in text if not x.startswith('<system-reminder')]
                if real:
                    prompts.append(' '.join(real)[:prompt_chars])
    return turns, prompts[-max_prompts:], sorted(set(files))[:10], \
        last_out[:out_chars]


def absorb_note_exists(sid):
    """True if an absorb-note row for this session is already in MC_EVENTS
    (the auto-absorb is idempotent: one row per dropped session, ever)."""
    want = f'dropped-{sid[:12]}'
    try:
        with open(MC_EVENTS) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get('event') == 'absorb-note' \
                        and r.get('workstream') == want:
                    return True
    except FileNotFoundError:
        pass
    except Exception as e:
        log_err('absorb-exists-check', e)
    return False


def maybe_absorb_drop(sid, transcript_path):
    """(a) AUTO-ABSORB on drop: when the deadman sweep records a dropped
    session, append an absorb-note row to the mission-control ledger carrying
    the recovery payload. Idempotent per session; never raises."""
    try:
        if absorb_note_exists(sid):
            return
        turns, prompts, files, last_out = recovery_payload(transcript_path)
        what = (f"DROPPED SESSION auto-absorb (deadman): {turns} turns; "
                f"last prompts: {' | '.join(prompts) if prompts else 'none'}; "
                f"files: {', '.join(files[:5]) or 'none'}; "
                f"last output: {last_out}; "
                f"transcript: {transcript_path}")
        row = {
            'ts': now_iso(),
            'event': 'absorb-note',
            'workstream': f'dropped-{sid[:12]}',
            'project': 'agent-harness',
            'jira': '',
            'jira_title': '',
            'what': what,
            'why': 'deadman sweep recorded a dropped session; auto-absorb '
                   'preserves the recovery payload in the ledger',
            'end': '',
            'needs': 'resume or explicitly abandon this workstream',
            'state': 'in-flight',
            'by': 'deadman-sweep',
        }
        os.makedirs(os.path.dirname(MC_EVENTS), exist_ok=True)
        with open(MC_EVENTS, 'a') as fh:
            fh.write(json.dumps(row) + '\n')
    except Exception as e:
        log_err('auto-absorb', e)


def checkpoint_transcript(state, path):
    """(b) CHECKPOINT JOURNAL: for one transcript, if it has reached a new
    50-turn bucket (>= CHECKPOINT_MIN_TURNS), append a sparse checkpoint row
    with the recovery payload. Returns True if state was mutated."""
    base = os.path.basename(path)
    if not re.match(r'^[0-9a-f-]{36}\.jsonl$', base):
        return False
    sid = base[:-6]
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return False
    ck = state.setdefault('checkpoints', {})
    prev = ck.get(sid) or {}
    if prev.get('mtime') == mt:
        return False  # nothing appended since we last looked
    turns, prompts, files, _ = recovery_payload(path)
    ck[sid] = {'mtime': mt, 'bucket': prev.get('bucket', -1)}
    bucket = turns // CHECKPOINT_BUCKET
    if turns < CHECKPOINT_MIN_TURNS or bucket <= prev.get('bucket', -1):
        return False
    ck[sid]['bucket'] = bucket
    row = {'ts': now_iso(), 'session_id': sid, 'turns': turns,
           'last_prompt': prompts[-1] if prompts else '',
           'files_touched': files[:10]}
    os.makedirs(os.path.dirname(CHECKPOINTS_PATH), exist_ok=True)
    with open(CHECKPOINTS_PATH, 'a') as fh:
        fh.write(json.dumps(row) + '\n')
    return True


def checkpoint_sweep(state):
    """Checkpoint every transcript that crossed a new 50-turn bucket this
    cycle. Returns True if state changed (caller should save_state)."""
    changed = False
    seen = set()
    for f in glob.glob(PROJECTS_GLOB):
        base = os.path.basename(f)
        if not re.match(r'^[0-9a-f-]{36}\.jsonl$', base):
            continue
        seen.add(base[:-6])
        try:
            if checkpoint_transcript(state, f):
                changed = True
        except Exception as e:
            log_err('checkpoint', e)
    ck = state.get('checkpoints', {})
    for dead in [k for k in ck if k not in seen]:
        ck.pop(dead, None)
        changed = True
    return changed


def deadman_sweep(state):
    """Dead-man switch for hard-killed sessions (SessionEnd hook never fires on
    SIGKILL/crash): any tracked session quiet for DEADMAN_SECONDS whose work
    wasn't closed out gets recorded to dropped-sessions.jsonl — once per quiet
    period. Self-teaching: the watcher survives the death of the watched."""
    now = time.time()
    tracked = state.setdefault('deadman', {})

    # sweep quiet sessions (any transcript, not just the newest)
    for f in glob.glob(PROJECTS_GLOB):
        base = os.path.basename(f)
        if not re.match(r'^[0-9a-f-]{36}\.jsonl$', base):
            continue
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        quiet_for = now - mt
        sid = base[:-6]
        entry = tracked.get(sid)
        if quiet_for <= DEADMAN_SECONDS:
            tracked.pop(sid, None)  # alive again
            continue
        if entry and entry.get('recorded_for') == int(mt):
            continue  # already recorded for this quiet period
        if quiet_for > 172800:
            # 2026-10-13 fusion-build fix: a session quiet >48h is history, not
            # an actionable drop (the Oct 12/13 floods recorded 12-day-old
            # transcripts on every tailer restart). Mark tracked, write nothing.
            tracked[sid] = {'recorded_for': int(mt), 'turns': 0}
            continue
        # substantial? count turns + collect context cheaply
        turns, last_prompt, files = 0, '', []
        try:
            for l in open(f, errors='replace'):
                if '"assistant"' in l:
                    turns += 1
                elif '"user"' in l and not last_prompt:
                    pass
            with open(f, errors='replace') as fh:
                for l in fh:
                    if '"last-prompt"' in l:
                        try:
                            last_prompt = str(json.loads(l).get('prompt', ''))[:200]
                        except Exception:
                            pass
                    if '"tool_use"' in l and ('Edit' in l or 'Write' in l):
                        m = re.search(r'"file_path"\s*:\s*"([^"]+)"', l)
                        if m:
                            files.append(m.group(1))
        except Exception:
            continue
        if turns < 8:
            tracked[sid] = {'recorded_for': int(mt), 'turns': turns}
            continue  # trivial session; nothing to lose
        # closed out near its last activity?
        closed = False
        try:
            import datetime
            for l in open(MC_EVENTS):
                try:
                    r = json.loads(l)
                except Exception:
                    continue
                ts = str(r.get('ts') or r.get('recorded_at') or '')
                try:
                    t = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
                except Exception:
                    continue
                if mt - CLOSEOUT_WINDOW <= t <= mt + 60:
                    closed = True
                    break
        except FileNotFoundError:
            pass
        tracked[sid] = {'recorded_for': int(mt), 'turns': turns}
        if closed:
            continue
        if not last_prompt and not files:
            # 2026-10-13 fusion-build fix: fleet/headless jobs legitimately end
            # without closeouts and carry no absorbable state (no prompt, no
            # files) — recording them flooded the ledger 9.6k rows deep.
            continue
        rec = {'ts': now, 'session_id': sid[:12], 'ended': 'deadman: quiet '
               f'{int(quiet_for//60)}min, no closeout found', 'turns': turns,
               'last_prompt': last_prompt, 'files_touched': sorted(set(files))[:10],
               'note': 'session went quiet without closeout — absorb state from '
                       'transcript or shadow before continuing this work'}
        try:
            os.makedirs(os.path.dirname(DROPS_PATH), exist_ok=True)
            with open(DROPS_PATH, 'a') as fh:
                fh.write(json.dumps(rec) + '\n')
        except Exception:
            pass  # fail-open; the shadow never breaks on its side-mission
        try:
            maybe_absorb_drop(sid, f)
        except Exception as e:
            log_err('auto-absorb', e)


def build_fixture(path, n_assistant):
    """Selftest fixture: a synthetic main-thread transcript."""
    with open(path, 'w') as fh:
        for i in range(n_assistant):
            fh.write(json.dumps(
                {'type': 'user', 'message': {'role': 'user', 'content': [
                    {'type': 'text', 'text': f'fixture prompt {i}'}]}}) + '\n')
            content = [{'type': 'text',
                        'text': f'fixture assistant output {i}'}]
            if i == 7:
                content.append({'type': 'tool_use', 'name': 'Edit',
                                'input': {'file_path':
                                          '/tmp/fixture-touched/file.py'}})
            fh.write(json.dumps(
                {'type': 'assistant',
                 'message': {'role': 'assistant', 'content': content}}) + '\n')


def append_fixture(path, n_more):
    with open(path, 'a') as fh:
        for i in range(n_more):
            fh.write(json.dumps(
                {'type': 'user', 'message': {'role': 'user', 'content': [
                    {'type': 'text', 'text': f'fixture more prompt {i}'}]}})
                + '\n')
            fh.write(json.dumps(
                {'type': 'assistant', 'message': {'role': 'assistant',
                 'content': [{'type': 'text',
                              'text': f'fixture more output {i}'}]}}) + '\n')


def selftest():
    """--selftest: exercise absorb + checkpoint against a fixture transcript
    with TEMP ledger paths. Writes NOTHING to the real ledgers."""
    import tempfile
    global MC_EVENTS, CHECKPOINTS_PATH, DROPS_PATH
    old = (MC_EVENTS, CHECKPOINTS_PATH, DROPS_PATH)
    tmp = tempfile.mkdtemp(prefix='session-shadow-selftest-')
    results = []

    def check(name, ok, detail=''):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}: {name}"
              + (f" | {detail}" if detail else ''))

    try:
        fx = os.path.join(
            tmp, '00000000-0000-4000-8000-0000000000aa.jsonl')
        build_fixture(fx, 55)
        MC_EVENTS = os.path.join(tmp, 'events.jsonl')
        CHECKPOINTS_PATH = os.path.join(tmp, 'checkpoints.jsonl')
        DROPS_PATH = os.path.join(tmp, 'drops.jsonl')
        real_sizes = {p: (os.path.getsize(p) if os.path.exists(p) else None)
                      for p in old}

        # --- checkpoint journal ---
        state = {}
        checkpoint_transcript(state, fx)
        rows = [json.loads(l) for l in open(CHECKPOINTS_PATH)]
        check('checkpoint row lands at 55 turns',
              len(rows) == 1 and rows[0]['turns'] == 55, f"rows={rows}")
        check('checkpoint row keys exact',
              rows and set(rows[0]) == {'ts', 'session_id', 'turns',
                                        'last_prompt', 'files_touched'},
              str(sorted(rows[0])) if rows else 'no row')
        check('checkpoint files_touched carries tool_use file_path',
              rows and rows[0]['files_touched'] ==
              ['/tmp/fixture-touched/file.py'],
              str(rows[0]['files_touched']) if rows else '')
        checkpoint_transcript(state, fx)
        rows = [json.loads(l) for l in open(CHECKPOINTS_PATH)]
        check('no duplicate checkpoint on unchanged mtime', len(rows) == 1)
        append_fixture(fx, 5)  # 60 turns, still bucket 1
        checkpoint_transcript(state, fx)
        rows = [json.loads(l) for l in open(CHECKPOINTS_PATH)]
        check('same-bucket growth writes no new checkpoint row', len(rows) == 1)
        append_fixture(fx, 45)  # 105 turns -> bucket 2
        checkpoint_transcript(state, fx)
        rows = [json.loads(l) for l in open(CHECKPOINTS_PATH)]
        check('bucket crossing writes exactly one more row',
              len(rows) == 2 and rows[-1]['turns'] == 105,
              f"turns={rows[-1]['turns'] if rows else '?'}")

        # --- auto-absorb on drop (fresh fixture: deterministic payload) ---
        fx2 = os.path.join(
            tmp, '00000000-0000-4000-8000-0000000000bb.jsonl')
        build_fixture(fx2, 55)
        sid = 'abcdef123456-dead-beef-cafe-000000000000'
        maybe_absorb_drop(sid, fx2)
        ev = [json.loads(l) for l in open(MC_EVENTS)]
        real_keys = {'ts', 'event', 'workstream', 'project', 'jira',
                     'jira_title', 'what', 'why', 'end', 'needs', 'state',
                     'by'}
        check('absorb row lands on drop',
              len(ev) == 1 and ev[0]['event'] == 'absorb-note',
              f"rows={len(ev)}")
        check('absorb keys exactly mirror mission-control schema',
              ev and set(ev[0]) == real_keys, str(sorted(ev[0])))
        check('absorb what carries recovery payload',
              ev and 'auto-absorb (deadman): 55 turns' in ev[0]['what']
              and 'fixture prompt 54' in ev[0]['what']
              and '/tmp/fixture-touched/file.py' in ev[0]['what']
              and 'fixture assistant output 54' in ev[0]['what'])
        check('absorb workstream = dropped-<sid-short>',
              ev and ev[0]['workstream'] == f'dropped-{sid[:12]}')
        check('absorb row state/by fields',
              ev and ev[0]['state'] == 'in-flight' and ev[0]['by'] ==
              'deadman-sweep' and ev[0]['project'] == 'agent-harness')
        maybe_absorb_drop(sid, fx2)
        ev = [json.loads(l) for l in open(MC_EVENTS)]
        check('absorb idempotent (second drop appends nothing)', len(ev) == 1)

        # --- real ledgers untouched ---
        untouched = all(
            (os.path.getsize(p) if os.path.exists(p) else None) ==
            real_sizes[p] for p in old)
        check('real ledgers untouched during selftest', untouched)

        ok = all(results)
        print(f"SELFTEST: {'PASS' if ok else 'FAIL'} (fixture dir: {tmp})")
        return ok
    except Exception as e:
        import traceback
        print(f"SELFTEST: FAIL — exception {e!r}")
        traceback.print_exc()
        return False
    finally:
        MC_EVENTS, CHECKPOINTS_PATH, DROPS_PATH = old


def git_autocommit(state):
    """Revert-protection (2026-10-15, Josh: 'investigate and fix'): the
    2026-10-15 22:08Z knowledge-deposit commit wiped uncommitted worktree
    appends (runs.jsonl rows, sweep cursor, a memory file). This cycle
    auto-commits the knowledge tree at most every 10 minutes so any future
    history rewrite is recoverable via reflog instead of destructive.
    Purely additive: add -A + commit, NEVER reset/checkout/clean."""
    import subprocess
    now = time.time()
    last = state.get('last_autocommit', 0)
    if now - last < 600:
        return
    repo = os.path.expanduser('~/.claude/knowledge')
    try:
        if subprocess.run(['git', '-C', repo, 'rev-parse', '--is-inside-work-tree'],
                          capture_output=True).returncode != 0:
            return
        dirty = subprocess.run(['git', '-C', repo, 'status', '--porcelain'],
                               capture_output=True, text=True).stdout.strip()
        if not dirty:
            state['last_autocommit'] = now
            save_state(state)
            return
        subprocess.run(['git', '-C', repo, 'add', '-A'], capture_output=True)
        r = subprocess.run(['git', '-C', repo, 'commit', '-q', '-m',
                            'session-shadow auto-commit (revert-protection)'],
                           capture_output=True, text=True)
        if r.returncode == 0:
            log_err('git-autocommit', 'committed %d dirty paths' % len(dirty.splitlines()))
        state['last_autocommit'] = now
        save_state(state)
    except Exception as e:
        log_err('git-autocommit', e)


def main():
    if '--selftest' in sys.argv:
        sys.exit(0 if selftest() else 1)
    os.makedirs(NOW_DIR, exist_ok=True)
    state = load_state()
    deadman_sweep(state)
    try:
        if checkpoint_sweep(state):
            save_state(state)
    except Exception as e:
        log_err('checkpoint-sweep', e)
    git_autocommit(state)
    sessions = active_sessions()
    if not sessions:
        return  # nothing live; keep last known state
    mt, active = sessions[0]
    session_id = os.path.basename(active)[:-6]
    offset = state['offsets'].get(session_id, 0)
    new_offset, users, tools, files, last_ts = scan_new_lines(active, offset)

    if new_offset != offset:
        state['offsets'][session_id] = new_offset
        # prune offsets for old sessions (keep 3 newest)
        newest = {os.path.basename(f)[:-6] for _, f in sessions[:3]}
        state['offsets'] = {k: v for k, v in state['offsets'].items()
                            if k in newest}
    # full-file scan on first sight of an active session (bootstrap)
    if not users and offset == 0:
        return  # nothing new yet this poll
    last_user = users[-1] if users else state.get('last_user', '')
    all_tools = state.get('tool_buffer', []) + tools
    state['tool_buffer'] = all_tools[-18:]
    state['last_user'] = last_user if last_user else state.get('last_user', '')
    tickets, focus_files = topic_signature(
        [last_user] if last_user else [], files or state.get('last_files', []))
    if files:
        state['last_files'] = list(set(files + state.get('last_files', [])))[-8:]

    # Focus VALUE: ticket set + canonical top-2 of the ACCUMULATED focus-file
    # set. This-tick `files` churn on every active turn, so the gate must key
    # on the stable value, not the tick's new activity.
    focus_top = sorted(state.get('last_files', []))[:2]
    sig = '|'.join(tickets) + '#' + ','.join(focus_top)
    prev_sig = state.get('topic_sig')
    now_t = time.time()
    interval_ok = (now_t - state.get('last_focus_post_ts', 0)) >= \
        FOCUS_MIN_INTERVAL

    # Shift gate: a bus post happens only when the focus VALUE actually
    # changed AND the min-interval floor elapsed. A change inside a blocked
    # window is deferred, not dropped (topic_sig stays on the posted value).
    if sig != prev_sig and interval_ok:
        if prev_sig is not None:  # don't announce the shadow's own bootstrap
            bus_post('focus',
                     f"Josh's focus shifted: tickets {tickets or ['none']} — "
                     f"last said: {last_user[:140]}",
                     {'session': session_id, 'now': 'knowledge/now/josh-now.md'})
            state['last_focus_post_ts'] = now_t
        state['topic_sig'] = sig

    heartbeat()  # liveness stays per-run, independent of the focus gate
    save_state(state)
    write_now(session_id, state.get('last_user', ''), state.get('tool_buffer', []),
              tickets, state.get('last_files', [])[:4],
              last_ts or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))


if __name__ == '__main__':
    main()
