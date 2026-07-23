# Infrastructure and Deployment Instructions

Apply these rules to `infra\`, `deployment\`, Docker files, and workflows.

## Rules

- Keep Bicep as the source for managed Azure resources.
- Keep preproduction and production configuration separate.
- Prefer managed identity and GitHub OIDC.
- Preserve queue-based scale-to-zero behavior.
- Review scaling, polling, replicas, and health probes together.
- Keep scripts idempotent when practical.
- Never print deployment secrets or connection strings.
- Do not deploy without explicit authorization.
- Use a safe what-if operation before an authorized deployment.
- Pin production image tags to an immutable build identifier.

Treat auth, retention, ingress, role, and resource name changes as high risk.
