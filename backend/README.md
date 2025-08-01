# Azure OpenAI Integration

This application uses Azure OpenAI for text processing. To configure the application, create a `.env` file in the `backend` directory with the following variables:

```
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
AZURE_OPENAI_API_VERSION=2023-05-15
```

## Testing the Integration

You can test the Azure OpenAI integration by running:

```bash
cd backend
python test_azure_openai.py
```

This will validate that your credentials are working and that the application can connect to Azure OpenAI.

## Running the Application

To run the application:

```bash
cd backend
uvicorn main:app --reload
```

The application will start on http://localhost:8000 by default.

## Endpoints

- `POST /webhook` - Receives responder messages and extracts vehicle and ETA information
- `GET /api/responders` - Returns all processed responder messages
- `GET /dashboard` - Simple HTML dashboard showing responder information
- `GET /` - Serves the frontend application
