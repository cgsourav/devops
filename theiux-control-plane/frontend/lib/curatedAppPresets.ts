/** Quick-fill values for the Deploy Wizard (must match operator ALLOWED_RUNTIME_VERSIONS). */

export type CuratedAppPreset = {
  id: string
  label: string
  description: string
  name: string
  git_repo_url: string
  runtime: string
  runtime_version: string
}

export const CURATED_APP_PRESETS: CuratedAppPreset[] = [
  {
    id: 'frappe-framework',
    label: 'Frappe Framework',
    description: 'Core Frappe framework for custom cloud-hosted applications',
    name: 'frappe',
    git_repo_url: 'https://github.com/frappe/frappe',
    runtime: 'python',
    runtime_version: '3.11',
  },
  {
    id: 'erpnext',
    label: 'ERPNext',
    description: 'Open source ERP with accounting, inventory, and operations modules',
    name: 'erpnext',
    git_repo_url: 'https://github.com/frappe/erpnext',
    runtime: 'python',
    runtime_version: '3.11',
  },
  {
    id: 'hrms',
    label: 'Frappe HR',
    description: 'HR and payroll management app built on Frappe',
    name: 'hrms',
    git_repo_url: 'https://github.com/frappe/hrms',
    runtime: 'python',
    runtime_version: '3.11',
  },
  {
    id: 'frappe-crm',
    label: 'Frappe CRM',
    description: 'Modern customer relationship management app for sales pipelines',
    name: 'crm',
    git_repo_url: 'https://github.com/frappe/crm',
    runtime: 'node',
    runtime_version: '20',
  },
  {
    id: 'erp_lab',
    label: 'ERP Lab',
    description: 'Frappe hands-on lab app (tracks, tasks, verifiers)',
    name: 'erp_lab',
    git_repo_url: 'https://github.com/souravs72/erp_lab.git',
    runtime: 'python',
    runtime_version: '3.11',
  },
]
