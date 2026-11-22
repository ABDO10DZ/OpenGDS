import tempfile
import unittest
from pathlib import Path
from project_review import review_file

class ProjectReviewTests(unittest.TestCase):
    def test_flags_dynamic_execution_shell_and_todo(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root/"danger.py"
            source.write_text("eval(user_input)\nsubprocess.run(cmd, shell=True)\n# TODO later\n",encoding="utf-8")
            result=review_file(root,"danger.py")
            self.assertEqual(result["counts"]["high"],2)
            self.assertEqual(result["counts"]["low"],1)
            self.assertEqual([row["line"] for row in result["findings"]],[1,2,3])

    def test_rejects_outside_and_sensitive_file(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as other:
            root=Path(td); outside=Path(other)/"x.py";outside.write_text("eval(x)",encoding="utf-8")
            self.assertIn("error",review_file(root,str(outside)))
            (root/".env").write_text("password",encoding="utf-8")
            self.assertIn("error",review_file(root,".env"))

if __name__=="__main__": unittest.main()
