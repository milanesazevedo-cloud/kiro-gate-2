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

# Check if SCALINGO_API_TOKEN environment variable is set
if [ -z "$SCALINGO_API_TOKEN" ]; then
    echo "❌ SCALINGO_API_TOKEN environment variable not set."
    echo "Please set it with: export SCALINGO_API_TOKEN=your_token_here"
    echo "Or run with: SCALINGO_API_TOKEN=your_token_here ./deploy_scalingo.sh"
    exit 1
fi

# Login to Scalingo using the provided token from environment variable
echo "🔑 Logging into Scalingo..."
scalingo login --api-token "$SCALINGO_API_TOKEN"

# Check if app exists
APP_NAME="kiro-gateway"
echo "🔍 Checking if app '$APP_NAME' exists..."

if scalingo --app "$APP_NAME" apps-info &>/dev/null; then
    echo "✅ App '$APP_NAME' already exists"
else
    echo "🏗️ App '$APP_NAME' does not exist, you'll need to create it manually in the Scalingo dashboard"
    echo "   to avoid the free trial confirmation prompt."
    echo ""
    echo "📝 Instructions:"
    echo "   1. Go to https://my.scalingo.com/apps"
    echo "   2. Click 'Create App'"
    echo "   3. Name it 'kiro-gateway'"
    echo "   4. Select your preferred region"
    echo "   5. Then run this script again"
    exit 1
fi

# Add remote if not already added
echo "🔗 Setting up Scalingo git remote..."
scalingo git-setup --app "$APP_NAME"

# Deploy to Scalingo
echo "📦 Deploying to Scalingo..."
git push scalingo main

echo "✅ Deployment completed successfully!"

echo "📋 Next steps:"
echo "1. Set your environment variables in the Scalingo dashboard:"
echo "   - PROXY_API_KEY"
echo "   - REFRESH_TOKEN1 through REFRESH_TOKEN5"
echo "   - Any other custom configuration"
echo ""
echo "2. Access your app at: https://$APP_NAME.scalingo.io"
echo "3. Monitor logs with: scalingo --app $APP_NAME logs"
