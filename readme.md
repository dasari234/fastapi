docker-compose up -d
docker-compose down
docker-compose stope






Here's how to deploy your Dockerized FastAPI application with PostgreSQL and Redis to AWS ECS:

## 1. Project Structure Preparation

```
fastapi-ecs-project/
├── app/                 (your FastAPI code)
├── Dockerfile           (your FastAPI Dockerfile)
├── docker-compose.yml   (for local development)
├── Dockerfile.nginx     (optional, for nginx)
├── nginx.conf          (optional, for nginx)
├── scripts/
│   └── deploy.sh       (deployment script)
└── task-definitions/   (ECS task definitions)
```

## 2. Create ECR Repository

```bash
# Create ECR repository
aws ecr create-repository --repository-name fastapi-app

# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login \
    --username AWS \
    --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com
```

## 3. Create Dockerfile for Production

**`Dockerfile.prod`**:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ./app ./app

# Create non-root user
RUN useradd -m -u 1000 fastapi-user && chown -R fastapi-user:fastapi-user /app
USER fastapi-user

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

## 4. Create ECS Task Definition

**`task-definitions/fastapi-task.json`**:
```json
{
  "family": "fastapi-task",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "executionRoleArn": "arn:aws:iam::YOUR_ACCOUNT_ID:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::YOUR_ACCOUNT_ID:role/ecsTaskRole",
  "containerDefinitions": [
    {
      "name": "fastapi-app",
      "image": "YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/fastapi-app:latest",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "ENVIRONMENT",
          "value": "production"
        },
        {
          "name": "DATABASE_URL",
          "value": "postgresql://user:password@your-rds-endpoint:5432/fastapi_db"
        },
        {
          "name": "REDIS_URL",
          "value": "redis://your-elasticache-endpoint:6379/0"
        }
      ],
      "secrets": [
        {
          "name": "SECRET_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:YOUR_ACCOUNT_ID:secret:fastapi-secrets:SECRET_KEY::"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/fastapi-app",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

## 5. Create CloudFormation Template

**`cloudformation.yml`**:
```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: FastAPI ECS Deployment

Parameters:
  VpcId:
    Type: AWS::EC2::VPC::Id
    Description: VPC ID

Resources:
  # ECS Cluster
  ECSCluster:
    Type: AWS::ECS::Cluster
    Properties:
      ClusterName: fastapi-cluster

  # Security Group
  AppSecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: Security group for FastAPI app
      VpcId: !Ref VpcId
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 8000
          ToPort: 8000
          CidrIp: 0.0.0.0/0

  # Load Balancer
  ApplicationLoadBalancer:
    Type: AWS::ElasticLoadBalancingV2::LoadBalancer
    Properties:
      Scheme: internet-facing
      Subnets: !Ref PublicSubnets
      SecurityGroups:
        - !Ref AppSecurityGroup

  # ECS Service
  ECSService:
    Type: AWS::ECS::Service
    Properties:
      ServiceName: fastapi-service
      Cluster: !Ref ECSCluster
      LaunchType: FARGATE
      DesiredCount: 2
      NetworkConfiguration:
        AwsvpcConfiguration:
          AssignPublicIp: ENABLED
          Subnets: !Ref PublicSubnets
          SecurityGroups:
            - !Ref AppSecurityGroup
      LoadBalancers:
        - ContainerName: fastapi-app
          ContainerPort: 8000
          TargetGroupArn: !Ref TargetGroup
      TaskDefinition: !Ref TaskDefinition

Outputs:
  LoadBalancerDNS:
    Description: Load Balancer DNS Name
    Value: !GetAtt ApplicationLoadBalancer.DNSName
```

## 6. Create Deployment Script

**`scripts/deploy.sh`**:
```bash
#!/bin/bash

set -e

REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/fastapi-app"

# Build and push Docker image
echo "Building Docker image..."
docker build -t fastapi-app -f Dockerfile.prod .

echo "Logging into ECR..."
aws ecr get-login-password --region $REGION | docker login \
    --username AWS \
    --password-stdin $ECR_REPO

echo "Tagging and pushing image..."
docker tag fastapi-app:latest $ECR_REPO:latest
docker push $ECR_REPO:latest

# Update ECS service
echo "Updating ECS service..."
aws ecs update-service \
    --cluster fastapi-cluster \
    --service fastapi-service \
    --force-new-deployment \
    --region $REGION

echo "Deployment completed successfully!"
```

## 7. Set Up AWS Infrastructure

### Create RDS PostgreSQL:
```bash
aws rds create-db-instance \
    --db-instance-identifier fastapi-db \
    --db-instance-class db.t3.micro \
    --engine postgres \
    --master-username user \
    --master-user-password password \
    --allocated-storage 20 \
    --backup-retention-period 7
```

### Create ElastiCache Redis:
```bash
aws elasticache create-cache-cluster \
    --cache-cluster-id fastapi-redis \
    --engine redis \
    --cache-node-type cache.t3.micro \
    --num-cache-nodes 1 \
    --port 6379
```

## 8. Environment Configuration

**Store secrets in AWS Secrets Manager:**
```bash
aws secretsmanager create-secret \
    --name fastapi-secrets \
    --secret-string '{
        "SECRET_KEY": "your-super-secret-key-here",
        "DATABASE_URL": "postgresql://user:password@your-rds-endpoint:5432/fastapi_db",
        "REDIS_URL": "redis://your-elasticache-endpoint:6379/0"
    }'
```

## 9. Deploy to ECS

```bash
# Make script executable
chmod +x scripts/deploy.sh

# Run deployment
./scripts/deploy.sh
```

## 10. Verify Deployment

```bash
# Get load balancer URL
ALB_DNS=$(aws elbv2 describe-load-balancers \
    --names fastapi-alb \
    --query 'LoadBalancers[0].DNSName' \
    --output text)

echo "Application URL: http://$ALB_DNS"

# Test health endpoint
curl http://$ALB_DNS/health

# Check ECS service status
aws ecs describe-services \
    --cluster fastapi-cluster \
    --services fastapi-service
```

## 11. Optional: Add CI/CD Pipeline

**`.github/workflows/deploy.yml`**:
```yaml
name: Deploy to ECS

on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Configure AWS credentials
      uses: aws-actions/configure-aws-credentials@v2
      with:
        aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
        aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
        aws-region: us-east-1
    
    - name: Login to Amazon ECR
      run: |
        aws ecr get-login-password --region us-east-1 | docker login \
            --username AWS \
            --password-stdin ${{ secrets.AWS_ACCOUNT_ID }}.dkr.ecr.us-east-1.amazonaws.com
    
    - name: Build and push Docker image
      run: |
        docker build -t fastapi-app -f Dockerfile.prod .
        docker tag fastapi-app:latest ${{ secrets.AWS_ACCOUNT_ID }}.dkr.ecr.us-east-1.amazonaws.com/fastapi-app:latest
        docker push ${{ secrets.AWS_ACCOUNT_ID }}.dkr.ecr.us-east-1.amazonaws.com/fastapi-app:latest
    
    - name: Deploy to ECS
      run: |
        aws ecs update-service \
            --cluster fastapi-cluster \
            --service fastapi-service \
            --force-new-deployment \
            --region us-east-1
```

## Key Changes for ECS:

1. **Use AWS Managed Services**: RDS for PostgreSQL, ElastiCache for Redis
2. **Environment Variables**: Use Secrets Manager for sensitive data
3. **Networking**: Use AWS VPC and security groups
4. **Load Balancing**: Application Load Balancer for traffic distribution
5. **Logging**: CloudWatch Logs for monitoring
6. **Scaling**: Configure ECS service auto-scaling

This setup provides a production-ready deployment on AWS ECS with proper security, scalability, and maintainability.