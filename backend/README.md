# Respondr Backend

This is the FastAPI backend for the SCVSAR Response Tracker application. It processes webhook messages from GroupMe and uses Azure OpenAI to extract responder information.

## Azure OpenAI Integration

This application uses Azure OpenAI for text processing. To configure the application, create a `.env` file in the `backend` directory with the following variables:

```env
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4.1-mini
AZURE_OPENAI_API_VERSION=2025-01-01-preview
```

## Local Development Setup

1. **Install Dependencies**:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Create Environment File**:
   Create a `.env` file with your Azure OpenAI credentials (see above).

3. **Run the Application**:
   ```bash
   uvicorn main:app --reload
   ```

The application will start on http://localhost:8000 by default.

## Testing the Integration

### Test Azure OpenAI Connection

You can test the Azure OpenAI integration by running:

```bash
python test_azure_openai.py
```

This will validate that your credentials are working and that the application can connect to Azure OpenAI.

### Test the Webhook Endpoint

Run the comprehensive test suite:

```bash
python test_webhook.py
```

This sends synthetic test messages to the webhook endpoint and verifies the complete pipeline.

### Simple Connection Test

For a quick connection test:

```bash
python simple_test.py
```

## API Endpoints

The backend provides the following endpoints:

- `POST /webhook` - Receives responder messages and extracts vehicle and ETA information
- `GET /api/responders` - Returns all processed responder messages in JSON format
- `GET /dashboard` - Simple HTML dashboard showing responder information
- `GET /` - Serves the frontend application (when built)

## Message Processing

The application processes GroupMe webhook messages and extracts:

- **Vehicle Assignment**: SAR vehicles (e.g., SAR78, SAR-4) or POV (Personal Owned Vehicle)
- **ETA Information**: Either clock time (e.g., "23:30") or duration (e.g., "15 minutes")
- **Timestamp**: When the message was received
- **Responder Name**: Who sent the message

Example input message:
```
"I'm responding with SAR78, ETA 15 minutes"
```

Example extracted data:
```json
{
  "vehicle": "SAR78",
  "eta": "15 minutes",
  "name": "John Smith",
  "timestamp": "2025-07-31 14:30:00",
  "text": "I'm responding with SAR78, ETA 15 minutes"
}
```

## Container Build

The backend is containerized as part of the multi-stage Docker build. See the main Dockerfile in the project root.

## Environment Variables

Required environment variables:

- `AZURE_OPENAI_API_KEY`: Your Azure OpenAI API key
- `AZURE_OPENAI_ENDPOINT`: Your Azure OpenAI endpoint URL  
- `AZURE_OPENAI_DEPLOYMENT`: The deployment name (model)
- `AZURE_OPENAI_API_VERSION`: API version to use

## Error Handling

The application includes comprehensive error handling:

- Invalid Azure OpenAI responses fall back to "Unknown" values
- Network failures are logged and handled gracefully
- Malformed webhook data is rejected with appropriate error messages

## Logging

The application uses Python's standard logging module with INFO level logging by default. Logs include:

- Incoming webhook requests
- Azure OpenAI API calls and responses
- Parsing results and any errors
- Application startup information
