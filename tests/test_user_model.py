#!/usr/bin/env python3
"""Unit tests for knowledge/scripts/user-model.py.
Run from the kit root: python3 -m unittest discover -s tests -v
Each test loads the module fresh with USER_MODEL_DIR pointed at a temp store.
"""
import importlib.util
import json
import os
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "knowledge", "scripts", "user-model.py")


def load_jm(store_dir):
    os.environ["USER_MODEL_DIR"] = store_dir
    spec = importlib.util.spec_from_file_location("user_model", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def pref(rid, scope="global", tags=None, rule=None, status="active",
         confirmed="2026-10-23"):
    return {
        "id": rid,
        "statement": rule or ("rule " + rid),
        "normalized_rule": rule or ("rule " + rid),
        "origin": "stated",
        "status": status,
        "scope": scope,
        "tags": tags or [],
        "evidence": [{"source": "test", "ref": "test", "date": "2026-10-23"}],
        "created": "2026-10-23",
        "last_confirmed": confirmed,
        "supersedes": [],
        "contradicts": [],
    }


class UserModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jm = load_jm(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, rows):
        with open(os.path.join(self.tmp.name, name), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def brief(self, task, **kw):
        kw.setdefault("project", "workbench")
        kw.setdefault("use_demote", False)
        return self.jm.build_briefing(task, **kw)

    # -- classification ------------------------------------------------------
    def test_classify_task(self):
        jm = self.jm
        self.assertEqual(jm.classify_task("prepare the promotion manifest"), ["promote"])
        self.assertEqual(jm.classify_task("build a new recipe"), ["build"])
        self.assertEqual(jm.classify_task("draft a slack reply"), ["comms"])
        self.assertEqual(jm.classify_task("what time is it in Tokyo"), [])

    def test_classify_is_multi_type(self):
        # "post an update to the BSYS ticket" is comms AND triage; a
        # single-winner classifier would starve one side's rules.
        types = self.jm.classify_task("post an update to the BSYS ticket")
        self.assertIn("comms", types)
        self.assertIn("triage", types)

    def test_infer_project_from_git_dir(self):
        repo = os.path.join(self.tmp.name, "myrepo")
        os.makedirs(os.path.join(repo, ".git"))
        self.assertEqual(self.jm.infer_project(os.path.join(repo, "sub", "dir")), "myrepo")

    # -- eligibility and scoring ----------------------------------------------
    def test_scope_eligibility(self):
        jm = self.jm
        row = pref("pref-001", scope="project:a")
        self.assertIsNone(jm.row_eligible(row, "b", []))
        self.assertEqual(jm.row_eligible(row, "a", []), 100)
        row = pref("pref-002", scope="task:build")
        self.assertIsNone(jm.row_eligible(row, "a", ["docs"]))
        self.assertEqual(jm.row_eligible(row, "a", ["build"]), 60)
        # untyped prompt: task rows serve weakly, never outrank plain globals
        self.assertEqual(jm.row_eligible(row, "a", []), 20)

    def test_untyped_prompt_surfaces_task_row_with_tag_overlap(self):
        self.write("preferences.jsonl", [
            pref("pref-001", scope="global", tags=[]),
            pref("pref-002", scope="task:debug", tags=["vua", "flag"]),
        ])
        _, served, _ = self.brief("flip the vua flag")
        self.assertEqual(served[0], "pref-002")

    def test_scope_beats_tag_overlap(self):
        self.write("preferences.jsonl", [
            pref("pref-001", scope="global", tags=["manifest", "promote"]),
            pref("pref-002", scope="task:promote", tags=[]),
        ])
        _, served, _ = self.brief("prepare the promotion manifest")
        self.assertEqual(served[0], "pref-002")

    def test_tag_overlap_ranks_within_scope(self):
        self.write("preferences.jsonl", [
            pref("pref-001", tags=["slack"]),
            pref("pref-002", tags=["slack", "voice"]),
        ])
        _, served, _ = self.brief("slack voice check")
        self.assertEqual(served[:2], ["pref-002", "pref-001"])

    def test_violation_boost(self):
        self.write("preferences.jsonl", [
            pref("pref-001", tags=["hook", "mcp"]),
            pref("pref-002", tags=["hook", "mcp", "correction"]),
        ])
        _, served, _ = self.brief("hook mcp question")
        self.assertEqual(served[0], "pref-002")

    def test_demote_after_repeated_serves(self):
        self.write("preferences.jsonl", [
            pref("pref-001", tags=["alpha"]),
            pref("pref-002", tags=["alpha"]),
        ])
        os.makedirs(os.path.join(self.tmp.name, "briefings"), exist_ok=True)
        self.write("briefings/briefings.jsonl", [
            {"ts": "2026-10-2%dT00:00:00Z" % i, "session_id": "s%d" % i,
             "served_pref_ids": ["pref-001"], "served_prec_ids": [],
             "token_estimate": 100}
            for i in range(10)
        ])
        body, served, _ = self.jm.build_briefing(
            "alpha task", project="workbench", use_demote=True)
        self.assertEqual(served[0], "pref-002")  # pref-001 demoted by repetition

    def test_inactive_rows_never_serve(self):
        self.write("preferences.jsonl", [
            pref("pref-001", status="draft", tags=["alpha"]),
            pref("pref-002", status="superseded", tags=["alpha"]),
            pref("pref-003", status="active", tags=["alpha"]),
        ])
        _, served, _ = self.brief("alpha")
        self.assertEqual(served, ["pref-003"])

    # -- rendering -------------------------------------------------------------
    def test_token_cap_trims_items(self):
        rows = [pref("pref-%03d" % i, tags=["alpha"], rule=("word " * 120) + str(i))
                for i in range(20)]
        self.write("preferences.jsonl", rows)
        body, served, _ = self.brief("alpha")
        self.assertLessEqual(self.jm.est_tokens(body), 800)
        self.assertTrue(body.startswith("--- [user-model]"))
        self.assertTrue(body.endswith("---"))
        self.assertLess(len(served), 20)

    def test_empty_task_and_no_match(self):
        self.assertEqual(self.brief(""), ("", [], []))
        self.write("preferences.jsonl", [pref("pref-001", scope="project:other")])
        self.assertEqual(self.brief("hello"), ("", [], []))

    def test_malformed_rows_skipped(self):
        with open(os.path.join(self.tmp.name, "preferences.jsonl"), "w") as f:
            f.write('{"id":"pref-001","status":"active","scope":"global","tags":["alpha"]}\n')
            f.write("NOT JSON\n")
        body, served, _ = self.brief("alpha")
        self.assertEqual(served, ["pref-001"])

    def test_precedents_only_for_plan_build_review(self):
        self.write("preferences.jsonl", [pref("pref-001", tags=["alpha"])])
        self.write("precedents.jsonl", [{
            "id": "prec-001", "date": "2026-10-20", "situation": "s",
            "options": ["a", "b"], "chosen": "a", "reason": "r",
            "context_tags": ["alpha"], "evidence": [],
        }])
        _, _, precs = self.brief("plan the alpha work")
        self.assertEqual(precs, ["prec-001"])
        _, _, precs = self.brief("alpha comms slack message")
        self.assertEqual(precs, [])

    # -- lifecycle ---------------------------------------------------------------
    def test_next_id(self):
        self.write("preferences.jsonl", [pref("pref-007"), pref("pref-003")])
        self.assertEqual(self.jm.next_id(self.jm.PREFS, "pref"), "pref-008")

    def test_confirm_draft_to_active(self):
        self.write("drafts.jsonl", [pref("pref-001", status="draft")])
        self.write("preferences.jsonl", [pref("pref-009")])
        args = type("A", (), {"id": "pref-001"})
        self.jm.cmd_confirm(args)
        drafts = self.jm.load_rows(self.jm.DRAFTS)
        prefs = self.jm.load_rows(self.jm.PREFS)
        self.assertEqual(drafts, [])
        confirmed = [p for p in prefs if p["normalized_rule"] == "rule pref-001"]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0]["status"], "active")
        self.assertEqual(confirmed[0]["id"], "pref-010")  # canonical id re-issue

    def test_supersede_and_retract(self):
        self.write("preferences.jsonl", [pref("pref-001"), pref("pref-002")])
        self.jm.cmd_supersede(type("A", (), {"id": "pref-001", "by": "pref-002"}))
        rows = {r["id"]: r for r in self.jm.load_rows(self.jm.PREFS)}
        self.assertEqual(rows["pref-001"]["status"], "superseded")
        self.assertEqual(rows["pref-002"]["supersedes"], ["pref-001"])
        self.jm.cmd_retract(type("A", (), {"id": "pref-002"}))
        rows = {r["id"]: r for r in self.jm.load_rows(self.jm.PREFS)}
        self.assertEqual(rows["pref-002"]["status"], "retracted")

    # -- eval ---------------------------------------------------------------------
    def test_eval_recall(self):
        self.write("preferences.jsonl", [
            pref("pref-001", tags=["manifest", "promote"]),
            pref("pref-002", tags=["slack", "voice"]),
        ])
        os.makedirs(os.path.join(self.tmp.name, "eval"), exist_ok=True)
        self.write("eval/correction-episodes.jsonl", [
            {"episode_id": "ep1", "task_signal": "prepare the promotion manifest",
             "expected_pref_ids": ["pref-001"]},
            {"episode_id": "ep2", "task_signal": "draft a slack message",
             "expected_pref_ids": ["pref-002"]},
            {"episode_id": "ep3", "task_signal": "unrelated nothing",
             "expected_pref_ids": ["pref-001"]},
        ])
        self.assertEqual(self.jm.cmd_eval(type("A", (), {})), 0)

    # -- CLI end to end ------------------------------------------------------------
    def test_brief_logs_serving(self):
        self.write("preferences.jsonl", [pref("pref-001", tags=["alpha"])])
        rc = self.jm.cmd_brief(type("A", (), {
            "task": "alpha work", "project": "workbench", "cwd": "",
            "session_id": "testsession", "no_log": False, "no_demote": True}))
        self.assertEqual(rc, 0)
        logs = self.jm.load_rows(self.jm.BRIEF_LOG)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["served_pref_ids"], ["pref-001"])
        self.assertEqual(logs[0]["session_id"], "testsession")

    def test_brief_fails_open_on_missing_store(self):
        # No store files at all: brief must exit 0 and print nothing to stdout.
        rc = self.jm.cmd_brief(type("A", (), {
            "task": "anything", "project": None, "cwd": "",
            "session_id": "", "no_log": True, "no_demote": True}))
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
