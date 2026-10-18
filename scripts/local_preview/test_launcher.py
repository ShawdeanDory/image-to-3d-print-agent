"""本机启动器的输入、真实子进程失败与超时回归，不调用模型。"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from launcher import new_run_dir, run_step, validate_image


class LauncherChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_png_and_literal_path(self):
        path = self.folder / "图片 & 有空格.png"
        Image.new("RGBA", (16, 12), (30, 60, 90, 200)).save(path)
        self.assertEqual(validate_image(path)["size"], [16, 12])
        log = self.folder / "命令 & 日志.txt"
        run_step([sys.executable, "-c", "import sys;print(sys.argv[1])", str(path)], log, 10)
        self.assertIn(str(path), log.read_text(encoding="utf-8"))

    def test_invalid_image_is_rejected(self):
        path = self.folder / "损坏.jpg"
        path.write_bytes(b"not an image")
        with self.assertRaises(ValueError):
            validate_image(path)

    def test_real_image_type_required(self):
        path = self.folder / "伪装.png"
        Image.new("RGB", (8, 8)).save(path, format="BMP")
        with self.assertRaises(ValueError):
            validate_image(path)

    def test_previous_results_are_kept(self):
        first = new_run_dir(self.folder)
        (first / "keep.txt").write_text("keep", encoding="utf-8")
        second = new_run_dir(self.folder)
        self.assertNotEqual(first, second)
        self.assertEqual((first / "keep.txt").read_text(), "keep")

    def test_nonzero_process_fails_and_keeps_log(self):
        log = self.folder / "failure.txt"
        with self.assertRaises(RuntimeError):
            run_step([sys.executable, "-c", "print('failed');raise SystemExit(7)"], log, 10)
        self.assertIn("failed", log.read_text(encoding="utf-8"))

    def test_timeout_is_not_success(self):
        with self.assertRaises(TimeoutError):
            run_step([sys.executable, "-c", "import time;time.sleep(5)"], self.folder / "timeout.txt", .1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
