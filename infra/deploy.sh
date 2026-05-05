#!/usr/bin/env bash
# deploy.sh — build, push to ECR, and update the ECS service
# Usage: ./infra/deploy.sh [region] [account_id]
# Example: ./infra/deploy.sh eu-west-2 123456789012

set -euo pipefail

REGION="${1:-eu-west-2}"
ACCOUNT_ID="${2:?Usage: deploy.sh <region> <account_id>}"
ECR_BASE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
CLUSTER="invictus-cluster"
SERVICE="invictus-service"

echo "==> Logging in to ECR"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ECR_BASE"

echo "==> Building backend"
docker build -t invictus-backend -f backend/Dockerfile .
docker tag invictus-backend:latest "${ECR_BASE}/invictus-backend:latest"
docker push "${ECR_BASE}/invictus-backend:latest"

echo "==> Building frontend"
docker build -t invictus-frontend ./frontend
docker tag invictus-frontend:latest "${ECR_BASE}/invictus-frontend:latest"
docker push "${ECR_BASE}/invictus-frontend:latest"

echo "==> Registering new task definition"
TASK_DEF=$(sed \
  -e "s/ACCOUNT_ID/${ACCOUNT_ID}/g" \
  -e "s/REGION/${REGION}/g" \
  infra/ecs-task-definition.json)

TASK_ARN=$(echo "$TASK_DEF" \
  | aws ecs register-task-definition \
      --cli-input-json file:///dev/stdin \
      --region "$REGION" \
      --query "taskDefinition.taskDefinitionArn" \
      --output text)

echo "==> Task definition registered: ${TASK_ARN}"

echo "==> Updating ECS service"
aws ecs update-service \
  --cluster "$CLUSTER" \
  --service "$SERVICE" \
  --task-definition "$TASK_ARN" \
  --region "$REGION" \
  --force-new-deployment \
  --output table

echo "==> Waiting for service to stabilise…"
aws ecs wait services-stable \
  --cluster "$CLUSTER" \
  --services "$SERVICE" \
  --region "$REGION"

echo "==> Deploy complete"