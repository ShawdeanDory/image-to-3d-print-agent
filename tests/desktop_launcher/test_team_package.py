"""便携包白名单/凭据拒绝；固定内容仅用于测试，不使用真实密钥。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('team_packager', Path(__file__).resolve().parents[2] / 'scripts/desktop_launcher/package_team.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BundleSecurityTests(unittest.TestCase):
    def check_file(self, name, data, reject):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
            if reject:
                with self.assertRaises(ValueError):
                    MODULE.scan_bundle(root)
            else:
                self.assertEqual(MODULE.scan_bundle(root), [file])

    def test_public_config_allowed(self):
        self.check_file('config/team-connection.json', b'{"host_key":"ssh-ed25519 PUBLIC"}', False)

    def test_private_key_rejected(self):
        self.check_file('config/innocent.txt', b'-----BEGIN OPENSSH PRIVATE KEY-----\n' + b'A' * 40, True)

    def test_api_token_rejected(self):
        self.check_file('frontend/dist/app.js', b'sk-' + b'A' * 32, True)

    def test_runtime_and_environment_rejected(self):
        self.check_file('runtime/ssh/config', b'public', True)
        self.check_file('frontend/.env', b'public', True)

    def test_original_personal_path_rejected(self):
        self.check_file('config/example.json', b'C:/Users/Lenovo/example', True)

    def test_existing_public_ssh_key_is_not_a_private_key(self):
        self.check_file('config/public.txt', b'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPUBLIC', False)

    def test_css_mask_identifier_is_not_an_api_key(self):
        self.check_file('frontend/dist/app.css', b'mask-' + b'border-' * 8, False)


if __name__ == '__main__':
    unittest.main()
