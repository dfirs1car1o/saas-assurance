# API Credential Setup

This guide walks through obtaining the credentials required for Salesforce and Workday assessments.

---

## Salesforce

Two authentication methods are supported. **JWT Bearer** is preferred for CI/CD and production use.

### Method 1 — JWT Bearer (Preferred)

JWT Bearer uses a certificate/private-key pair instead of passwords. No session tokens expire mid-run.

#### Step 1 — Generate an RSA key pair

```bash
openssl genrsa -out ~/salesforce_jwt_private.pem 2048
openssl req -new -x509 -key ~/salesforce_jwt_private.pem \
  -out salesforce_jwt_cert.crt -days 730 \
  -subj "/CN=saas-assurance-agent"
chmod 600 ~/salesforce_jwt_private.pem
```

Keep `salesforce_jwt_private.pem` **outside the repo** (never commit it). The `.crt` is public and safe to share.

#### Step 2 — Create an External Client App in Salesforce

1. **Setup → External Client Apps → New External Client App**
2. Fill in:
   - **App Name / Label:** `saas-assurance-agent`
   - **Contact Email:** your email
   - **Enable OAuth Settings:** ✅
   - **Callback URL:** `https://login.salesforce.com/services/oauth2/callback`
   - **Selected OAuth Scopes:** `api`, `refresh_token`, `offline_access`
3. **Use digital signatures:** ✅ — upload `salesforce_jwt_cert.crt`
4. Save → copy the **Consumer Key**

#### Step 3 — Pre-authorize the connected app

1. Go to **Setup → Connected Apps → Manage** → find your app
2. Set **Permitted Users:** _Admin approved users are pre-authorized_
3. Under **Profiles / Permission Sets**, add the profile of the user you will authenticate as

#### Step 4 — `.env` configuration

```bash
SF_AUTH_METHOD=jwt
SF_CONSUMER_KEY=3MVG9...        # from Step 2
SF_PRIVATE_KEY_PATH=~/salesforce_jwt_private.pem
SF_USERNAME=your@email.salesforce.com
SF_DOMAIN=login                 # use "test" for sandboxes
```

---

### Required Salesforce Permissions

The user account used by the agent needs **read-only** access:

| Permission | Why |
|---|---|
| View Setup and Configuration | SOQL on SecuritySettings, RemoteProxy, NetworkAccess |
| API Enabled | All REST API calls |
| View All Data | EventLogFile query |
| Modify All Data | **Not required — do not grant** |

A custom **Permission Set** is recommended over a full Admin profile:

1. Setup → Permission Sets → New
2. Name: `SaasPostureReadOnly`
3. Enable: **API Enabled**, **View Setup and Configuration**, **View All Data**
4. Assign to the service account used in `.env`

---

## Workday

Workday uses OAuth 2.0 Client Credentials flow. All credentials come from a Workday Integration System User (ISU).

### Step 1 — Create an Integration System User

1. **Workday search bar → "Create Integration System User"**
2. Fill in:
   - **User Name:** `saas-assurance-agent`
   - **Password:** strong random password
   - **Do Not Allow UI Sessions:** ✅ (security best practice)
3. Note the **User Name** — this is your service account

### Step 2 — Create an Integration System Security Group

1. **Search → "Create Security Group"**
2. Type: **Integration System Security Group (Unconstrained)**
3. Name: `SaaS Posture Agent`
4. Add your ISU from Step 1

### Step 3 — Grant domain security policies

Activate these domain security policies for the group (Setup → Maintain Permission for Security Group):

| Domain | Permission |
|---|---|
| Worker Data: All Positions | View |
| Staffing | View |
| Security Configuration | View |
| System Auditing | View |
| Integration Build | View |

After adding, run **Activate Pending Security Policy Changes** (required by Workday).

### Step 4 — Create an API Client (OAuth 2.0)

1. **Search → "Register API Client for Integrations"**
2. Fill in:
   - **Client Name:** `saas-assurance-agent`
   - **Client Grant Type:** Client Credentials
   - **Access Token Type:** Bearer
   - **Token Expiration (seconds):** `3600`
3. Under **Scope (Functional Areas)**: add the domains from Step 3
4. Save — copy the **Client ID** and **Client Secret** (shown once)

### Step 5 — Get the Token URL

1. **Search → "View API Clients"** → find your client
2. The token URL follows this pattern:
   ```
   https://<tenant>.workday.com/ccx/oauth2/<tenant>/token
   ```
   Where `<tenant>` is your Workday tenant ID (visible in your Workday URL).

### Step 6 — `.env` configuration

```bash
WD_TENANT=your-tenant-id
WD_CLIENT_ID=abc123...          # from Step 4
WD_CLIENT_SECRET=xyz789...      # from Step 4 (shown once — store securely)
WD_TOKEN_URL=https://your-tenant.workday.com/ccx/oauth2/your-tenant/token
WD_BASE_URL=https://your-tenant.workday.com/ccx/api
```

> **Client Secret storage:** Never commit `WD_CLIENT_SECRET` to git. Use a secrets manager (AWS Secrets Manager, Azure Key Vault, GitHub Actions Secrets) for CI/CD environments. The `.env` approach is for local development only.

---

## OpenAI API Key

The orchestration harness uses the OpenAI API for all LLM calls.

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create a new secret key — name it `saas-assurance-agent`
3. Copy immediately (shown once)

```bash
OPENAI_API_KEY=sk-...
```

For Azure OpenAI (FedRAMP / IL5 environments):

```bash
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-02-01
LLM_MODEL_ORCHESTRATOR=gpt-5.3-chat-latest   # or your deployment name
```

---

## Verify Your Setup

```bash
# Verify all required env vars are present
python3 scripts/validate_env.py --json

# Test Salesforce connection (dry-run — no data written)
sfdc-connect collect --scope auth --out /tmp/sfdc_test.json

# Test Workday connection
python3 -m skills.workday_connect.workday_connect collect --scope all --out /tmp/wd_test.json

# Full pipeline dry-run (no live org needed)
agent-loop run --dry-run --env dev --org test-org
```

---

## Secrets Rotation

| Credential | Rotation trigger | Action |
|---|---|---|
| Salesforce Security Token | SF password change | Reset via Setup → My Personal Information |
| JWT private key | Annual or on compromise | Regenerate key pair, re-upload `.crt` to External Client App |
| Workday Client Secret | Annual or on compromise | Re-register API Client, update `.env` / secrets manager |
| OpenAI API key | On compromise or quarterly | Rotate at platform.openai.com, update secrets manager |
