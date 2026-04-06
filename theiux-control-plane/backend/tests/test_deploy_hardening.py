"""Unit tests for deployment hardening (idempotency, retries, SSM exit codes)."""

import unittest

from app.jobs import DEPLOYMENT_TRANSITIONS, _deployment_error_text
from app.theiux_cli import TheiuxDeployError, classify_failure_from_exit_and_output


class TestDeploymentTransitions(unittest.TestCase):
    def test_failed_to_deploying_for_rq_retry(self) -> None:
        self.assertIn('deploying', DEPLOYMENT_TRANSITIONS['failed'])

    def test_failed_still_allows_rollback(self) -> None:
        self.assertIn('rollback', DEPLOYMENT_TRANSITIONS['failed'])


class TestDeploymentErrorText(unittest.TestCase):
    def test_combined_output_not_truncated_in_persisted_text(self) -> None:
        big = 'LINE\n' * 5000
        exc = TheiuxDeployError(
            'theiux deploy-site failed (exit 1)',
            exit_code=1,
            category='build_error',
            combined_output=big,
        )
        text = _deployment_error_text(exc)
        self.assertIn('LINE', text)
        self.assertGreater(len(text), len(big) // 2)


class TestClassifyExit(unittest.TestCase):
    def test_ssm_timeout_exit_124(self) -> None:
        self.assertEqual(classify_failure_from_exit_and_output(124, ''), 'runtime_error')

    def test_heuristic_when_non_timeout(self) -> None:
        self.assertEqual(
            classify_failure_from_exit_and_output(1, 'npm ERR! build failed'),
            'build_error',
        )


if __name__ == '__main__':
    unittest.main()
