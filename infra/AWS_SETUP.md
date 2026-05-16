# AWS Infrastructure Setup — Invictus Hiring

Run these steps once. After setup, all deploys go through `deploy.sh`.

---

## Prerequisites

```bash
# Install the AWS CLI tool on Mac
brew install awscli

# Configure your AWS credentials, region, and output format
# You'll be prompted for: Access Key ID, Secret Access Key, region (e.g. eu-west-2), output format (json)
aws configure
```

Set shell variables used throughout this guide:
```bash
# Set your target AWS region — all resources will be created here
REGION=eu-west-2

# Fetch your 12-digit AWS account ID automatically and store it
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

---

## 1. ECR Repositories

ECR (Elastic Container Registry) stores your Docker images so ECS can pull them at deploy time.

```bash
# Create a private image repository for the backend FastAPI container
aws ecr create-repository --repository-name invictus-backend  --region $REGION

# Create a private image repository for the frontend Next.js container
aws ecr create-repository --repository-name invictus-frontend --region $REGION
```

---

## 2. VPC, Subnets & Security Groups

Run this before steps 3–7 to capture the variables used throughout the rest of this guide.

```bash
# Fetch your default VPC ID — AWS creates one automatically in every account
VPC_ID=$(aws ec2 describe-vpcs \
  --filters "Name=isDefault,Values=true" \
  --query "Vpcs[0].VpcId" --output text)
echo "VPC ID: $VPC_ID"

# List all default subnets with their Availability Zones — pick 2 from different AZs
# RDS requires subnets in at least 2 AZs for a subnet group
aws ec2 describe-subnets \
  --filters "Name=defaultForAz,Values=true" \
  --query "Subnets[*].{ID:SubnetId,AZ:AvailabilityZone}" \
  --output table

# Set the two subnet IDs from the output above (must be in different AZs)
SUBNET_1=subnet-XXXXXXXX   # replace with your first subnet ID
SUBNET_2=subnet-YYYYYYYY   # replace with your second subnet ID (different AZ)

# Create a dedicated security group for the RDS instance
# This controls who is allowed to connect to the database on port 5432 (Postgres)
RDS_SG=$(aws ec2 create-security-group \
  --group-name invictus-rds-sg \
  --description "Invictus RDS Postgres" \
  --vpc-id $VPC_ID \
  --region $REGION \
  --query "GroupId" --output text)

# Allow inbound Postgres connections from any IP — tighten this after ECS is running (see note below)
aws ec2 authorize-security-group-ingress \
  --group-id $RDS_SG \
  --protocol tcp --port 5432 --cidr 0.0.0.0/0 \
  --region $REGION

# Create a dedicated security group for the ElastiCache Redis cluster
# This controls who can connect to Redis on port 6379
REDIS_SG=$(aws ec2 create-security-group \
  --group-name invictus-redis-sg \
  --description "Invictus ElastiCache Redis" \
  --vpc-id $VPC_ID \
  --region $REGION \
  --query "GroupId" --output text)

# Allow inbound Redis connections from any IP — tighten after ECS is running
aws ec2 authorize-security-group-ingress \
  --group-id $REDIS_SG \
  --protocol tcp --port 6379 --cidr 0.0.0.0/0 \
  --region $REGION

echo "VPC:      $VPC_ID"
echo "Subnet 1: $SUBNET_1"
echo "Subnet 2: $SUBNET_2"
echo "RDS SG:   $RDS_SG"
echo "Redis SG: $REDIS_SG"
```

> **Tightening later** — once ECS task SG (`$TASK_SG`) is created in step 10, restrict RDS and Redis to only accept traffic from your app containers:
> ```bash
> # Remove the open rules and replace with ECS-task-only access
> aws ec2 revoke-security-group-ingress --group-id $RDS_SG --protocol tcp --port 5432 --cidr 0.0.0.0/0
> aws ec2 authorize-security-group-ingress --group-id $RDS_SG --protocol tcp --port 5432 --source-group $TASK_SG
>
> aws ec2 revoke-security-group-ingress --group-id $REDIS_SG --protocol tcp --port 6379 --cidr 0.0.0.0/0
> aws ec2 authorize-security-group-ingress --group-id $REDIS_SG --protocol tcp --port 6379 --source-group $TASK_SG
> ```

---

## 3. RDS PostgreSQL with pgvector

RDS hosts the production Postgres database. pgvector enables the embedding similarity search used by the JD RAG pipeline.

```bash
# Create a DB subnet group — tells RDS which subnets it can place the instance in
# Requires at least 2 subnets in different Availability Zones
aws rds create-db-subnet-group \
  --db-subnet-group-name invictus-db-subnet \
  --db-subnet-group-description "Invictus DB subnets" \
  --subnet-ids $SUBNET_1 $SUBNET_2

# Create the RDS Postgres instance
# db.t4g.micro = smallest ARM-based instance, sufficient for this workload
# --no-publicly-accessible = not reachable from the internet (only from within VPC)
# --backup-retention-period 7 = keep 7 days of automated backups
aws rds create-db-instance \
  --db-instance-identifier invictus-hiring-db \
  --db-instance-class db.t4g.micro \
  --engine postgres \
  --engine-version 16.3 \
  --master-username hiring_user \
  --master-user-password YOUR_STRONG_PASSWORD \
  --allocated-storage 20 \
  --db-name hiring_db \
  --db-subnet-group-name invictus-db-subnet \
  --vpc-security-group-ids $RDS_SG \
  --no-publicly-accessible \
  --backup-retention-period 7

# Block until the instance status becomes "available" (~5 min)
aws rds wait db-instance-available --db-instance-identifier invictus-hiring-db

# Print the hostname you'll use in DATABASE_URL — save this value
aws rds describe-db-instances \
  --db-instance-identifier invictus-hiring-db \
  --query "DBInstances[0].Endpoint.Address" --output text

# Temporarily allow public access so you can run migrations from your laptop
# Revert this once ECS is running and the app connects from within the VPC
aws rds modify-db-instance \
  --db-instance-identifier invictus-hiring-db \
  --publicly-accessible \
  --apply-immediately \
  --region $REGION
```

Run migrations to set up the schema (replace placeholders with your actual values):
```bash
# Set once — reuse for all migration commands below
DB_URL="postgresql://hiring_user:YOUR_STRONG_PASSWORD@YOUR_RDS_ENDPOINT:5432/hiring_db"

# Creates the pgvector extension — must run before any table that uses vector columns
psql $DB_URL -f backend/migrations/001_init.sql

# Creates all tables, indexes, and constraints from the current model definitions
# Use this for a fresh database — skips the need to run migrations 002–008 individually
psql $DB_URL -f backend/migrations/000_full_schema.sql
```

> **Upgrading an existing database?** Run migrations 002–008 instead of `000_full_schema.sql` — they use `ADD COLUMN IF NOT EXISTS` so they are safe to re-run.

---

## 4. ElastiCache (Redis)

Redis caches chat history and active session state. The app falls back to Postgres if Redis is unavailable, but ElastiCache is strongly recommended for production.

```bash
# Create a subnet group for Redis — same concept as RDS subnet group
# Tells ElastiCache which subnets it can place nodes in
aws elasticache create-cache-subnet-group \
  --cache-subnet-group-name invictus-redis-subnet \
  --cache-subnet-group-description "Invictus Redis subnets" \
  --subnet-ids $SUBNET_1 $SUBNET_2 \
  --region $REGION

# Create a single-node Redis 7 cluster
# cache.t4g.micro = smallest ARM instance, sufficient for session/chat caching
aws elasticache create-cache-cluster \
  --cache-cluster-id invictus-redis \
  --cache-node-type cache.t4g.micro \
  --engine redis \
  --engine-version 7.0 \
  --num-cache-nodes 1 \
  --cache-subnet-group-name invictus-redis-subnet \
  --security-group-ids $REDIS_SG \
  --region $REGION

# Block until the cluster status becomes "available" (~3 min)
aws elasticache wait cache-cluster-available --cache-cluster-id invictus-redis --region $REGION

# Print the Redis hostname — save this for the REDIS_URL secret in step 6
aws elasticache describe-cache-clusters \
  --cache-cluster-id invictus-redis \
  --show-cache-node-info \
  --query "CacheClusters[0].CacheNodes[0].Endpoint.Address" --output text
```

Set the Redis URL as a secret (see step 6):
```
REDIS_URL=redis://ELASTICACHE_ENDPOINT:6379/0
```

---

## 5. SMTP — Mailpit sidecar container (no AWS SES)

Instead of AWS SES, a [Mailpit](https://github.com/axllent/mailpit) container runs as a sidecar inside the same ECS task. The backend connects to it over localhost on port 1025 (same as local dev with Mailhog). Mailpit catches all outgoing email and exposes a web UI on port 8025 so you can inspect sent emails without real delivery.

No DNS records, no domain verification, no IAM users, no SMTP credentials needed.

**No AWS CLI commands required for this step.** The container is declared directly in `ecs-task-definition.json` (see step 13).

### What to add to `ecs-task-definition.json`

Add a second container entry alongside `backend` in the `containerDefinitions` array:

```json
{
  "name": "mailpit",
  "image": "axllent/mailpit:latest",
  "essential": false,
  "portMappings": [
    { "containerPort": 1025, "protocol": "tcp" },
    { "containerPort": 8025, "protocol": "tcp" }
  ],
  "logConfiguration": {
    "logDriver": "awslogs",
    "options": {
      "awslogs-group": "/ecs/invictus-backend",
      "awslogs-region": "REGION",
      "awslogs-stream-prefix": "mailpit"
    }
  }
}
```

Because both containers share the same task network namespace, the backend reaches Mailpit at `localhost:1025` — identical to local dev.

### SMTP env vars for the backend container

```
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=noreply@invictushiring.co
SMTP_USE_TLS=false
```

These go into the backend container's `environment` array in the task definition (not Secrets Manager — they contain no credentials).

### Accessing the Mailpit UI in production

Mailpit's web UI (port 8025) is not exposed through the ALB by default. To inspect sent emails, use ECS Exec:

```bash
# Open a shell into the running Mailpit container
aws ecs execute-command \
  --cluster invictus-cluster \
  --task <TASK_ID> \
  --container mailpit \
  --interactive \
  --command "/bin/sh"
```

Or add a second ALB listener rule that forwards `/mailpit*` traffic to port 8025 on the task (restrict by IP if doing this).

> **Note** — Mailpit stores emails in memory only. They are lost when the container restarts. This is intentional for a demo platform; no email data persists to disk.

---

## 6. Secrets Manager

Secrets Manager stores all sensitive environment variables. The ECS task fetches them at runtime so no secrets are baked into the Docker image.

```bash
# Store the OpenAI API key used by all AI agents
aws secretsmanager create-secret --name invictus/openai_api_key \
  --secret-string "sk-..."  --region $REGION

# Store the full Postgres connection string — replace with your actual RDS endpoint and password
aws secretsmanager create-secret --name invictus/database_url \
  --secret-string "postgresql+asyncpg://hiring_user:PASSWORD@RDS_ENDPOINT:5432/hiring_db?ssl=require" \
  --region $REGION

# Store the Redis connection URL — replace with your actual ElastiCache endpoint
aws secretsmanager create-secret --name invictus/redis_url \
  --secret-string "redis://ELASTICACHE_ENDPOINT:6379/0"  --region $REGION

# Store the Fernet encryption key used to encrypt candidate emails at rest
# Generate one: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
aws secretsmanager create-secret --name invictus/encryption_key \
  --secret-string "YOUR_FERNET_KEY"  --region $REGION

# Store the JWT signing secret used to sign and verify auth tokens
aws secretsmanager create-secret --name invictus/jwt_secret_key \
  --secret-string "YOUR_JWT_SECRET"  --region $REGION

```

All five secrets must be referenced in `ecs-task-definition.json` under the backend container's `secrets` array (see step 13).

> **SMTP credentials not stored here** — because the Mailpit sidecar requires no username or password, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_USE_TLS` are passed as plain `environment` variables in the task definition, not as Secrets Manager secrets.

---

## 7. EFS (for CV uploads)

EFS (Elastic File System) is a shared persistent volume. CV files, Indeed XML feeds, and Google Jobs pages are written here so they survive container restarts.

```bash
# Create a new EFS file system — returns a file system ID (fs-XXXXXXXXX)
EFS_ID=$(aws efs create-file-system \
  --performance-mode generalPurpose \
  --region $REGION \
  --query "FileSystemId" --output text)

# Print the EFS ID — paste this into ecs-task-definition.json → fileSystemId
echo "EFS ID: $EFS_ID"

# Create a mount target in each subnet so Fargate tasks in both AZs can reach EFS
# $TASK_SG is created in step 10 — run these two commands after that step
aws efs create-mount-target \
  --file-system-id $EFS_ID \
  --subnet-id $SUBNET_1 \
  --security-groups $TASK_SG

aws efs create-mount-target \
  --file-system-id $EFS_ID \
  --subnet-id $SUBNET_2 \
  --security-groups $TASK_SG
```

> **EFS security group** — `$TASK_SG` must allow inbound TCP 2049 (NFS) so containers can mount EFS.

The backend writes three directories to EFS at runtime:

| Container path | EFS root directory | Purpose |
|---|---|---|
| `/app/backend/cv_uploads` | `/cv_uploads` | candidate CV files |
| `/app/backend/indeed_feeds` | `/indeed_feeds` | Indeed XML job feeds |
| `/app/backend/job_pages` | `/job_pages` | Google Jobs JSON-LD pages |

---

## 8. IAM Roles

IAM roles grant ECS the permissions it needs to pull images, read secrets, and write to EFS and CloudWatch.

### ECS Task Execution Role (pull images, read secrets)
```bash
# Create the execution role — allows ECS itself to pull images from ECR and read secrets
aws iam create-role --role-name ecsTaskExecutionRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

# Attach the AWS-managed policy that grants ECR pull and CloudWatch Logs write access
aws iam attach-role-policy --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Allow the execution role to read secrets from Secrets Manager at container startup
aws iam attach-role-policy --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/SecretsManagerReadWrite
```

### Task Role (app permissions — EFS, CloudWatch)
```bash
# Create the task role — this is what your running app container uses at runtime
aws iam create-role --role-name invictusTaskRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

# Allow the app to read and write files on EFS (CV uploads, job feeds, etc.)
aws iam attach-role-policy --role-name invictusTaskRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonElasticFileSystemClientReadWriteAccess
```

---

## 9. CloudWatch Log Groups

CloudWatch collects stdout/stderr from both containers so you can debug issues after deploy.

```bash
# Create log groups for backend and frontend containers
aws logs create-log-group --log-group-name /ecs/invictus-backend  --region $REGION
aws logs create-log-group --log-group-name /ecs/invictus-frontend --region $REGION

# Set 30-day retention so logs don't accumulate and incur unnecessary storage cost
aws logs put-retention-policy --log-group-name /ecs/invictus-backend  --retention-in-days 30 --region $REGION
aws logs put-retention-policy --log-group-name /ecs/invictus-frontend --retention-in-days 30 --region $REGION
```

---

## 10. Security Groups (ALB + ECS Tasks)

```bash
# VPC_ID, SUBNET_1, SUBNET_2 were set in step 2

# Create security group for the Application Load Balancer
# This is the internet-facing entry point — allows HTTP and HTTPS from anywhere
ALB_SG=$(aws ec2 create-security-group \
  --group-name invictus-alb-sg \
  --description "Invictus ALB" \
  --vpc-id $VPC_ID \
  --region $REGION \
  --query "GroupId" --output text)

# Allow public HTTP traffic into the ALB from any IP
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 80  --cidr 0.0.0.0/0 --region $REGION
# Allow public HTTPS traffic into the ALB from any IP
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 443 --cidr 0.0.0.0/0 --region $REGION

# Create security group for the Fargate task containers
# Only the ALB can send traffic to them — not the public internet directly
TASK_SG=$(aws ec2 create-security-group \
  --group-name invictus-task-sg \
  --description "Invictus ECS tasks" \
  --vpc-id $VPC_ID \
  --region $REGION \
  --query "GroupId" --output text)

# Allow the ALB to forward HTTP traffic to the frontend container (port 80)
aws ec2 authorize-security-group-ingress --group-id $TASK_SG \
  --protocol tcp --port 80 --source-group $ALB_SG --region $REGION
# Allow the ALB to forward API traffic to the backend container (port 8000)
aws ec2 authorize-security-group-ingress --group-id $TASK_SG \
  --protocol tcp --port 8000 --source-group $ALB_SG --region $REGION

echo "ALB SG:  $ALB_SG"
echo "Task SG: $TASK_SG"
```

After this step, go back and tighten RDS and Redis security groups (see note in step 2).

---

## 11. Application Load Balancer + HTTPS

The ALB is the public entry point. It routes incoming requests to your Fargate containers and terminates HTTPS.

```bash
# Create an internet-facing ALB across both subnets for high availability
ALB_ARN=$(aws elbv2 create-load-balancer \
  --name invictus-alb \
  --subnets $SUBNET_1 $SUBNET_2 \
  --security-groups $ALB_SG \
  --scheme internet-facing \
  --type application \
  --region $REGION \
  --query "LoadBalancers[0].LoadBalancerArn" --output text)

# Create a target group — defines which container the ALB forwards traffic to
# --target-type ip is required for Fargate (tasks have IPs, not EC2 instance IDs)
TG_ARN=$(aws elbv2 create-target-group \
  --name invictus-tg \
  --protocol HTTP \
  --port 80 \
  --vpc-id $VPC_ID \
  --target-type ip \
  --health-check-path / \
  --region $REGION \
  --query "TargetGroups[0].TargetGroupArn" --output text)

# Create an HTTP listener — forwards port 80 traffic to the target group
aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=forward,TargetGroupArn=$TG_ARN \
  --region $REGION

# Print the ALB DNS name — use this as YOUR_DOMAIN in the task definition
aws elbv2 describe-load-balancers \
  --load-balancer-arns $ALB_ARN \
  --query "LoadBalancers[0].DNSName" --output text --region $REGION
```

**HTTPS (recommended for production):**

```bash
# Request a free TLS certificate from ACM for your domain
# You must own the domain and add a DNS validation record when prompted
CERT_ARN=$(aws acm request-certificate \
  --domain-name invictushiring.co \
  --validation-method DNS \
  --region $REGION \
  --query "CertificateArn" --output text)

# After DNS validation completes, add an HTTPS listener on port 443
aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTPS \
  --port 443 \
  --certificates CertificateArn=$CERT_ARN \
  --default-actions Type=forward,TargetGroupArn=$TG_ARN \
  --region $REGION
```

---

## 12. ECS Cluster + Service

ECS Fargate runs your containers without managing any EC2 servers.

```bash
# Create the ECS cluster — a logical grouping for your Fargate tasks
aws ecs create-cluster --cluster-name invictus-cluster --region $REGION

# Build both Docker images, push them to ECR, register a new task definition revision
./infra/deploy.sh $REGION $ACCOUNT_ID

# Create the ECS service — keeps 1 task running at all times and registers it with the ALB
# Run this only once; subsequent deploys use deploy.sh
aws ecs create-service \
  --cluster invictus-cluster \
  --service-name invictus-service \
  --task-definition invictus-hiring \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_1,$SUBNET_2],securityGroups=[$TASK_SG],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=$TG_ARN,containerName=frontend,containerPort=80" \
  --region $REGION
```

---

## 13. Update ecs-task-definition.json placeholders

Open `infra/ecs-task-definition.json` and replace:

| Placeholder | Value |
|---|---|
| `ACCOUNT_ID` | Your AWS account ID (12 digits) |
| `REGION` | e.g. `eu-west-2` |
| `fs-XXXXXXXXX` | Your EFS file system ID from step 7 |
| `YOUR_DOMAIN` | Your ALB DNS name or custom domain |

The task definition must include **three containers**: `backend`, `frontend`, and `mailpit`.

The backend container's `secrets` array references the five Secrets Manager secrets from step 6 (`openai_api_key`, `database_url`, `redis_url`, `encryption_key`, `jwt_secret_key`).

The backend container's `environment` array carries the plain SMTP vars (no credentials):
```json
{ "name": "SMTP_HOST",     "value": "localhost" },
{ "name": "SMTP_PORT",     "value": "1025" },
{ "name": "SMTP_USER",     "value": "" },
{ "name": "SMTP_PASSWORD", "value": "" },
{ "name": "SMTP_FROM",     "value": "noreply@invictushiring.co" },
{ "name": "SMTP_USE_TLS",  "value": "false" }
```

---

## Ongoing deploys

```bash
# Builds both images, pushes to ECR, registers a new task definition, triggers rolling update
./infra/deploy.sh eu-west-2 YOUR_ACCOUNT_ID
```