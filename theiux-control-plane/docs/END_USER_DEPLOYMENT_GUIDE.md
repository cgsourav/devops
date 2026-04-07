# End-user guide: deploying your app with Theiux

This document is for **developers and teams** who use the **Theiux control plane** (web app or API) to **deploy and manage Frappe applications** on infrastructure operated by your organization.

If you **run or install** the control plane itself (servers, Docker, `theiux` CLI, AWS), see **[Operator guide](./OPERATOR_GUIDE.md)** instead.

---

## What this product does for you

The control plane lets you:

1. **Register** an account and sign in.
2. **Create an “app”** — your Frappe custom app — by pointing at a **Git repository** and choosing a **runtime** and **plan**.
3. **Start a deployment** — the platform runs a real remote install on the operator’s Frappe/bench environment (via **`theiux deploy-site`**), not a simulation.
4. **Watch logs**, **see errors** (build, migration, or runtime), and **retry** a failed deployment when permitted.

Your site gets a **deterministic hostname** derived from the app name (for example, a pattern like **`<sanitized>.theiux.local`** — exact suffix depends on operator configuration). Use the **Sites** view in the UI or the API to see active sites.

---

## Before you start

- **Access**: URL of the web UI and (if you use the API directly) the **API base URL** your operator gave you.
- **Git repository**: Your Frappe app must live in a **Git** repo reachable over **HTTPS** or **SSH** from the **deployment environment** (the bench host that runs `bench get-app`). Confirm branch and tags with your operator if deploys fail on clone.
- **Credentials**: Your app’s **name** (used as a label for the site), **repo URL**, and a **runtime** / **version** chosen from what the platform allows (see your UI or **`GET /v1/plans`**).

---

## Using the web application

After you **sign in**, you land on **Dashboard**. The left navigation includes **Dashboard**, **Benches**, **Sites**, **Deployments**, **Deploy wizard**, **Marketplace**, **Billing**, **Team**, and **Settings**.

Typical daily workflow:

1. Pick an app template from **Marketplace**.
2. Open **Deploy wizard** to create and deploy.
3. Track progress in **Deployments** and the deployment log view.
4. Manage custom domains, SSL, backups, and restore from each **Site** page.
5. Check usage/plan status in **Billing** and manage collaborators in **Team**.

**Platform init** (Terraform / `theiux init`) is a separate **admin** screen (`/admin/theiux-init`), not where you register tenant apps.

### 1. Create an account

- Open the **Register** flow and sign up with your **email** and a **password** (minimum length is enforced by the API).
- **Sign in** to receive an **access token** (the UI stores this for you). For API-only workflows, use **`POST /v1/auth/login`** (OAuth2 password form) and send **`Authorization: Bearer <access_token>`** on subsequent requests.

### 2. Pick a plan and subscription

- Plans define **limits** (for example: active sites, deployments per day, concurrent jobs). Set or change your active plan from **Billing** and choose app-level plans in wizard step 3 for compatibility with existing deploy flows.

### 3. Create an app (Deploy Wizard)

Use the **Deploy Wizard** on the home page. **Step 1** asks for **app name** and **Git repo URL**. **Step 2** is **runtime** and version (must match operator **`ALLOWED_RUNTIME_VERSIONS`**). **Step 3** picks a **plan**. **Step 4** is review; **Deploy now** creates the app and starts the first deployment. **Step 5** shows **logs** and pipeline stages for the selected deployment.

**Example — [erp_lab](https://github.com/souravs72/erp_lab)** (Frappe lab app):

- Use **Use ERP Lab template** on step 1, or enter manually:
  - **Name**: `erp_lab` (should match the app folder name in the repo; the platform builds `frappe,<app>` for bench).
  - **Git URL**: `https://github.com/souravs72/erp_lab.git`
  - **Runtime**: **Python** **3.11** (or another version your operator allows).

When you finish the wizard, the **app** appears under **Your apps**. You can have multiple apps under one account.

### 4. Deploy

- For a **new** app, complete the wizard and click **Deploy now** — the UI moves to **step 5**, shows **pipeline stages** (for example queued → building → deploying → success or failed), and **live or polled logs**.
- Wait until the run **succeeds** or **fails**. Large deployments can take many minutes; your operator sets timeouts.
- On a newly provisioned host, the first deploy/get-app may take longer because the platform can automatically bootstrap missing host prerequisites before running the app lifecycle steps.

### 5. If something fails

- Read the **error summary** and **log lines** in the UI. Failures are classified when possible:
  - **`build_error`** — dependency or build steps (e.g. npm/pip).
  - **`migration_error`** — database migrations / schema.
  - **`runtime_error`** — everything else (timeouts, infrastructure, SSM, etc.).
- Use **Retry** when the platform offers it. Retries often create a **new deployment** record; follow the new ID in the UI.
- **Quota** — If you hit limits (sites, deployments per day), the API returns an error; upgrade plan or wait as your operator allows.

### 5a. Manage domains and backups

- Open **Sites** and click a site.
- In **Overview**, you can:
  - add custom domains,
  - verify a domain and activate SSL state,
  - create backups,
  - restore from a chosen backup snapshot.
- These actions typically require an **admin** or **owner** role.

### 6. Redeploy

- In the UI, open **Your apps** on the home page and click **Redeploy** next to an app. That calls **`POST /v1/deployments`** with `{ "app_id": "<the app id>" }`, selects the new deployment, and opens **step 5** logs (same as after **Deploy now**). You need a role that is allowed to create deployments (for example **owner** or **admin**, per operator policy).
- Deploying the **same app** again is supported: the remote pipeline is designed to **skip** work that already completed (for example, existing site or app source). You should still see logs for the new run.
- API-only: **`POST /v1/deployments`** with body `{ "app_id": "<uuid>" }` after you know the app id from **`GET /v1/apps`**.

---

## Using the HTTP API (optional)

Interactive documentation is usually available at **`GET /docs`** on the API host.

Typical flow:

1. **`POST /v1/auth/register`** or **`POST /v1/auth/login`**
2. **`GET /v1/plans`** — list plans
3. **`POST /v1/apps`** — create app (`name`, `git_repo_url`, `runtime`, `runtime_version`, `plan_id`)
4. **`POST /v1/deployments`** — body `{ "app_id": "<uuid>" }`
5. **`GET /v1/deployments/{id}/logs`** or **`/logs/structured`** — follow progress
6. **`POST /v1/deployments/{id}/retry`** — retry when failed (if allowed)

See **`backend/docs/API_CONTRACT.md`** for request/response shapes and error codes.

---

## Security practices

- Use a **strong, unique password**; **rotate** tokens if your operator suspects a leak.
- Prefer **HTTPS** in the browser; do not send tokens over untrusted networks.
- **Do not embed** long-lived tokens in public repositories or client-side code that ships to browsers beyond what the Next.js app already uses.

---

## When to contact your operator

Reach out to the team that hosts the control plane when:

- The UI or API is **unreachable** or **slow** consistently.
- **Every** deploy fails with **infrastructure** or **timeout** messages.
- You need **SSH** or **VPN** access to the bench host (usually not granted through this UI).
- You need **allowed runtimes** or **plans** updated.

---

## Related documents

- **[Operator guide](./OPERATOR_GUIDE.md)** — for people who deploy and maintain the platform.
- **`backend/docs/API_CONTRACT.md`** — full API contract.
