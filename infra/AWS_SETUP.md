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
  -f backend/migrations/003_interview_scheduling.sql
psql postgresql://hiring_user:PASSWORD@RDS_ENDPOINT:5432/hiring_db \
  -f backend/migrations/004_agent_runs.sql
psql postgresql://hiring_user:PASSWORD@RDS_ENDPOINT:5432/hiring_db \
  -f backend/migrations/005_ml_outcome_fields.sql
psql postgresql://hiring_user:PASSWORD@RDS_ENDPOINT:5432/hiring_db \
  -f backend/migrations/006_cover_letter_file.sql
psql postgresql://hiring_user:PASSWORD@RDS_ENDPOINT:5432/hiring_db \
  -f backend/migrations/007_job_expiry.sql
```

---

## 3. ElastiCache (Redis)

Used for chat history caching and active session persistence. The app fails silently if Redis is unavailable (falls back to Postgres), but ElastiCache is strongly recommended for production.

```bash
# Create a subnet group (use the same subnets as your Fargate tasks)
aws elasticache create-cache-subnet-group \
  --cache-subnet-group-name invictus-redis-subnet \
  --cache-subnet-group-description "Invictus Redis subnets" \
  --subnet-ids subnet-XXXXXXXX subnet-YYYYYYYY \
  --region $REGION

# Create a single-node Redis cluster (t4g.micro is sufficient)
aws elasticache create-cache-cluster \
  --cache-cluster-id invictus-redis \
  --cache-node-type cache.t4g.micro \
  --engine redis \
  --engine-version 7.0 \
  --num-cache-nodes 1 \
  --cache-subnet-group-name invictus-redis-subnet \
  --security-group-ids sg-XXXXXXXXX \
  --region $REGION

# Wait for it to be available (~3 min)
aws elasticache wait cache-cluster-available --cache-cluster-id invictus-redis --region $REGION

# Get the endpoint
aws elasticache describe-cache-clusters \
  --cache-cluster-id invictus-redis \
  --show-cache-node-info \
  --query "CacheClusters[0].CacheNodes[0].Endpoint.Address" --output text
```

Set the Redis URL as a secret (see step 4):
```
REDIS_URL=redis://ELASTICACHE_ENDPOINT:6379/0
```

---

## 4. Amazon SES (SMTP)

Replaces Mailhog for sending interview invitations and application confirmations.

```bash
# Verify your sending domain (replace with your actual domain)
aws ses verify-domain-identity --domain invictushiring.co --region $REGION

# Follow the DNS TXT record instructions returned above, then check verification:
aws ses get-domain-dkim-attributes --domains invictushiring.co --region $REGION

# Create an IAM user for SMTP credentials
aws iam create-user --user-name invictus-ses-smtp

aws iam attach-user-policy --user-name invictus-ses-smtp \
  --policy-arn arn:aws:iam::aws:policy/AmazonSESFullAccess

# Generate SMTP credentials (convert IAM access key → SES SMTP password)
aws iam create-access-key --user-name invictus-ses-smtp
# Note the AccessKeyId and SecretAccessKey — convert to SES SMTP credentials:
# https://docs.aws.amazon.com/ses/latest/dg/smtp-credentials.html
```

Store SMTP settings as secrets (see step 5):
```
SMTP_HOST=email-smtp.eu-west-2.amazonaws.com
SMTP_PORT=587
SMTP_USER=<SES SMTP username (converted from IAM AccessKeyId)>
SMTP_PASSWORD=<SES SMTP password (converted from IAM SecretAccessKey)>
SMTP_FROM=noreply@invictushiring.co
SMTP_USE_TLS=true
```

---

## 5. Secrets Manager

Store all sensitive env vars — the ECS task reads these at runtime.

```bash
aws secretsmanager create-secret --name invictus/openai_api_key \
  --secret-string "sk-..."  --region $REGION

aws secretsmanager create-secret --name invictus/database_url \
  --secret-string "postgresql+asyncpg://hiring_user:PASSWORD@RDS_ENDPOINT:5432/hiring_db?ssl=require" \
  --region $REGION

aws secretsmanager create-secret --name invictus/redis_url \
  --secret-string "redis://ELASTICACHE_ENDPOINT:6379/0"  --region $REGION

aws secretsmanager create-secret --name invictus/encryption_key \
  --secret-string "YOUR_FERNET_KEY"  --region $REGION

aws secretsmanager create-secret --name invictus/jwt_secret_key \
  --secret-string "YOUR_JWT_SECRET"  --region $REGION

aws secretsmanager create-secret --name invictus/smtp_user \
  --secret-string "YOUR_SES_SMTP_USER"  --region $REGION

aws secretsmanager create-secret --name invictus/smtp_password \
  --secret-string "YOUR_SES_SMTP_PASSWORD"  --region $REGION
```

---

## 6. EFS (for CV uploads)

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

## 7. IAM Roles

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

## 8. CloudWatch Log Groups

```bash
aws logs create-log-group --log-group-name /ecs/invictus-backend  --region $REGION
aws logs create-log-group --log-group-name /ecs/invictus-frontend --region $REGION
```

---

## 9. ECS Cluster + Service

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

## 10. Update ecs-task-definition.json placeholders

Open `infra/ecs-task-definition.json` and replace:

| Placeholder | Value |
|---|---|
| `ACCOUNT_ID` | Your AWS account ID (12 digits) |
| `REGION` | e.g. `eu-west-2` |
| `fs-XXXXXXXXX` | Your EFS file system ID from step 6 |
| `YOUR_DOMAIN` | Your ALB DNS name or custom domain |

---

## Ongoing deploys

```bash
./infra/deploy.sh eu-west-2 YOUR_ACCOUNT_ID
```

This builds both images, pushes to ECR, registers a new task definition, and triggers a rolling update with zero downtime.