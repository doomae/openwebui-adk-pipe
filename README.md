# Open WebUI ADK Pipe

This pipe connects agents running with [ADK (Agent Development Kit)](https://google.github.io/adk-docs/) in Cloud Run as custom models in Open WebUI.

## Overview

This implementation allows you to integrate ADK agents as custom models in Open WebUI using the [pipe functionality](https://docs.openwebui.com/features/plugin/functions/pipe). The pipe handles authentication, session management, and streaming responses from ADK agents.

## Prerequisites

- ADK agent deployed in Cloud Run (see [ADK Cloud Run deployment guide](https://google.github.io/adk-docs/deploy/cloud-run/))
- Open WebUI instance with admin access
- Proper Google Cloud authentication setup

**Note:** Currently only tested with ADK agents deployed in Cloud Run. Agent Engine deployments might not work.

## Installation

1. In Open WebUI, navigate to **Admin Panel** → **Functions**
2. Click the **"+"** button to create a new function
3. Copy and paste the pipe code from `pipe.py` into the function editor
4. Save the function

## Configuration

Configure the following values in the function's valve settings:

| Setting | Description | Example |
|---------|-------------|---------|
| **App URL** | Cloud Run base URL of your ADK agent | `https://your-service-cloudrun.url` |
| **App Name** | Cloud Run service name | `your-adk-service-name` |
| **Preferred Language** | Default language for agent responses | `English`, `German`, etc. |
| **Streaming Delay** | Delay between message chunks (in seconds) for smoother streaming effect | `0.05` (optional, leave empty for no delay) |

## Authentication

### Cloud Run Deployment
When both Open WebUI and the ADK agent are deployed in Cloud Run, ensure that:
- The Open WebUI Cloud Run service's Service Account has permissions to invoke the ADK agent's Cloud Run service
- Proper IAM roles are configured for service-to-service authentication

### Local Development
For local development, set up Application Default Credentials:
```bash
gcloud auth application-default login
```

See the [Google Cloud ADC documentation](https://cloud.google.com/docs/authentication/provide-credentials-adc) for more details.

**Note:** Due to local environment limitations, the code includes a fallback mechanism that uses the `gcloud` CLI via subprocess if the standard authentication method fails.

## Usage

1. After installation and configuration, the ADK agent will appear as a custom model in Open WebUI
2. Select the model in a chat session
3. The pipe will handle:
   - User input preparation
   - ADK session initialization
   - Authentication token management
   - Streaming response processing
   - Function call and response formatting

## Features

- **Streaming Support**: Real-time streaming of agent responses
- **Function Call Handling**: Properly formatted display of tool usage
- **Session Management**: Maintains conversation context across messages
- **Multi-language Support**: Configurable preferred language
- **Smooth Streaming**: Optional delay configuration for better visual experience

## Known Issues & To-Dos

- [ ] **Token Optimization**: Currently obtains a new authentication token for every user prompt. Should implement token caching and refresh logic for better performance
- [ ] **Local Authentication**: Fix `fetch_id_token` issues in local development to avoid subprocess fallback
- [ ] **Agent Engine Support**: Test and ensure compatibility with Agent Engine deployments
- [ ] **Error Handling**: Improve error handling and user feedback for authentication failures

## Troubleshooting

### Authentication Issues
- Verify that your Service Account has the necessary permissions
- For local development, ensure ADC is properly configured
- Check that the App URL and App Name are correctly set in the valve configuration

### Streaming Issues
- If streaming appears choppy, try adjusting the **Streaming Delay** setting
- Ensure your network connection is stable for real-time streaming

### Function Call Display
- Function calls and responses are automatically formatted in collapsible details sections
- Status updates show when tools are being executed

## Architecture

The pipe consists of several modular components:

- **Session Management**: Initializes and manages ADK sessions
- **Authentication**: Handles Google Cloud identity token generation
- **Streaming Processing**: Manages Server-Sent Events from ADK
- **Event Handling**: Routes different event types (text, function calls, actions)
- **Response Formatting**: Creates Open WebUI-compatible streaming responses

## Contributing

Feel free to submit issues and pull requests to improve this integration. Key areas for contribution:
- Performance optimizations
- Error handling improvements
- Support for additional ADK deployment methods
- Enhanced configuration options
