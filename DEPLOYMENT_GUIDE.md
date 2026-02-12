# Kiro Gateway Deployment Guide

## 🚀 Scalingo Deployment Setup

### 1. Prerequisites
- Scalingo account
- GitHub account with repository access
- Kiro Gateway repository (this one)

### 2. Create Scalingo App
1. Log into [Scalingo Dashboard](https://my.scalingo.com/apps)
2. Click "Create App"
3. Choose a name for your app (e.g., `kiro-gateway`)
4. Select the region closest to your users

### 3. Connect to GitHub Repository
1. In your Scalingo app dashboard, go to "Deployment" tab
2. Select "GitHub" as deployment method
3. Connect your GitHub account if not already connected
4. Select your repository (`milanesazevedo-cloud/kiro-gate-2`)
5. Enable "Auto Deploy" to automatically deploy on pushes to main branch

### 4. Configure Environment Variables
In the Scalingo dashboard, go to "Environment" tab and add these variables:

```
PROXY_API_KEY=your-secure-api-key-here
REFRESH_TOKEN1=your-first-account-refresh-token
REFRESH_TOKEN2=your-second-account-refresh-token
REFRESH_TOKEN3=your-third-account-refresh-token
REFRESH_TOKEN4=your-fourth-account-refresh-token
REFRESH_TOKEN5=your-fifth-account-refresh-token
BACKGROUND_REFRESH_INTERVAL=600
LOG_LEVEL=INFO
SERVER_HOST=0.0.0.0
```

### 5. Manual Deployment (if auto-deploy is not enabled)
1. Go to "Deployment" tab
2. Click "Manual Deploy"
3. Select the branch to deploy (usually `main`)
4. Click "Deploy"

### 6. Configure Domain (Optional)
1. Go to "Domains" tab
2. Add a custom domain if desired
3. Configure SSL certificate

### 7. Monitoring and Logs
- Use "Logs" tab to monitor application output
- Set up alerts in "Alerts" tab for monitoring
- Check "Metrics" tab for resource usage

## 🛠 Environment Variables Explanation

### Required Variables
- `PROXY_API_KEY`: Secret key for authenticating API requests to your gateway
- `REFRESH_TOKEN1-N`: Kiro account refresh tokens for multi-account support

### Optional Variables
- `BACKGROUND_REFRESH_INTERVAL`: How often to refresh tokens (default: 600 seconds)
- `LOG_LEVEL`: Logging verbosity (default: INFO)
- `SERVER_HOST`: Host to bind to (default: 0.0.0.0)

## 🔄 Multi-Account Rotation
The gateway automatically rotates requests across all configured accounts:
- Round-robin distribution for load balancing
- Automatic failover when an account becomes unavailable
- Background token refresh to maintain active sessions

## 📊 Health Monitoring
- `/` endpoint for basic health checks
- `/health` endpoint for detailed health information
- `/v1/accounts/status` endpoint for account status monitoring

## 🔧 Troubleshooting

### Common Issues
1. **Deployment Failures**: Check build logs in Scalingo dashboard
2. **Authentication Errors**: Verify refresh tokens are valid and not expired
3. **Connection Issues**: Check Scalingo environment variables
4. **Performance Problems**: Monitor resource usage in Scalingo metrics

### Scalingo Specific Notes
- The `$PORT` environment variable is automatically set by Scalingo
- Web processes should bind to `$PORT`
- Only the `web` process type is exposed to the internet
- Use `scalingo.json` to configure buildpack behavior

## 📈 Scaling Recommendations
- Start with 1 container and scale based on usage
- Monitor memory usage and adjust container size if needed
- Consider adding more Kiro accounts for higher capacity
- Set up alerts for downtime or performance degradation
