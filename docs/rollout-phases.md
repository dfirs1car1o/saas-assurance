# Phased Rollout Plan (With Backout + RV)

This document defines phased delivery, required configuration steps, release validation (RV), and rollback criteria.

## Rollout Principles
- One production change domain per phase.
- No phase promotion without passing RV gates.
- Every phase must have a tested rollback path.
- Every merged PR must update `CHANGELOG.md` under `[Unreleased]`.

## Phase 0: Foundation (Current)

### Goal
Stand up baseline infra + CI/CD + API scaffold.

### Configuration Steps
1. Configure GitHub OIDC variables:
   - `AZURE_CLIENT_ID`
   - `AZURE_TENANT_ID`
   - `AZURE_SUBSCRIPTION_ID`
2. Configure Terraform remote state variables:
   - `TF_STATE_RG`
   - `TF_STATE_SA`
   - `TF_STATE_CONTAINER`
   - `TF_STATE_KEY`
3. Create `infra/terraform/envs/dev.tfvars` from example.
4. Run plan in PR, apply via protected environment.

### RV Gate
- Terraform `validate` passes.
- Terraform plan completes with expected resource set.
- `/health` endpoint reachable on Container App after apply.

### Backout
- `terraform destroy -var-file=envs/dev.tfvars` for dev environment only.
- If partial deploy: revert merge commit, re-run apply from known-good commit.

## Phase 1: Secure Model + Secret Plumbing

### Goal
Move from stubs to real model providers with Key Vault-backed secrets.

### Configuration Steps
1. Add Key Vault secrets:
   - `OPENAI_API_KEY` (or Azure OpenAI credentials)
   - `GEMINI_API_KEY`
2. Add managed identity permissions for orchestrator to read only required secrets.
3. Add provider selection policy in orchestrator:
   - primary/fallback routing
   - timeout and retry constraints
4. Add APIM inbound auth policy (JWT validation).

### RV Gate
- Triage endpoint completes with primary provider in < defined SLA.
- Fallback provider path validated via forced-failure test.
- No secret values present in logs.

### Backout
- Feature-flag provider routing to stub mode.
- Rollback to prior image tag and re-apply infra/policies.

## Phase 2: Workflow + Queue Orchestration

### Goal
Implement asynchronous case workflow using Service Bus.

### Configuration Steps
1. Add queue consumer worker deployment.
2. Add workflow states:
   - `ingested`, `triaged`, `enriched`, `awaiting_approval`, `closed`
3. Add durable case store (Cosmos/SQL decision per environment).
4. Add correlation IDs for end-to-end tracing.
5. Add role-based model/tool policy enforcement from `config/`.

### RV Gate
- End-to-end case run succeeds from intake to summary.
- Dead-letter behavior verified on failed jobs.
- Traceability from API request to queue job to result confirmed.

### Backout
- Disable queue consumers (scale to zero).
- Route API to synchronous triage-only fallback.

## Phase 2B: Cloud MCP Gateway

### Goal
Replace local MCP runtime assumptions with cloud-hosted MCP services.

### Configuration Steps
1. Deploy `infra/terraform/cloud-mcp` stack.
2. Publish MCP tool services behind APIM.
3. Apply auth/policy/rate limits at APIM.
4. Enforce role-based allowlists in orchestrator via:
   - `config/role_model_policy.yaml`
   - `config/role_tool_policy.yaml`

### RV Gate
- MCP gateway reachable via APIM.
- Tool invocation audited with role and case correlation ID.
- Unauthorized tool calls rejected by policy.

### Backout
- Disable MCP routes in APIM.
- Fall back to core triage/report workflows while policy issues are remediated.

## Phase 3: Copilot Studio Integration

### Goal
Expose governed APIs/actions for Copilot Studio.

### Configuration Steps
1. Publish OpenAPI spec behind APIM.
2. Create Copilot Studio custom connector/actions.
3. Implement approval action for high-risk operations.
4. Add per-action RBAC and audit logging.

### RV Gate
- Copilot action invocation succeeds for read-only triage.
- Approval workflow enforced for restricted actions.
- Audit records captured for each action invocation.

### Backout
- Disable connector actions in Copilot Studio.
- Keep backend running for direct analyst-console/API usage.

## Phase 4A: SIFT Image Factory

### Goal
Build and version a hardened SIFT Ubuntu image pipeline for worker deployment.

### Configuration Steps
1. Deploy `infra/terraform/sift-image-factory` baseline resources.
2. Upload image build scripts:
   - `scripts/sift-install.sh`
   - `scripts/sift-hardening.sh`
3. Create Azure Image Builder template and publish version to Compute Gallery.
4. Approve image version after RV smoke tests.

### RV Gate
- Image build succeeds and version is published.
- SIFT install and hardening checks pass on launched VM.
- Image metadata (version/date/owner) recorded in release notes.

### Backout
- Mark failing image version as blocked.
- Revert worker config to previous known-good image version.

## Phase 4B: Malware Sandbox Isolation

### Goal
Add isolated execution plane for malware analysis tasks.

### Configuration Steps
1. Create dedicated subscription/resource group/VNet boundary.
2. Deploy ephemeral worker VM/VMSS pattern.
3. Restrict egress and prohibit direct corp network reachability.
4. Capture evidence artifacts to immutable container path.

### RV Gate
- One-sample-one-worker lifecycle verified (create/run/collect/destroy).
- Evidence integrity and provenance checks pass.
- No unauthorized egress in network telemetry.

### Backout
- Disable sandbox job dispatch.
- Keep triage-only and static enrichment active.

## Phase 5: Production Hardening

### Goal
Operational readiness for enterprise support model.

### Configuration Steps
1. Add SLO dashboards and alerting.
2. Add runbooks for incident response and provider outage failover.
3. Enforce branch protections and mandatory plan checks.
4. Tag release versions and lock rollback artifacts.

### RV Gate
- Load and resilience tests pass.
- Failover drill completed.
- Security review sign-off completed.

### Backout
- Roll back image + terraform module versions to last known-good release tag.

## Release Validation Checklist (Per Phase)
- [ ] `CHANGELOG.md` updated
- [ ] Terraform plan reviewed by second approver
- [ ] RV scripts/checks executed and attached to PR
- [ ] Rollback command(s) tested in dev
- [ ] Post-deploy smoke checks passed
