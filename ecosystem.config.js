module.exports = {
  apps: [
    {
      name: 'api_server',
      script: 'uvicorn',
      args: 'shared.api_server:app --host 0.0.0.0 --port 8000',
      interpreter: 'python3',
      env: {
        PYTHONPATH: '.'
      }
    },
    {
      name: 'mcp_server',
      script: 'market_sentiment_tool/backend/mcp_server.py',
      interpreter: 'python3',
      env: {
        PYTHONPATH: '.'
      }
    },
    {
      name: 'orchestrator',
      script: 'market_sentiment_tool/backend/orchestrator.py',
      interpreter: 'python3',
      env: {
        PYTHONPATH: '.'
      }
    },
    {
      name: 'scanner_slow',
      script: 'shared/background_scanner.py',
      interpreter: 'python3',
      env: {
        PYTHONPATH: '.'
      }
    },
    {
      name: 'scanner_fast',
      script: 'shared/fast_scanner.py',
      interpreter: 'python3',
      env: {
        PYTHONPATH: '.'
      }
    }
  ]
};
