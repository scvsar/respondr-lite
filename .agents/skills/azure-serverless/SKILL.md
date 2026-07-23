---
name: azure-serverless
description: Use when changing Bicep, Container Apps, Azure Functions, queues, Table Storage, scaling, Docker, GitHub deployment workflows, or cloud configuration.
---

# Azure Serverless

## When to Use

- Edit `infra\`, `deployment\`, Docker files, or deployment workflows.
- Change Container App scaling or health probes.
- Change Function, queue, Table Storage, identity, ingress, or RBAC settings.
- Diagnose cold starts or scale-from-zero behavior.

## Rules

1. Keep Bicep as the source for managed resources.
2. Keep preproduction and production separate.
3. Prefer managed identity and GitHub OIDC.
4. Preserve scale-to-zero unless the user accepts the cost.
5. Review queue polling, KEDA rules, replicas, and probes together.
6. Keep secret values out of commands, logs, outputs, and state artifacts.
7. Keep scripts idempotent when practical.
8. Use immutable image tags for production deployment.

## Workflow

1. Identify the affected environment and resource boundary.
2. Review identity, network, secret, and cost impact.
3. Update infrastructure and deployment adapters together.
4. Validate syntax.
5. Use a what-if operation before an authorized deployment.
6. Record rollback and migration requirements.

Never change live Azure resources without explicit authorization.
