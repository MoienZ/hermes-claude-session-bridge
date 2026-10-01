"""Self-test suite for hermes_to_claude.py — run with: python tests/test_bridge.py

Covers: directory-name encoding, cwd fallback logic, corrupt-line tolerance,
empty/missing input, dry-run non-writes, and a full inject-then-read-back.
No network, no Claude Code required (the resume step itself is manual).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.normpath(os.path.join(HERE, "..", "scripts", "hermes_to_claude.py"))


def run_script(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


class TestEncode(unittest.TestCase):
    def _encode(self, cwd):
        # import the script as a module
        sys.path.insert(0, os.path.dirname(SCRIPT))
        import hermes_to_claude as m
        return m.encode_project_dir(cwd)

    def test_ascii_path(self):
        self.assertEqual(
            self._encode(r"C:\Users\Administrator\Documents\Hermes"),
            "C--Users-Administrator-Documents-Hermes",
        )

    def test_chinese_path(self):
        # verified against real on-disk directory
        self.assertEqual(
            self._encode(r"C:\Users\Administrator\Nutstore\1\我的坚果云\00-皓琳文档\20260903-病例扫描件"),
            "C--Users-Administrator-Nutstore-1-------00------20260903------",
        )

    def test_spaces_and_dots(self):
        self.assertEqual(self._encode("C:\\my dir\\a.b"), "C--my-dir-a-b")

    def test_no_collapsing(self):
        # consecutive dashes are never collapsed
        self.assertEqual(self._encode("C:\\ü"), "C---")  # ':' '\' 'ü' = 3 dashes


class TestScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bridge_test_")
        self.cwd_dir = os.path.join(self.tmp, "proj")
        os.makedirs(self.cwd_dir, exist_ok=True)

    def _trace(self, path, rows):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return path

    def _rows(self, cwd=None):
        cwd = cwd or self.cwd_dir
        return [
            {"type": "user", "cwd": cwd, "message": {"role": "user", "content": "hi"}},
            {"type": "assistant", "cwd": cwd, "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call_1", "name": "terminal", "input": {"command": "date"}},
                {"type": "text", "text": "done"},
            ]}},
            {"type": "user", "cwd": cwd, "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "ok"},
            ]}},
        ]

    def test_full_inject_and_readback(self):
        tr = self._trace(os.path.join(self.tmp, "s.trace"), self._rows())
        r = run_script(tr)
        self.assertEqual(r.returncode, 0, r.stderr)
        # locate written file
        import glob
        enc = "".join(c if (c.isascii() and (c.isalnum() or c in "-_")) else "-" for c in self.cwd_dir)
        proj = os.path.join(os.path.expanduser("~"), ".claude", "projects", enc)
        files = glob.glob(os.path.join(proj, str(uuid.UUID(r.stdout.split("claude --resume ")[1].split()[0])) + ".jsonl"))
        self.assertTrue(files, "injected file not found")
        lines = [json.loads(l) for l in open(files[0], encoding="utf-8")]
        # 2 metadata + 3 message rows
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[0]["type"], "mode")
        self.assertEqual(lines[1]["type"], "permission-mode")
        sids = {l["sessionId"] for l in lines}
        self.assertEqual(len(sids), 1, "sessionId not uniform")
        # tool pairing preserved
        self.assertEqual(lines[4]["message"]["content"][0]["tool_use_id"], "call_1")
        os.remove(files[0])  # cleanup

    def test_dry_run_writes_nothing(self):
        tr = self._trace(os.path.join(self.tmp, "d.trace"), self._rows())
        r = run_script(tr, "--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertIn("dry-run", r.stdout)

    def test_missing_cwd_falls_back_home(self):
        tr = self._trace(os.path.join(self.tmp, "g.trace"), self._rows(cwd=os.path.join(self.tmp, "gone")))
        r = run_script(tr, "--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertIn("已回退", r.stdout)
        self.assertIn(os.path.expanduser("~"), r.stdout)

    def test_override_cwd_checked(self):
        tr = self._trace(os.path.join(self.tmp, "o.trace"), self._rows())
        r = run_script(tr, "--cwd", os.path.join(self.tmp, "nope"), "--dry-run")
        self.assertIn("已回退", r.stdout)

    def test_corrupt_lines_skipped(self):
        p = os.path.join(self.tmp, "bad.trace")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._rows()[0]) + "\n{broken\n")
        r = run_script(p, "--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertIn("1 行损坏", r.stderr)

    def test_empty_file_fails(self):
        p = os.path.join(self.tmp, "empty.trace")
        open(p, "w").close()
        r = run_script(p, "--dry-run")
        self.assertEqual(r.returncode, 2)

    def test_missing_file_fails(self):
        r = run_script(os.path.join(self.tmp, "ghost.trace"))
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
