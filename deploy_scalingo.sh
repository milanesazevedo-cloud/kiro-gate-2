#!/bin/bash

# Kiro Gateway Scalingo Deployment Script
# Usage: ./deploy_scalingo.sh

set -e  # Exit on any error

echo "🚀 Starting Kiro Gateway Deployment to Scalingo..."

# Check if Scalingo CLI is installed
if ! command -v scalingo &> /dev/null; then
    echo "❌ Scalingo CLI not found. Please install it first:"
    echo "   curl -O https://cli-dl.scalingo.io/install && bash install"
    exit 1
fi

# Login to Scalingo using the provided token
echo "🔑 Logging into Scalingo..."
scalingo login --api-token tk-us-2rS9FtHDfCGvE8NaxRwo7AK9SQeCmRiomrJpSpQJV3dIf-Z9

# Create app if it doesn't exist (uncomment and modify as needed)
# echo "🏗️ Creating Scalingo app..."
# scalingo create kiro-gateway

# Add remote if not already added
echo "🔗 Adding Scalingo remote..."
git remote add scalingo https://git.scalingo.com/kiro-gateway.git 2>/dev/null || echo "Remote already exists"

# Deploy to Scalingo
echo "📦 Deploying to Scalingo..."
scalingo git-push scalingo main

echo "✅ Deployment completed successfully!"

echo "📋 Next steps:"
echo "1. Set your environment variables in the Scalingo dashboard:"
echo "   - PROXY_API_KEY"
echo "   - REFRESH_TOKEN1 through REFRESH_TOKEN5"
echo "   - Any other custom configuration"
echo ""
echo "2. Access your app at: https://kiro-gateway.scalingo.io"
echo "3. Monitor logs with: scalingo logs -a kiro-gateway"
