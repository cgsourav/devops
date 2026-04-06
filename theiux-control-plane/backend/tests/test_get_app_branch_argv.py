"""Unit tests: get-app-only CLI wiring includes optional branch."""

import unittest
from unittest.mock import patch

from app.theiux_cli import stream_theiux_get_app_only


class TestGetAppBranchArgv(unittest.TestCase):
    def test_without_branch(self) -> None:
        with patch('app.theiux_cli.stream_theiux_argv') as m:
            m.return_value = iter([])
            list(stream_theiux_get_app_only('https://github.com/org/repo.git'))
            args = m.call_args[0][0]
            self.assertEqual(args[0], 'get-app-only')
            self.assertIn('--git-repo', args)
            self.assertNotIn('--branch', args)

    def test_with_branch(self) -> None:
        with patch('app.theiux_cli.stream_theiux_argv') as m:
            m.return_value = iter([])
            list(stream_theiux_get_app_only('https://github.com/org/repo.git', 'version-15-hotfix'))
            args = m.call_args[0][0]
            self.assertIn('--branch', args)
            bi = args.index('--branch')
            self.assertEqual(args[bi + 1], 'version-15-hotfix')


if __name__ == '__main__':
    unittest.main()
