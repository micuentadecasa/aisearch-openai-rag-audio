
cd app
cd backend
python app.py


---- then in other terminal

for testing websockets
wscat -c ws://localhost:8765/realtime


{"type":"conversation.item.create","item":{"type":"function_call","name":"search","call_id":"call_12345","arguments":"{ \"query\": \"Tell me about AI\" }"}}

esto falla, no le gusta 
--- for testing the frontend

cd app/frontend
npm run dev
