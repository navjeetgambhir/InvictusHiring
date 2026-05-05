# AWS Infrastructure Setup — Invictus Hiring

Run these steps once. After setup, all deploys go through `deploy.sh`.

---

## Prerequisites

```bash
brew install awscli
aws configure          # set Access Key, Secret, region (e.g. eu-west-2), output json
```

Set your values:
```bash
REGION=eu-west-2
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

---

## 1. ECR Repositories

```bash
aws ecr create-repository --repository-name invictus-backend  --region $REGION
aws ecr create-repository --repository-name invictus-frontend --region $REGION
```

---

## 2. RDS PostgreSQL with pgvector

```bash
# Create a DB subnet group first (replace with your VPC subnet IDs)
aws rds create-db-subnet-group \
  --db-subnet-group-name invictus-db-subnet \
  --db-subnet-group-description "Invictus DB subnets" \
  --subnet-ids subnet-XXXXXXXX subnet-YYYYYYYY

# Create the RDS instance (pgvector is supported on PostgreSQL 15+)
aws rds create-db-instance \
  --db-instance-identifier invictus-db \
  --db-instance-class db.t4g.micro \
  --engine postgres \
  --engine-version 16.4 \
  --master-username hiring_user \
  --master-user-password YOUR_STRONG_PASSWORD \
  --allocated-storage 20 \
  --db-name hiring_db \
  --db-subnet-group-name invictus-db-subnet \
  --vpc-security-group-ids sg-XXXXXXXXX \
  --no-publicly-accessible \
  --backup-retention-period 7

# Wait for it to be available (~5 min)
aws rds wait db-instance-available --db-instance-identifier invictus-db

# Get the endpoint
aws rds describe-db-instances \
  --db-instance-identifier invictus-db \
  --query "DBInstances[0].Endpoint.Address" --output text
```

After the instance is up, connect and enable pgvector:
```sql
-- Connect via bastion or port-forward then:
CREATE EXTENSION IF NOT EXISTS vector;
```

Then run your migrations:
```bash
psql postgresql://hiring_user:PASSWORD@RDS_ENDPOINT:5432/hiring_db \
  -f backend/migrations/001_init.sql
psql postgresql://hiring_user:PASSWORD@RDS_ENDPOINT:5432/hiring_db \
  -f backend/migrations/002_candidate_cv_screening.sql
psql postgresql://hiring_user:PASSWORD@RDS_ENDPOINT:5432/hiring_db \
  -f backend/migrations/003_prompt_versions.sql
psql postgresql://hiring_user:PASSWORD@RDS_ENDPOINT:5432/hiring_db \
  -f backend/migrations/004_agent_runs.sql
```

---

## 3. Secrets Manager

Store all sensitive env vars — the ECS task reads these at runtime.

```bash
aws secretsmanager create-secret --name invictus/openai_api_key \
  --secret-string "sk-..."  --region $REGION

aws secretsmanager create-secret --name invictus/database_url \
  --secret-string "postgresql+asyncpg://hiring_user:PASSWORD@RDS_ENDPOINT:5432/hiring_db?ssl=require" \
  --region $REGION

aws secretsmanager create-secret --name invictus/encryption_key \
  --secret-string "YOUR_FERNET_KEY"  --region $REGION

aws secretsmanager create-secret --name invictus/jwt_secret_key \
  --secret-string "YOUR_JWT_SECRET"  --region $REGION
```

---

## 4. EFS (for CV uploads)

```bash
EFS_ID=$(aws efs create-file-system \
  --performance-mode generalPurpose \
  --region $REGION \
  --query "FileSystemId" --output text)

echo "EFS ID: $EFS_ID"   # paste into ecs-task-definition.json → fileSystemId

# Create a mount target in each AZ your Fargate tasks run in
aws efs create-mount-target \
  --file-system-id $EFS_ID \
  --subnet-id subnet-XXXXXXXX \
  --security-groups sg-XXXXXXXXX
```

---

## 5. IAM Roles

### ECS Task Execution Role (pull images, read secrets)
```bash
aws iam create-role --role-name ecsTaskExecutionRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

aws iam attach-role-policy --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Allow reading secrets
aws iam attach-role-policy --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/SecretsManagerReadWrite
```

### Task Role (app permissions — EFS, CloudWatch)
```bash
aws iam create-role --role-name invictusTaskRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

aws iam attach-role-policy --role-name invictusTaskRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonElasticFileSystemClientReadWriteAccess
```

---

## 6. CloudWatch Log Groups

```bash
aws logs create-log-group --log-group-name /ecs/invictus-backend  --region $REGION
aws logs create-log-group --log-group-name /ecs/invictus-frontend --region $REGION
```

---

## 7. ECS Cluster + Service

```bash
# Cluster
aws ecs create-cluster --cluster-name invictus-cluster --region $REGION

# Application Load Balancer (create via console or CLI — routes :80 → frontend container)
# Note the ALB security group ID and target group ARNs

# Update ecs-task-definition.json — replace all placeholder values:
#   ACCOUNT_ID, REGION, fs-XXXXXXXXX (EFS), YOUR_DOMAIN

# First deploy
./infra/deploy.sh $REGION $ACCOUNT_ID

# Create the service (first time only)
aws ecs create-service \
  --cluster invictus-cluster \
  --service-name invictus-service \
  --task-definition invictus-hiring \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-XXXXXXXX],securityGroups=[sg-XXXXXXXXX],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:...,containerName=frontend,containerPort=80" \
  --region $REGION
```

---

## 8. Update ecs-task-definition.json placeholders

Open `infra/ecs-task-definition.json` and replace:

| Placeholder | Value |
|---|---|
| `ACCOUNT_ID` | Your AWS account ID (12 digits) |
| `REGION` | e.g. `eu-west-2` |
| `fs-XXXXXXXXX` | Your EFS file system ID from step 4 |
| `YOUR_DOMAIN` | Your ALB DNS name or custom domain |

---

## Ongoing deploys

```bash
./infra/deploy.sh eu-west-2 YOUR_ACCOUNT_ID
```

This builds both images, pushes to ECR, registers a new task definition, and triggers a rolling update with zero downtime.