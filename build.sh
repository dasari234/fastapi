#!/bin/bash

# Configuration
REGION="ap-south-1"
ECR_REPOSITORY="fastapi-lambda-repo"
IMAGE_TAG="latest"
LAMBDA_FUNCTION_NAME="fastapi-lambda-function"
ROLE_NAME="lambda-execution-role"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting FastAPI Lambda deployment...${NC}"

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}AWS CLI is not installed. Please install it first.${NC}"
    exit 1
fi

# Navigate to app directory
cd app

# Build Docker image
echo -e "${YELLOW}Building Docker image...${NC}"
docker build -t ${ECR_REPOSITORY}:${IMAGE_TAG} .

# Create ECR repository (if it doesn't exist)
echo -e "${YELLOW}Setting up ECR repository...${NC}"
if ! aws ecr describe-repositories --repository-names ${ECR_REPOSITORY} --region ${REGION} &> /dev/null; then
    echo -e "${YELLOW}Creating ECR repository...${NC}"
    aws ecr create-repository --repository-name ${ECR_REPOSITORY} --region ${REGION}
    sleep 5
fi

# Get ECR login password and login
echo -e "${YELLOW}Logging into ECR...${NC}"
aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin $(aws sts get-caller-identity --query 'Account' --output text).dkr.ecr.${REGION}.amazonaws.com

# Tag and push image to ECR
ECR_URI=$(aws ecr describe-repositories --repository-names ${ECR_REPOSITORY} --region ${REGION} --query 'repositories[0].repositoryUri' --output text)

echo -e "${YELLOW}Tagging and pushing image to ECR...${NC}"
docker tag ${ECR_REPOSITORY}:${IMAGE_TAG} ${ECR_URI}:${IMAGE_TAG}
docker push ${ECR_URI}:${IMAGE_TAG}

# Create IAM role for Lambda (if it doesn't exist)
echo -e "${YELLOW}Setting up IAM role...${NC}"
if ! aws iam get-role --role-name ${ROLE_NAME} --region ${REGION} &> /dev/null; then
    echo -e "${YELLOW}Creating IAM role...${NC}"
    
    # Create trust policy document
    cat > trust-policy.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "lambda.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
EOF
    
    aws iam create-role \
        --role-name ${ROLE_NAME} \
        --assume-role-policy-document file://trust-policy.json \
        --region ${REGION}
    
    # Attach basic execution policy
    aws iam attach-role-policy \
        --role-name ${ROLE_NAME} \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
        --region ${REGION}
    
    rm trust-policy.json
    
    # Wait for role to be available
    sleep 10
fi

# Get role ARN
ROLE_ARN=$(aws iam get-role --role-name ${ROLE_NAME} --region ${REGION} --query 'Role.Arn' --output text)

# Create or update Lambda function
echo -e "${YELLOW}Creating/updating Lambda function...${NC}"
if aws lambda get-function --function-name ${LAMBDA_FUNCTION_NAME} --region ${REGION} &> /dev/null; then
    echo -e "${YELLOW}Updating existing Lambda function...${NC}"
    aws lambda update-function-code \
        --function-name ${LAMBDA_FUNCTION_NAME} \
        --image-uri ${ECR_URI}:${IMAGE_TAG} \
        --region ${REGION}
else
    echo -e "${YELLOW}Creating new Lambda function...${NC}"
    aws lambda create-function \
        --function-name ${LAMBDA_FUNCTION_NAME} \
        --role ${ROLE_ARN} \
        --code ImageUri=${ECR_URI}:${IMAGE_TAG} \
        --package-type Image \
        --timeout 30 \
        --memory-size 512 \
        --environment Variables="{ \
            'ENVIRONMENT': 'production', \
            'DEBUG': 'False' \
        }" \
        --region ${REGION}
fi

# Wait for function to be active
echo -e "${YELLOW}Waiting for Lambda function to be active...${NC}"
aws lambda wait function-active --function-name ${LAMBDA_FUNCTION_NAME} --region ${REGION}

# Create Function URL
echo -e "${YELLOW}Creating Function URL...${NC}"
aws lambda create-function-url-config \
    --function-name ${LAMBDA_FUNCTION_NAME} \
    --auth-type NONE \
    --region ${REGION}

# Add resource-based policy for Function URL
echo -e "${YELLOW}Adding resource-based policy...${NC}"
aws lambda add-permission \
    --function-name ${LAMBDA_FUNCTION_NAME} \
    --action lambda:InvokeFunctionUrl \
    --principal "*" \
    --function-url-auth-type NONE \
    --statement-id FunctionURLAllowPublicAccess \
    --region ${REGION}

# Get Function URL
FUNCTION_URL=$(aws lambda get-function-url-config --function-name ${LAMBDA_FUNCTION_NAME} --region ${REGION} --query 'FunctionUrl' --output text)

echo -e "${GREEN}Deployment completed successfully!${NC}"
echo -e "${GREEN}Function URL: ${FUNCTION_URL}${NC}"
echo -e "${YELLOW}Test endpoints:${NC}"
echo -e "${YELLOW}  Health check: ${FUNCTION_URL}/health${NC}"
echo -e "${YELLOW}  Root: ${FUNCTION_URL}/${NC}"
echo -e "${YELLOW}  API: ${FUNCTION_URL}/api/v1/${NC}"