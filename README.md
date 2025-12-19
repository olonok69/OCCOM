# Bot In a Box (BIAB) V2
This repo is for the Bot In a Box v2, this repo will have the following structure


## Architecture and Requirements

Refer to Confluence: https://ebrdtech.atlassian.net/wiki/spaces/AI1/pages/5697929281/AI+Bot-in-a-Box+V2+Technical+requirements+and+User+Journey


## Folder Structure

- Frontend
    Streamlit application that calls the Backend API via APIM.

- Backend
    FastAPI backend that handles the business logic and calls the services. It uses LlamaIndex as a framework for RAG and connectivity to services.

## Backend
Endpoint in draft: https://ebrdtech.atlassian.net/wiki/spaces/AI1/pages/5677809697/AI+Bot-in-a-Box+V2+-+Proposed+Backend

## TODO
- Change how to check for progress report in the task based mananger to get system update
- change the ingestor to also clear the previous index if it existed if same file being uploaded in
- Image extraction from pdf files
-

