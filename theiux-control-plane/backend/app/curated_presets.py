"""Curated app definitions — keep in sync with frontend/lib/curatedAppPresets.ts."""

from __future__ import annotations

from typing import TypedDict


class CuratedAppFields(TypedDict):
    name: str
    git_repo_url: str
    runtime: str
    runtime_version: str
    label: str
    description: str


CURATED_APP_PRESETS: dict[str, CuratedAppFields] = {
    'frappe-framework': {
        'name': 'frappe',
        'git_repo_url': 'https://github.com/frappe/frappe',
        'runtime': 'python',
        'runtime_version': '3.11',
        'label': 'Frappe Framework',
        'description': 'Core Frappe framework for custom cloud-hosted applications',
    },
    'erpnext': {
        'name': 'erpnext',
        'git_repo_url': 'https://github.com/frappe/erpnext',
        'runtime': 'python',
        'runtime_version': '3.11',
        'label': 'ERPNext',
        'description': 'Open source ERP with accounting, inventory, and operations modules',
    },
    'hrms': {
        'name': 'hrms',
        'git_repo_url': 'https://github.com/frappe/hrms',
        'runtime': 'python',
        'runtime_version': '3.11',
        'label': 'Frappe HR',
        'description': 'HR and payroll management app built on Frappe',
    },
    'frappe-crm': {
        'name': 'crm',
        'git_repo_url': 'https://github.com/frappe/crm',
        'runtime': 'node',
        'runtime_version': '20',
        'label': 'Frappe CRM',
        'description': 'Modern customer relationship management app for sales pipelines',
    },
    'erp_lab': {
        'name': 'erp_lab',
        'git_repo_url': 'https://github.com/souravs72/erp_lab.git',
        'runtime': 'python',
        'runtime_version': '3.11',
        'label': 'ERP Lab',
        'description': 'Frappe hands-on lab app (tracks, tasks, verifiers)',
    },
}
